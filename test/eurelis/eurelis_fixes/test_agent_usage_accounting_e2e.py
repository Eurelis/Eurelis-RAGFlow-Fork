# Eurelis — non-régression AILAB-43 : tokens et durée d'un agent canvas comptabilisés à chaque exécution.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Préprod Synerga (v0.26.3-eurelis.13) : parcours complet de l'agent CRM via l'API (comme le Shield),
# `api_4_conversation.tokens = 0`, `duration = 0.0` et AUCUNE ligne `usage_log`, alors que
# `workflow_finished.usage` annonçait 26 822 tokens. Les étapes arrêtées sur une pause n'étaient
# jamais comptées.
#
# Canvas (fixtures/agent_usage_canvas.json, LLM Ollama) :
#   Begin → LLM:Draft → UserFillUp:Valid {retour} → LLM:Final → Message:Fin
# Parcours : départ → pause → reprise → fin. La session est créée avec le `user_id` de l'utilisateur
# de test, ce qui permet de relire les lignes usage_log via /usage-stats/me/session/<id>.
# Rouge sur v0.26.3-eurelis.13 (tokens 0, aucune ligne), vert avec le correctif.

import json
from pathlib import Path

import pytest

from configs import CHAT_MODEL, HOST_ADDRESS, VERSION, model_ref
from libs.agents import client, ensure_agent, events, ok, stream_agent
from libs.ragflow_api import get_own_tenant_id

AGENT_TITLE = "eurelis-usage-accounting-agent"
CANVAS_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_usage_canvas.json"


@pytest.fixture(scope="module")
def run(token):
    user_id = get_own_tenant_id(HOST_ADDRESS, f"Bearer {token}")
    dsl = json.loads(CANVAS_FILE.read_text().replace("__CHAT_MODEL__", model_ref(CHAT_MODEL)))
    with client(token) as c:
        agent_id = ensure_agent(c, AGENT_TITLE, dsl, "Agent AILAB-43 : comptabilisation de l'usage")
        base = f"/api/{VERSION}/agents/{agent_id}/sessions"
        sid = ok(c.post(base, json={"release": True, "user_id": user_id, "name": "ailab43-usage"}))["data"]["id"]
        created = ok(c.get(f"{base}/{sid}"))["data"]
        start = stream_agent(c, {"agent_id": agent_id, "session_id": sid, "query": "", "inputs": {}})
        resume = stream_agent(c, {"agent_id": agent_id, "session_id": sid, "query": "",
                                  "inputs": {"retour": {"type": "paragraph", "value": "Plus court"}}})
        done = ok(c.get(f"{base}/{sid}"))["data"]
        stats = c.get(f"/api/{VERSION}/usage-stats/me/session/{sid}").json()
        yield {"sid": sid, "agent_id": agent_id, "created": created, "start": start, "resume": resume,
               "done": done, "stats": stats}
        c.delete(f"{base}/{sid}")


def _usage(frames) -> dict:
    return next(f["data"]["usage"] for f in frames if isinstance(f, dict) and f.get("event") == "workflow_finished")


@pytest.mark.p0
def test_flow_pauses_then_finishes(run):
    assert events(run["start"])[-2] == "user_inputs", events(run["start"])
    assert events(run["resume"])[-2] == "workflow_finished", events(run["resume"])
    assert _usage(run["resume"])["total_tokens"] > 0, "le modèle n'a déclaré aucun token"


@pytest.mark.p0
def test_session_counts_tokens_and_duration(run):
    done, created = run["done"], run["created"]
    assert done["round"] - created["round"] == 2, f"round : {created['round']} → {done['round']}"
    assert done["tokens"] > _usage(run["resume"])["total_tokens"], \
        f"tokens de session {done['tokens']} : la pause (LLM:Draft) doit être comptée en plus de la fin"
    assert done["duration"] > 0


@pytest.mark.p0
def test_one_usage_log_line_per_run(run):
    stats = run["stats"]
    assert stats.get("code") == 0, f"aucune ligne usage_log pour la session : {stats}"
    data = stats["data"]
    assert data["source"] == "agent" and data["resource_id"] == run["agent_id"]
    turns = data["by_turn"]
    assert len(turns) == 2, turns
    assert all(t["tokens"] > 0 and t["duration_ms"] > 0 for t in turns), turns
    # La 2e exécution = workflow_finished.usage ; la session cumule les deux.
    assert turns[1]["tokens"] == _usage(run["resume"])["total_tokens"]
    assert data["totals"]["tokens"] == run["done"]["tokens"]
