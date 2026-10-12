# Eurelis — non-régression AILAB-43 : tokens et durée des agents canvas comptabilisés (api_4_conversation + usage_log).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Jusqu'à v0.26.3-eurelis.13, la complétion d'agent (`canvas_service.completion`, chemin du Shield)
# appelait `append_message` sans tokens ni durée et n'écrivait aucune ligne `usage_log` : la
# consommation des agents était invisible. Le correctif mesure chaque exécution (départ ou reprise)
# avec `AgentRunMeter` : total du collecteur de `Canvas.run` lu après le flux, pause comprise.
#
# Moteur `Canvas.run` réel, sans stack : composants factices « LLM » qui déclarent leur usage au
# collecteur depuis la boucle du canvas et depuis un thread (`thread_pool_exec`, comme un outil), services DB mockés.

import asyncio
import json
import time
from types import SimpleNamespace

import pytest

import agent.canvas as canvas_module
from agent.component import begin, fillup, message
from agent.component.base import ComponentBase, ComponentParamBase
from api.db.db_models import API4Conversation
from api.db.services import canvas_service, eurelis_agent_usage
from api.db.services.llm_service import LLMBundle
from common.misc_utils import thread_pool_exec
from common.token_utils import record_run_token_usage, token_usage_sink

AGENT_ID = "agent-ailab43"
SESSION_ID = "session-ailab43"
SESSION_USER = "shield-user-42"
TOKENS = {"FakeLLM:Draft": 15, "FakeLLM:Final": 40}


class FakeLLMParam(ComponentParamBase):
    def check(self):
        return True


class FakeLLM(ComponentBase):
    """Déclare son usage comme LLMBundle._report_usage, dont une partie via thread_pool_exec (outil)."""

    component_name = "FakeLLM"

    def _invoke(self, **kwargs):
        pass

    async def _invoke_async(self, **kwargs):
        total = TOKENS[self._id]
        record_run_token_usage(total // 3, total - total // 3 - 1, total - 1)
        await thread_pool_exec(record_run_token_usage, 0, 1, 1)  # appel d'outil dans un thread
        self.set_output("content", f"{self._id} ok")

    def thoughts(self) -> str:
        return ""


def _cpn(name, downstream, upstream, params=None):
    return {"obj": {"component_name": name, "params": params or {}}, "downstream": downstream, "upstream": upstream}


FIELD = {"name": "retour", "optional": False, "options": [], "type": "paragraph"}
DSL = json.dumps({
    "components": {
        "begin": _cpn("Begin", ["FakeLLM:Draft"], [], {"mode": "conversational", "prologue": "", "inputs": {}}),
        "FakeLLM:Draft": _cpn("FakeLLM", ["UserFillUp:Valid"], ["begin"]),
        "UserFillUp:Valid": _cpn("UserFillUp", ["FakeLLM:Final"], ["FakeLLM:Draft"],
                                 {"enable_tips": False, "inputs": {"retour": FIELD}, "outputs": {"retour": FIELD}}),
        "FakeLLM:Final": _cpn("FakeLLM", ["Message:Fin"], ["UserFillUp:Valid"]),
        "Message:Fin": _cpn("Message", [], ["FakeLLM:Final"], {"content": ["{FakeLLM:Final@content}"]}),
    },
    "globals": {"sys.conversation_turns": 0, "sys.files": [], "sys.query": "", "sys.user_id": "", "sys.history": []},
    "history": [], "path": [], "retrieval": [],
})


@pytest.fixture
def db(monkeypatch):
    """Session d'agent en mémoire : get_by_id / append_message / UsageLogService.log mockés."""
    registry = {"FakeLLM": FakeLLM, "FakeLLMParam": FakeLLMParam}
    for mod in (begin, fillup, message):
        registry.update({name: getattr(mod, name) for name in dir(mod)})
    monkeypatch.setattr(canvas_module, "component_class", lambda name: registry[name])
    monkeypatch.setattr(canvas_module, "has_canceled", lambda *_: False)

    state = {"conv": {"id": SESSION_ID, "dialog_id": AGENT_ID, "user_id": SESSION_USER, "message": [],
                      "reference": [], "source": "agent", "dsl": DSL},
             "appended": [], "usage_log": []}

    def get_by_id(_sid):
        return True, API4Conversation(**json.loads(json.dumps(state["conv"])))

    def append_message(_id, conv, tokens=0, duration=0.0):
        state["conv"] = conv
        state["appended"].append({"tokens": tokens, "duration": duration})

    monkeypatch.setattr(canvas_service.API4ConversationService, "get_by_id", staticmethod(get_by_id))
    monkeypatch.setattr(canvas_service.API4ConversationService, "append_message", staticmethod(append_message))
    monkeypatch.setattr(eurelis_agent_usage.UsageLogService, "log",
                        staticmethod(lambda **kw: state["usage_log"].append(kw)))
    return state


def _complete(**kwargs) -> list:
    async def collect():
        return [json.loads(f[len("data:"):]) async for f in
                canvas_service.completion("caller-tenant", AGENT_ID, session_id=SESSION_ID, query="", **kwargs)]
    return asyncio.run(collect())


def test_paused_run_counts_tokens_and_duration(db):
    frames = _complete(inputs={})
    assert frames[-1]["event"] == "user_inputs", [f["event"] for f in frames]
    assert db["appended"] == [{"tokens": TOKENS["FakeLLM:Draft"], "duration": pytest.approx(db["appended"][0]["duration"])}]
    assert db["appended"][0]["duration"] > 0


def test_one_usage_log_line_per_run_including_pause(db):
    _complete(inputs={})
    frames = _complete(inputs={"retour": {"type": "paragraph", "value": "ok"}})
    assert frames[-1]["event"] == "workflow_finished"

    assert [a["tokens"] for a in db["appended"]] == [TOKENS["FakeLLM:Draft"], TOKENS["FakeLLM:Final"]]
    assert len(db["usage_log"]) == 2
    for line, tokens, app in zip(db["usage_log"], TOKENS.values(), db["appended"]):
        assert line == {"user_id": SESSION_USER, "resource_id": AGENT_ID, "object_id": SESSION_ID, "source": "agent",
                        "token_type": "llm", "tokens": tokens, "duration": app["duration"]}
    # Sémantique de workflow_finished.usage inchangée : total de la 2e exécution seulement.
    assert frames[-1]["data"]["usage"]["total_tokens"] == TOKENS["FakeLLM:Final"]
    assert frames[-1]["data"]["usage"]["calls"] == 2


def test_usage_logged_when_run_fails(db, monkeypatch):
    async def boom(self, **kwargs):
        record_run_token_usage(0, 0, 7)
        raise RuntimeError("provider down")

    monkeypatch.setattr(FakeLLM, "_invoke_async", boom)
    _complete(inputs={})
    assert db["usage_log"] and db["usage_log"][0]["tokens"] == 7


def test_meter_without_tokens_still_logs_duration(monkeypatch):
    lines = []
    monkeypatch.setattr(eurelis_agent_usage.UsageLogService, "log", staticmethod(lambda **kw: lines.append(kw)))
    canvas = SimpleNamespace(_run_usage_payload=lambda: {"total_tokens": 0})
    meter = eurelis_agent_usage.AgentRunMeter(canvas)
    time.sleep(0.01)
    eurelis_agent_usage.log_agent_run(meter, user_id="u", agent_id="a", session_id="s")
    eurelis_agent_usage.log_agent_run(meter, user_id="u", agent_id="a", session_id="s")
    assert [line["tokens"] for line in lines] == [0, 0] and lines[0]["duration"] == lines[1]["duration"] > 0


def test_embedding_is_not_in_run_collector():
    """L'embedding de Retrieval est journalisé à part (eurelis_usage_log) : le collecteur ne compte que le chat."""
    bundle = LLMBundle.__new__(LLMBundle)
    bundle.langfuse = None
    bundle.used_tokens = 0
    bundle.model_config = {"llm_name": "nomic-embed-text", "llm_factory": "Ollama"}
    bundle.mdl = SimpleNamespace(encode_queries=lambda q: ([0.1], 7), last_usage={})
    sink = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
    token = token_usage_sink.set(sink)
    try:
        bundle.encode_queries("question")
        assert sink["total_tokens"] == 0 and bundle.used_tokens == 7
        bundle._report_usage(15)  # appel de chat
        assert sink["total_tokens"] == 15 and sink["calls"] == 1
    finally:
        token_usage_sink.reset(token)
