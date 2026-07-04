# Eurelis — seed idempotent du jeu de données de référence (tenant, Ollama, dataset, doc, chat).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Usage :  python test/eurelis/seed.py        (ou : make -C test/eurelis e2e-seed)
# Rejouable : chaque étape vérifie l'existant avant de créer. Sort en code != 0 si échec.

import sys
import time

import httpx

from configs import (
    CHAT_MODEL,
    CHAT_MODEL_PII,
    HOST_ADDRESS,
    HTTP_TIMEOUT,
    PARSE_TIMEOUT,
    REF_CHAT_NAME,
    REF_CHAT_PII_NAME,
    REF_DATASET_NAME,
    REF_DOC_NAME,
    REF_DOC_TEXT,
    REF_SEARCH_NAME,
    VERSION,
    model_ref,
)
from libs.ragflow_api import (
    ensure_default_ollama_models,
    get_api_token,
    login,
    register_user,
)


def _api(client: httpx.Client, method: str, path: str, **kw) -> dict:
    r = client.request(method, f"/api/{VERSION}{path}", **kw)
    body = r.json()
    if body.get("code") != 0:
        raise RuntimeError(f"{method} {path} -> code={body.get('code')} msg={body.get('message')!r}")
    return body


def ensure_dataset(client: httpx.Client) -> str:
    # NB : GET /datasets?name=X renvoie 102 « lacks permission » quand AUCUN dataset possédé ne
    # porte ce nom (comportement RAGFlow v0.26.3), ce qui casse le bootstrap sur stack vierge
    # (le helper _api lève dès code != 0). On liste donc SANS filtre (code 0 → datasets possédés)
    # et on filtre le nom côté client. /chats et /searches n'ont pas ce souci (0 sur nom absent).
    all_ds = _api(client, "GET", "/datasets").get("data") or []
    found = [d for d in all_ds if d.get("name") == REF_DATASET_NAME]
    if found:
        return found[0]["id"]
    data = _api(client, "POST", "/datasets", json={"name": REF_DATASET_NAME})["data"]
    print(f"  dataset créé : {REF_DATASET_NAME} (emb={data.get('embedding_model')})")
    return data["id"]


def ensure_document(client: httpx.Client, dataset_id: str) -> str:
    docs = (_api(client, "GET", f"/datasets/{dataset_id}/documents")["data"] or {}).get("docs") or []
    if docs:
        return docs[0]["id"]
    r = client.post(
        f"/api/{VERSION}/datasets/{dataset_id}/documents",
        files={"file": (REF_DOC_NAME, REF_DOC_TEXT.encode(), "text/plain")},
    )
    body = r.json()
    if body.get("code") != 0:
        raise RuntimeError(f"upload doc -> {body.get('message')!r}")
    print(f"  document uploadé : {REF_DOC_NAME}")
    return body["data"][0]["id"]


def parse_and_wait(client: httpx.Client, dataset_id: str, doc_id: str) -> None:
    def status():
        docs = (_api(client, "GET", f"/datasets/{dataset_id}/documents")["data"] or {}).get("docs") or []
        d = next((x for x in docs if x["id"] == doc_id), None) or {}
        return d.get("run"), d.get("progress", 0)

    run, _ = status()
    if run == "DONE":
        return
    _api(client, "POST", f"/datasets/{dataset_id}/chunks", json={"document_ids": [doc_id]})
    deadline = time.monotonic() + PARSE_TIMEOUT
    while time.monotonic() < deadline:
        run, progress = status()
        if run == "DONE":
            print(f"  parse : DONE")
            return
        if run in ("FAIL", "CANCEL"):
            raise RuntimeError(f"parse échoué (run={run})")
        time.sleep(4)
    raise RuntimeError(f"parse : timeout après {PARSE_TIMEOUT}s (dernier run={run})")


def ensure_chat(client: httpx.Client, dataset_id: str, name: str, llm_id: str = None) -> str:
    # /chats renvoie data={"chats": [...]} (dict), contrairement à /datasets qui renvoie une liste.
    found = (_api(client, "GET", "/chats", params={"name": name})["data"] or {}).get("chats") or []
    if found:
        return found[0]["id"]
    payload = {"name": name, "dataset_ids": [dataset_id]}
    if llm_id:
        payload["llm_id"] = llm_id
    data = _api(client, "POST", "/chats", json=payload)["data"]
    print(f"  chat créé : {name}" + (f" (llm={llm_id})" if llm_id else ""))
    return data["id"]


def ensure_search(client: httpx.Client, dataset_id: str, name: str = REF_SEARCH_NAME) -> str:
    # /searches renvoie data={"search_apps": [...], "total": N} (dict), comme /chats.
    found = (_api(client, "GET", "/searches", params={"keywords": name})["data"] or {}).get("search_apps") or []
    for s in found:
        if s["name"] == name:
            return s["id"]
    payload = {
        "name": name,
        "search_config": {
            "kb_ids": [dataset_id],           # obligatoire : sinon /completions renvoie 400 "kb_ids is required"
            "summary": True,                  # active le résumé (flag lu par le Shield)
            "related_search": True,           # active les suggestions
            "chat_id": model_ref(CHAT_MODEL),  # modèle du résumé : async_ask n'a pas de fallback défaut
        },
    }
    # POST /searches -> data={"search_id": "..."}
    data = _api(client, "POST", "/searches", json=payload)["data"]
    print(f"  search créée : {name}")
    return data["search_id"]


def main() -> int:
    print("Seed Eurelis — amorçage du jeu de référence")
    register_user(HOST_ADDRESS)
    auth = login(HOST_ADDRESS)
    ensure_default_ollama_models(HOST_ADDRESS, auth)
    print("  tenant amorcé sur Ollama (chat + embedding)")
    token = get_api_token(HOST_ADDRESS, auth)

    with httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        dataset_id = ensure_dataset(client)
        doc_id = ensure_document(client, dataset_id)
        parse_and_wait(client, dataset_id, doc_id)
        chat_id = ensure_chat(client, dataset_id, REF_CHAT_NAME)
        chat_pii_id = ensure_chat(client, dataset_id, REF_CHAT_PII_NAME, llm_id=model_ref(CHAT_MODEL_PII))
        search_id = ensure_search(client, dataset_id)

    print("Seed terminé :")
    print(f"  dataset_id   = {dataset_id}")
    print(f"  chat_id      = {chat_id}       (sans PII)")
    print(f"  chat_pii_id  = {chat_pii_id}   (avec PII, {CHAT_MODEL_PII})")
    print(f"  search_id    = {search_id}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"SEED ÉCHEC : {e}", file=sys.stderr)
        sys.exit(1)
