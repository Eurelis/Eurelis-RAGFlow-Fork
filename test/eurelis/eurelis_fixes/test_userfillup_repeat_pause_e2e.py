# Eurelis — non-régression AILAB-43 (CRM v1.2) : boucle de validation UserFillUp via l'API agents (SSE).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# L'agent CRM v1.2 propose plusieurs tours de modification par étape : « Modifier » renvoie sur
# l'agent puis sur le MÊME UserFillUp. Jusqu'à v0.26.3-eurelis.13, le 2e passage ne faisait plus de
# pause (entrées du tour précédent jamais vidées) et le Switch relisait `Modifier` → boucle infinie.
#
# Canvas sans LLM (fixtures/agent_userfillup_loop_canvas.json) :
#   Begin → Message:Version → UserFillUp:Valid {decision: Valider|Modifier, retour facultatif}
#   → Switch:Decision (decision = Valider → Message:Fin ; sinon → Message:Version)
# Parcours : départ → pause ; Modifier → pause ; Modifier → pause ; Valider → workflow_finished.
# Le flux SSE est borné (nombre de node_finished + timeout de lecture) : la version boguée échoue
# proprement au lieu de bloquer la suite. Rouge sur v0.26.3-eurelis.13, vert avec le correctif.

import json
from pathlib import Path

import httpx
import pytest

from configs import VERSION
from libs.agents import client, ensure_agent, events, ok, session_dsl

AGENT_TITLE = "eurelis-userfillup-loop-agent"
CANVAS_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_userfillup_loop_canvas.json"
MAX_NODE_FINISHED = 12  # un tour sain en émet au plus 4
READ_TIMEOUT = 30

MODIFIER = {"decision": {"type": "options", "value": "Modifier"}, "retour": {"type": "paragraph", "value": "Plus court"}}
VALIDER = {"decision": {"type": "options", "value": "Valider"}, "retour": {"type": "paragraph", "value": ""}}


def _stream_bounded(c: httpx.Client, body: dict) -> list:
    """Comme libs.agents.stream_agent, mais coupe le flux s'il dépasse MAX_NODE_FINISHED (boucle)."""
    frames = []
    with c.stream("POST", f"/api/{VERSION}/agents/chat/completions", json={"stream": True, **body},
                  timeout=httpx.Timeout(READ_TIMEOUT)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            frames.append("[DONE]" if raw == "[DONE]" else json.loads(raw))
            if events(frames).count("node_finished") > MAX_NODE_FINISHED:
                pytest.fail(f"flux non borné, pause sautée : {events(frames)[-12:]}")
    return frames


def _finished(frames) -> list:
    return [f["data"]["component_id"] for f in frames if isinstance(f, dict) and f.get("event") == "node_finished"]


@pytest.fixture(scope="module")
def session(token):
    with client(token) as c:
        agent_id = ensure_agent(c, AGENT_TITLE, json.loads(CANVAS_FILE.read_text()),
                                "Agent AILAB-43 : boucle de validation UserFillUp")
        base = f"/api/{VERSION}/agents/{agent_id}/sessions"
        sid = ok(c.post(base, json={"release": True, "user_id": "ailab43-loop", "name": "ailab43-loop"}))["data"]["id"]
        turn = lambda inputs: _stream_bounded(c, {"agent_id": agent_id, "session_id": sid, "query": "", "inputs": inputs})  # noqa: E731
        state = lambda: session_dsl(ok(c.get(f"{base}/{sid}"))["data"])  # noqa: E731
        yield turn, state
        c.delete(f"{base}/{sid}")


def _assert_pause(frames, dsl, label):
    ev = events(frames)
    assert frames and frames[-1] == "[DONE]", f"{label} : flux incomplet ({ev})"
    assert ev[-2] == "user_inputs", f"{label} : pas de pause ({ev})"
    assert "workflow_finished" not in ev
    pause = frames[ev.index("user_inputs")]["data"]
    assert {"decision", "retour"} <= set(pause["inputs"]), f"{label} : champs de pause {pause['inputs']}"
    assert dsl["path"] and dsl["path"][0] == "UserFillUp:Valid", f"{label} : pause non persistée, path={dsl['path']}"
    assert _finished(frames).count("Message:Version") == 1, f"{label} : proposition non régénérée ({_finished(frames)})"


@pytest.mark.p0
def test_validation_loop_pauses_on_each_pass(session):
    turn, state = session
    _assert_pause(turn({}), state(), "départ")
    _assert_pause(turn(MODIFIER), state(), "Modifier #1")
    _assert_pause(turn(MODIFIER), state(), "Modifier #2")

    frames = turn(VALIDER)
    ev = events(frames)
    assert frames[-1] == "[DONE]" and ev[-2] == "workflow_finished", f"Valider : fin non signalée ({ev})"
    assert _finished(frames)[-1] == "Message:Fin"
    assert "Message:Version" not in _finished(frames)
