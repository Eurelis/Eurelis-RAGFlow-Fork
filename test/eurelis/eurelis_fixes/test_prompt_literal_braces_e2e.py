# Eurelis — P1 (AILAB-35) : un prompt système contenant des accolades littérales (CSS/JS) ne casse
# plus un assistant rattaché à une base de connaissances.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Régression gardée : `async_chat` rendait le prompt système par `str.format(**kwargs)` ; toute
# accolade littérale (`body { font-family: Arial; }`, JSON, `${x}`…) levait `KeyError(' font-family')`
# et chaque réponse devenait `**ERROR**: ' font-family'`. Le même prompt passait sans base
# (`async_chat_solo` envoie le texte brut). Avec `render_prompt_template`, seuls les paramètres
# déclarés (plus `knowledge`) sont substitués : un seul prompt fonctionne avec et sans base.
#
# Une seule complétion (coûteuse sous émulation) alimente les deux assertions. Le texte arrive en
# deltas : la frame finale porte answer == "" et la référence, on agrège donc les deltas.

import httpx
import pytest

from configs import HOST_ADDRESS, REF_QUERY, VERSION
from libs.sse import stream_completions

CHAT_NAME = "eurelis-literal-braces-chat"
# Retrieval + génération avec un prompt système long, sur un petit modèle local en émulation.
COMPLETION_TIMEOUT = 900

# Prompt « Office » minimal : la base est injectée via {knowledge}, le reste contient les accolades
# qui faisaient planter str.format (CSS, JavaScript, template literal `${…}`).
SYSTEM_PROMPT = (
    "Tu es un assistant. Réponds en français à partir de la base de connaissances ci-dessous.\n"
    "Base de connaissances :\n{knowledge}\n\n"
    "Charte des livrables HTML :\n"
    "```css\nbody { font-family: system-ui, Arial; color: #3C3939; } th { background: #E1E1EA; }\n```\n"
    '```js\nconst THEME = { text: "3C3939" }; const id = () => `<p:cNvPr id="${next++}"`;\n```\n'
)


@pytest.fixture(scope="module")
def braces_client(token):
    """Client dédié à timeout large (le fixture `api` est de portée fonction et à 120 s)."""
    with httpx.Client(base_url=HOST_ADDRESS, headers={"Authorization": f"Bearer {token}"}, timeout=COMPLETION_TIMEOUT) as c:
        yield c


@pytest.fixture(scope="module")
def braces_chat_id(braces_client, ref_dataset_id):
    """Assistant AVEC base dont le prompt système contient des accolades littérales. Supprimé en fin de module."""
    api = braces_client
    existing = (api.get(f"/api/{VERSION}/chats", params={"name": CHAT_NAME}).json().get("data") or {}).get("chats") or []
    for chat in existing:
        api.request("DELETE", f"/api/{VERSION}/chats", json={"ids": [chat["id"]]})

    r = api.post(
        f"/api/{VERSION}/chats",
        json={
            "name": CHAT_NAME,
            "dataset_ids": [ref_dataset_id],
            "prompt_config": {
                "system": SYSTEM_PROMPT,
                "parameters": [{"key": "knowledge", "optional": False}],
                "empty_response": "",
                "prologue": "Bonjour.",
            },
        },
    )
    assert r.status_code == 200 and r.json().get("code") == 0, r.text
    chat_id = r.json()["data"]["id"]
    yield chat_id
    api.request("DELETE", f"/api/{VERSION}/chats", json={"ids": [chat_id]})


@pytest.fixture(scope="module")
def braces_completion(braces_client, braces_chat_id):
    """Frames `data` (dicts) d'une complétion sur le chat à accolades — une seule génération pour le module."""
    api = braces_client
    r = api.post(f"/api/{VERSION}/chats/{braces_chat_id}/sessions", json={"name": "ailab-35"})
    assert r.status_code == 200 and r.json().get("code") == 0, r.text
    sid = r.json()["data"]["id"]
    try:
        frames = stream_completions(api, braces_chat_id, REF_QUERY, sid)
    finally:
        api.request("DELETE", f"/api/{VERSION}/chats/{braces_chat_id}/sessions", json={"ids": [sid]})
    data = [f["data"] for f in frames if isinstance(f, dict) and isinstance(f.get("data"), dict)]
    assert data, f"aucune frame de réponse reçue : {frames[:3]}"
    return data


@pytest.mark.p1
def test_literal_braces_prompt_with_dataset_answers(braces_completion):
    """Cœur du correctif : aucune frame `**ERROR**` et un texte généré non vide malgré les accolades du prompt."""
    errors = [d["answer"] for d in braces_completion if "**ERROR**" in (d.get("answer") or "")]
    assert not errors, f"le prompt avec accolades littérales fait encore planter l'assistant : {errors[0]!r}"

    text = "".join(d.get("answer") or "" for d in braces_completion)
    assert text.strip(), "aucun texte généré (deltas vides)"


@pytest.mark.p1
def test_literal_braces_prompt_still_uses_the_dataset(braces_completion):
    """Contrôle : la base est bien interrogée (chemin `async_chat` avec retrieval, pas le chemin solo)."""
    chunks = [c for d in braces_completion for c in ((d.get("reference") or {}).get("chunks") or [])]
    assert chunks, "aucun chunk de référence : le retrieval sur la base n'a pas eu lieu"
