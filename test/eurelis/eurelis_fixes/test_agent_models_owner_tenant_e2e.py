# Eurelis — non-régression AILAB-43 : un membre d'équipe SANS fournisseur de modèles exécute un agent partagé.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Recette Shield (031, sandbox ai-lab, v0.26.3-eurelis.12) : `POST /agents/{id}/sessions` échoue avec
# « LookupError: Provider OpenAI not found for model gpt-4.1@OpenAI » quand l'utilisateur provisionné par
# le Shield n'a aucun fournisseur — upstream résout les modèles du canvas sur le tenant de l'APPELANT.
# Correctif : modèles résolus sur le tenant du PROPRIÉTAIRE du canvas (comme les assistants), tandis que
# fichiers, sessions et attribution restent chez l'appelant.
#
# Scénario : A (propriétaire, Ollama) publie et partage `team` un agent Begin(question, document:file)
# → LLM → Message(markdown). B (membre, tous fournisseurs retirés) dépose un fichier, crée une session,
# exécute l'agent, lit la réponse (contenu du fichier + réponse LLM) et télécharge la pièce générée.
# Rouge sur v0.26.3-eurelis.12 (création de session), vert avec le correctif.

import json
from pathlib import Path

import pytest

from configs import CHAT_MODEL, VERSION, model_ref
from libs.agents import client, ensure_agent, events, ok, stream_agent, team_member_token

AGENT_TITLE = "eurelis-owner-models-agent"
CANVAS_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_owner_models_canvas.json"
MARKER = "MARQUEUR-AILAB43-7Q2"


@pytest.fixture(scope="module")
def member(token, admin_token):
    """Client de B, après retrait de TOUS ses fournisseurs (test_model_supervision lui en ajoute un).

    Enrôlement propre au module, pas la fixture de session `agent_member_token` : l'instancier ici
    (eurelis_fixes, collecté avant shield_contract) enrôlerait B avant que test_admin_teams ne l'en
    retire, et les contrats agents trouveraient B hors de l'équipe.
    """
    with client(team_member_token(token, admin_token)) as c:
        for provider in ok(c.get(f"/api/{VERSION}/providers"))["data"]:
            ok(c.delete(f"/api/{VERSION}/providers/{provider['name']}"))
        assert ok(c.get(f"/api/{VERSION}/providers"))["data"] == [], "B doit n'avoir aucun fournisseur"
        yield c


@pytest.fixture(scope="module")
def llm_agent_id(token, member):
    dsl = json.loads(CANVAS_FILE.read_text().replace("__CHAT_MODEL__", model_ref(CHAT_MODEL)))
    with client(token) as owner:
        return ensure_agent(owner, AGENT_TITLE, dsl, "Agent LLM AILAB-43 (modèles du propriétaire)")


@pytest.fixture(scope="module")
def run(member, llm_agent_id):
    base = f"/api/{VERSION}/agents/{llm_agent_id}/sessions"
    # Point de rupture sur eurelis.12 : les composants LLM résolvent leur modèle dès la construction du canvas.
    created = member.post(base, json={"release": True, "user_id": "ailab43", "name": "ailab43"})
    body = created.json()
    assert created.status_code == 200 and body.get("code") == 0, f"création de session refusée au membre : {body}"
    sid = body["data"]["id"]
    uploaded = ok(member.post(f"/api/{VERSION}/agents/{llm_agent_id}/upload",
                              files={"file": ("note.txt", f"Le code du dossier est {MARKER}.".encode(), "text/plain")}))["data"]
    frames = stream_agent(member, {"agent_id": llm_agent_id, "session_id": sid, "query": "",
                                   "inputs": {"question": {"type": "line", "value": "Quel est le code du dossier ?"},
                                              "document": {"type": "file", "value": uploaded}}})
    yield {"sid": sid, "base": base, "frames": frames}
    member.delete(f"{base}/{sid}")


def _finished(frames):
    return {f["data"]["component_id"]: f["data"] for f in frames if isinstance(f, dict) and f.get("event") == "node_finished"}


@pytest.mark.p0
def test_member_without_models_runs_owner_llm(run):
    frames = run["frames"]
    assert frames and frames[-1] == "[DONE]", f"flux incomplet : {events(frames)}"
    finished = _finished(frames)
    assert "LLM:Answer" in finished, f"le composant LLM n'a pas tourné : {events(frames)}"
    assert not finished["LLM:Answer"].get("error"), f"erreur du LLM : {finished['LLM:Answer']['error']}"
    text = "".join(f["data"]["content"] for f in frames if isinstance(f, dict) and f.get("event") == "message")
    answer = text.split("REPONSE :", 1)[-1].strip()
    assert answer and "error" not in answer.lower(), f"réponse LLM vide ou en erreur : {text!r}"


@pytest.mark.p0
def test_member_file_is_read_by_agent(run):
    """Le fichier déposé par B (stocké sous B) est relu par l'agent malgré l'exécution sur les modèles de A."""
    text = "".join(f["data"]["content"] for f in run["frames"] if isinstance(f, dict) and f.get("event") == "message")
    assert MARKER in text, f"contenu du fichier déposé absent de la réponse : {text!r}"


@pytest.mark.p0
def test_member_downloads_generated_attachment(run, member):
    ends = [f["data"] for f in run["frames"] if isinstance(f, dict) and f.get("event") == "message_end"
            and f["data"].get("attachment")]
    assert ends, f"aucune pièce générée : {events(run['frames'])}"
    att = ends[-1]["attachment"]
    r = member.get(f"/api/{VERSION}/agents/attachments/{att['doc_id']}/download", params={"ext": att["format"]})
    assert r.status_code == 200 and MARKER.encode() in r.content, "pièce générée non téléchargeable par le membre"


@pytest.mark.p0
def test_session_keeps_caller_user_id(run, member, llm_agent_id):
    """Le rattachement de la session (user_id transmis par l'appelant, filtre de liste) est inchangé."""
    listed = ok(member.get(run["base"], params={"user_id": "ailab43", "dsl": "false", "page_size": 100}))["data"]
    assert run["sid"] in [s["id"] for s in listed], "session absente de la liste filtrée par user_id"
    detail = ok(member.get(f"{run['base']}/{run['sid']}"))["data"]
    assert detail["user_id"] == "ailab43" and detail["dialog_id"] == llm_agent_id
