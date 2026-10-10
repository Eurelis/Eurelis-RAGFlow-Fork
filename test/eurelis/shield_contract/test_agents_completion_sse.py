# Eurelis — P0 : contrat du flux SSE des agents (départ → pause UserFillUp → reprise) consommé par le Shield (031, T009).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Le Shield normalise ce flux : il lit `event`, `session_id`, `node_finished.{component_id, component_name,
# component_type, error, elapsed_time}`, `message.content`, `message_end.{attachment, reference}`,
# `user_inputs.{inputs, tips}` et `workflow_finished`. Il relit aussi l'état persisté de la session
# (`dsl.path`, sorties du UserFillUp) pour détecter une pause et la reprendre.
#
# Régression couverte : eurelis.11 ne persistait AUCUNE session d'agent (append_message : DB.atomic()
# imbriqué dans @DB.connection_context → OperationalError) → la reprise rejouait depuis begin.

import pytest

from configs import VERSION
from libs.agents import events, ok, session_dsl, stream_agent
from libs.contract import assert_valid
from schemas.agents import (
    MESSAGE_DATA_SCHEMA,
    MESSAGE_END_DATA_SCHEMA,
    NODE_FINISHED_DATA_SCHEMA,
    SSE_ENVELOPE_SCHEMA,
    USER_INPUTS_DATA_SCHEMA,
    WORKFLOW_FINISHED_DATA_SCHEMA,
)

DATA_SCHEMAS = {
    "node_finished": NODE_FINISHED_DATA_SCHEMA,
    "message": MESSAGE_DATA_SCHEMA,
    "message_end": MESSAGE_END_DATA_SCHEMA,
    "user_inputs": USER_INPUTS_DATA_SCHEMA,
    "workflow_finished": WORKFLOW_FINISHED_DATA_SCHEMA,
}


def _check_frames(frames, session_id, label):
    assert frames and frames[-1] == "[DONE]", f"{label}: sentinelle [DONE] absente ({events(frames)})"
    for i, f in enumerate(frames[:-1]):
        assert_valid(f, SSE_ENVELOPE_SCHEMA, label=f"{label}[{i}]")
        assert f["session_id"] == session_id
        schema = DATA_SCHEMAS.get(f["event"])
        if schema:
            assert_valid(f["data"], schema, label=f"{label}[{i}] {f['event']}")


@pytest.fixture(scope="module")
def run(agent_member_token, contract_agent_id):
    from libs.agents import client
    c = client(agent_member_token)
    base = f"/api/{VERSION}/agents/{contract_agent_id}/sessions"
    sid = ok(c.post(base, json={"release": True, "user_id": "contract-sse", "name": "contract-sse"}))["data"]["id"]
    start = stream_agent(c, {"agent_id": contract_agent_id, "session_id": sid, "query": "",
                             "inputs": {"sujet": {"type": "line", "value": "Dossier contrat"},
                                        "regime": {"type": "options", "value": "IR"}}})
    paused = ok(c.get(f"{base}/{sid}"))["data"]
    resume = stream_agent(c, {"agent_id": contract_agent_id, "session_id": sid, "query": "",
                              "inputs": {"retour": {"type": "paragraph", "value": "OK contrat"}}})
    done = ok(c.get(f"{base}/{sid}"))["data"]
    yield {"sid": sid, "start": start, "paused": paused, "resume": resume, "done": done}
    c.delete(f"{base}/{sid}")
    c.close()


@pytest.mark.p0
def test_start_streams_until_pause(run):
    frames = run["start"]
    _check_frames(frames, run["sid"], "start")
    ev = events(frames)
    assert "user_inputs" in ev and ev[-2] == "user_inputs", f"le flux doit s'arrêter sur la pause : {ev}"
    assert "workflow_finished" not in ev, "workflow_finished ne doit pas suivre une pause"
    assert "message" in ev and "message_end" in ev
    pause = frames[ev.index("user_inputs")]["data"]
    assert "retour" in pause["inputs"] and "| Poste |" in pause["tips"], "tips/inputs de pause non conformes"


@pytest.mark.p0
def test_agent_session_path_has_no_node_started(run):
    """Comportement figé (031 R3) : la voie session « agent » ne relaie pas node_started ; le Shield le synthétise."""
    assert "node_started" not in events(run["start"])


@pytest.mark.p0
def test_pause_is_persisted(run):
    """Régression eurelis.11 : la session doit être persistée en pause (path[0] = UserFillUp non satisfait)."""
    dsl = session_dsl(run["paused"])
    assert dsl["path"] and dsl["path"][0] == "UserFillUp:Valid", f"pause non persistée : path={dsl['path']}"
    params = dsl["components"]["UserFillUp:Valid"]["obj"]["params"]
    assert params["inputs"]["retour"].get("value") is None
    assert "| Poste |" in params["outputs"]["tips"]["value"], "tips non persistés dans les sorties du UserFillUp"


@pytest.mark.p0
def test_resume_does_not_replay_and_finishes(run):
    frames = run["resume"]
    _check_frames(frames, run["sid"], "resume")
    ev = events(frames)
    finished = [f["data"]["component_id"] for f in frames if isinstance(f, dict) and f.get("event") == "node_finished"]
    assert "begin" not in finished and "Message:Intro" not in finished, f"étapes rejouées à la reprise : {finished}"
    assert ev[-2] == "workflow_finished", f"fin d'exécution non signalée : {ev}"
    text = "".join(f["data"]["content"] for f in frames if isinstance(f, dict) and f.get("event") == "message")
    assert "OK contrat" in text and "```html" in text


@pytest.mark.p0
def test_completed_session_state(run):
    done = run["done"]
    dsl = session_dsl(done)
    assert not done.get("errors")
    assert dsl["components"]["UserFillUp:Valid"]["obj"]["params"]["inputs"]["retour"]["value"] == "OK contrat"
    assistant = [m["content"] for m in done["message"] if m["role"] == "assistant" and m["content"]]
    assert any("```html" in m for m in assistant), "livrable absent de l'historique de session"
