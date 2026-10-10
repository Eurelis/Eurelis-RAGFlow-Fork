# Eurelis — P0 : contrat de l'envoi de fichier d'agent et du téléchargement des pièces générées (031, T008).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Le Shield relaie POST /agents/{id}/upload puis réinjecte l'objet renvoyé dans inputs.<champ>.value ;
# il relaie GET /agents/attachments/{id}/download pour les pièces produites par un composant Message.

import pytest

from configs import VERSION
from libs.agents import events, ok, stream_agent
from libs.contract import assert_valid
from schemas.agents import MESSAGE_END_DATA_SCHEMA, UPLOAD_SCHEMA


@pytest.mark.p0
def test_upload_returns_file_object(agent_member, contract_agent_id):
    body = ok(agent_member.post(f"/api/{VERSION}/agents/{contract_agent_id}/upload",
                                files={"file": ("note.txt", b"Note de synthese contrat", "text/plain")}))
    assert isinstance(body["data"], dict), "un fichier envoyé doit renvoyer un objet (pas une liste)"
    assert_valid(body["data"], UPLOAD_SCHEMA, label="upload")


@pytest.mark.p0
def test_generated_attachment_download(agent_member, contract_agent_id):
    base = f"/api/{VERSION}/agents/{contract_agent_id}/sessions"
    sid = ok(agent_member.post(base, json={"release": True, "user_id": "contract-att"}))["data"]["id"]
    try:
        stream_agent(agent_member, {"agent_id": contract_agent_id, "session_id": sid, "query": "",
                                    "inputs": {"sujet": {"type": "line", "value": "Pièce"},
                                               "regime": {"type": "options", "value": "IS"}}})
        frames = stream_agent(agent_member, {"agent_id": contract_agent_id, "session_id": sid, "query": "",
                                             "inputs": {"retour": {"type": "paragraph", "value": "OK"}}})
        ends = [f["data"] for f in frames if isinstance(f, dict) and f.get("event") == "message_end"
                and f["data"].get("attachment")]
        assert ends, f"aucune pièce jointe dans message_end : {events(frames)}"
        assert_valid(ends[-1], MESSAGE_END_DATA_SCHEMA, label="message_end")
        att = ends[-1]["attachment"]
        r = agent_member.get(f"/api/{VERSION}/agents/attachments/{att['doc_id']}/download", params={"ext": att["format"]})
        assert r.status_code == 200 and r.content, "téléchargement de la pièce générée impossible"
        assert r.headers.get("content-type", "").startswith("text/markdown")
    finally:
        ok(agent_member.delete(f"{base}/{sid}"))
