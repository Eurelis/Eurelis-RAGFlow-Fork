# Eurelis — P1 : matrice INDÉPENDANTE de logging des tokens par (source, token_type).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Chaque test isole UNE méthode de logging via un scénario qui ne déclenche qu'elle, et vérifie que
# la cellule ciblée augmente ET (quand c'est isolable) que les cellules voisines n'augmentent pas.
#
# Couvert : chat/llm, chat/embedding, ingestion/embedding, ingestion/llm, search/llm, search/embedding.
# NON couvert (palier lourd) : agent/* — nécessite un agent (canvas DSL) exécutant l'outil retrieval ;
#   coûteux et instable avec un modèle 0.5B. Voir la stratégie.

import time
import uuid

import pytest

from configs import (
    CHAT_MODEL,
    HOST_ADDRESS,
    HTTP_TIMEOUT,
    PARSE_TIMEOUT,
    REF_DATASET_NAME,
    REF_DOC_TEXT,
    VERSION,
    model_ref,
    rerank_ref,
)
from libs.sse import stream_completions
from libs.usage import delta, usage_matrix

pytestmark = pytest.mark.p1


# --- Helpers d'action ------------------------------------------------------------------------
def _ingest(api, name: str, parser_config: dict, text: str = REF_DOC_TEXT) -> str:
    """Crée un dataset (purge préalable), ingère un doc et attend le parse. Renvoie l'id (à supprimer)."""
    for ds in api.get(f"/api/{VERSION}/datasets", params={"name": name}).json().get("data") or []:
        api.request("DELETE", f"/api/{VERSION}/datasets", json={"ids": [ds["id"]]})
    dsid = api.post(
        f"/api/{VERSION}/datasets",
        json={"name": name, "chunk_method": "naive", "parser_config": parser_config},
    ).json()["data"]["id"]
    doc = api.post(
        f"/api/{VERSION}/datasets/{dsid}/documents",
        files={"file": (f"{name}.txt", text.encode(), "text/plain")},
    ).json()["data"][0]["id"]
    api.post(f"/api/{VERSION}/datasets/{dsid}/chunks", json={"document_ids": [doc]})
    deadline = time.monotonic() + PARSE_TIMEOUT
    while time.monotonic() < deadline:
        docs = (api.get(f"/api/{VERSION}/datasets/{dsid}/documents").json()["data"] or {}).get("docs") or []
        run = docs[0]["run"] if docs else None
        if run == "DONE":
            time.sleep(3)  # laisser le flush des tokens LLM d'ingestion se terminer
            return dsid
        assert run != "FAIL", "parse en échec"
        time.sleep(4)
    raise AssertionError("parse : timeout")


def _run_search(api, dataset_id: str, question: str):
    """Crée un search app (avec chat_id), déclenche la complétion (flux `search`), supprime."""
    sid = api.post(
        f"/api/{VERSION}/searches",
        json={"name": "eurelis-matrix-search", "search_config": {"kb_ids": [dataset_id], "chat_id": model_ref(CHAT_MODEL)}},
    ).json()["data"]["search_id"]
    try:
        with api.stream("POST", f"/api/{VERSION}/searches/{sid}/completions",
                        json={"question": question, "kb_ids": [dataset_id]}) as resp:
            for _ in resp.iter_lines():
                pass
    finally:
        api.request("DELETE", f"/api/{VERSION}/searches/{sid}")


@pytest.fixture
def ref_dataset_id(api):
    ds = api.get(f"/api/{VERSION}/datasets", params={"name": REF_DATASET_NAME}).json()["data"]
    assert ds, "dataset de référence introuvable"
    return ds[0]["id"]


# --- chat -----------------------------------------------------------------------------------
def test_chat_llm_isolated(api):
    """Un chat SANS base → seule la cellule (chat, llm) augmente ; (chat, embedding) reste inchangée."""
    chat_id = api.post(f"/api/{VERSION}/chats", json={"name": "eurelis-matrix-nokb"}).json()["data"]["id"]
    try:
        sid = api.post(f"/api/{VERSION}/chats/{chat_id}/sessions", json={"name": "x"}).json()["data"]["id"]
        before = usage_matrix(api)
        stream_completions(api, chat_id, "Bonjour, qui es-tu ?", sid)
        time.sleep(1)
        d = delta(before, usage_matrix(api))
        assert d.get(("chat", "llm"), 0) > 0, f"(chat, llm) non logué : {d}"
        assert d.get(("chat", "embedding"), 0) == 0, f"embedding logué à tort (chat sans base) : {d}"
    finally:
        api.request("DELETE", f"/api/{VERSION}/chats", json={"ids": [chat_id]})


def test_chat_embedding_logged(api, ref_chat_id):
    """Un chat AVEC base → la cellule (chat, embedding) augmente (embedding de requête du retrieval)."""
    sid = api.post(f"/api/{VERSION}/chats/{ref_chat_id}/sessions", json={"name": "x"}).json()["data"]["id"]
    try:
        before = usage_matrix(api)
        stream_completions(api, ref_chat_id, "Que fait Eurelis avec RAGFlow ?", sid)
        time.sleep(1)
        d = delta(before, usage_matrix(api))
        assert d.get(("chat", "embedding"), 0) > 0, f"(chat, embedding) non logué : {d}"
        assert d.get(("chat", "llm"), 0) > 0, f"(chat, llm) non logué : {d}"
    finally:
        api.request("DELETE", f"/api/{VERSION}/chats/{ref_chat_id}/sessions", json={"ids": [sid]})


# --- ingestion ------------------------------------------------------------------------------
def test_ingestion_embedding_isolated(api):
    """Parse NAIVE → seule (ingestion, embedding) augmente ; (ingestion, llm) reste à zéro."""
    before = usage_matrix(api)
    dsid = _ingest(api, "eurelis-matrix-naive", {"auto_keywords": 0, "auto_questions": 0})
    try:
        d = delta(before, usage_matrix(api))
        assert d.get(("ingestion", "embedding"), 0) > 0, f"(ingestion, embedding) non logué : {d}"
        assert d.get(("ingestion", "llm"), 0) == 0, f"llm logué à tort en mode naive : {d}"
    finally:
        api.request("DELETE", f"/api/{VERSION}/datasets", json={"ids": [dsid]})


def test_ingestion_llm_logged(api):
    """
    Parse avec mots-clés + questions → les cellules (ingestion, llm) ET (ingestion, embedding) augmentent.

    IMPORTANT : l'extraction mots-clés/questions passe par un **cache LLM** (Redis, clé =
    llm_name + contenu). Sur un cache hit, l'appel LLM est sauté → aucun token n'est comptabilisé.
    Le test utilise donc un **contenu unique** à chaque exécution (garantit un cache miss et un
    logging déterministe). Corollaire produit : les tokens LLM d'ingestion sont sous-comptés quand un
    même contenu de chunk se répète (le cache est global par contenu) — comportement correct (pas
    d'appel = pas de tokens), mais à garder en tête pour l'interprétation des stats.
    """
    unique = uuid.uuid4().hex
    text = f"Note {unique}.\n\n" + "\n\n".join(
        f"Section {i} ({unique}). {REF_DOC_TEXT} RAGFlow structure la compréhension de documents."
        for i in range(1, 7)
    )
    before = usage_matrix(api)
    dsid = _ingest(
        api,
        "eurelis-matrix-llm",
        {"auto_keywords": 3, "auto_questions": 2, "chunk_token_num": 64},
        text=text,
    )
    try:
        d = delta(before, usage_matrix(api))
        assert d.get(("ingestion", "llm"), 0) > 0, f"(ingestion, llm) non logué : {d}"
        assert d.get(("ingestion", "embedding"), 0) > 0, f"(ingestion, embedding) non logué : {d}"
    finally:
        api.request("DELETE", f"/api/{VERSION}/datasets", json={"ids": [dsid]})


# --- search ---------------------------------------------------------------------------------
def test_search_llm_and_embedding_logged(api, ref_dataset_id):
    """Le flux de recherche IA logue (search, llm) ET (search, embedding)."""
    before = usage_matrix(api)
    _run_search(api, ref_dataset_id, "Que fait Eurelis ?")
    time.sleep(1)
    d = delta(before, usage_matrix(api))
    assert d.get(("search", "llm"), 0) > 0, f"(search, llm) non logué : {d}"
    assert d.get(("search", "embedding"), 0) > 0, f"(search, embedding) non logué : {d}"


# --- rerank (câblage du logging token_type="rerank" de bout en bout) -------------------------
def test_chat_rerank_logged(api, ref_dataset_id):
    """Un chat AVEC base ET reranker configuré → une vraie requête produit une ligne (chat, rerank)."""
    chat_id = api.post(
        f"/api/{VERSION}/chats",
        json={"name": "eurelis-matrix-rerank-chat", "dataset_ids": [ref_dataset_id], "rerank_id": rerank_ref()},
    ).json()["data"]["id"]
    try:
        sid = api.post(f"/api/{VERSION}/chats/{chat_id}/sessions", json={"name": "x"}).json()["data"]["id"]
        before = usage_matrix(api)
        stream_completions(api, chat_id, "Que fait Eurelis avec RAGFlow ?", sid)
        time.sleep(1)
        d = delta(before, usage_matrix(api))
        assert d.get(("chat", "rerank"), 0) > 0, f"(chat, rerank) non logué : {d}"
    finally:
        api.request("DELETE", f"/api/{VERSION}/chats", json={"ids": [chat_id]})


def test_search_rerank_logged(api, ref_dataset_id):
    """Un search app AVEC reranker configuré → une vraie requête produit une ligne (search, rerank)."""
    sid = api.post(
        f"/api/{VERSION}/searches",
        json={
            "name": "eurelis-matrix-rerank-search",
            "search_config": {"kb_ids": [ref_dataset_id], "chat_id": model_ref(CHAT_MODEL), "rerank_id": rerank_ref()},
        },
    ).json()["data"]["search_id"]
    try:
        before = usage_matrix(api)
        with api.stream("POST", f"/api/{VERSION}/searches/{sid}/completions",
                        json={"question": "Que fait Eurelis ?", "kb_ids": [ref_dataset_id]}) as resp:
            for _ in resp.iter_lines():
                pass
        time.sleep(1)
        d = delta(before, usage_matrix(api))
        assert d.get(("search", "rerank"), 0) > 0, f"(search, rerank) non logué : {d}"
    finally:
        api.request("DELETE", f"/api/{VERSION}/searches/{sid}")
