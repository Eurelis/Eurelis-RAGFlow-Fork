# Eurelis — non-régression AILAB-46 : dernier tour d'une boucle d'outils après dépassement de max_rounds.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Jusqu'à v0.26.3-eurelis.14, le chemin NON-streaming (`async_chat_with_tools`) faisait son dernier
# appel par `async_chat` / `_async_chat`, sans `tools=`. L'historique contenant des blocs
# tool_use/tool_result, Bedrock Converse le refusait (« Bedrock doesn't support tool calling without
# `tools=` param specified ») et l'agent rendait `**ERROR**: …` après 7 à 10 min (prod Diligentia,
# agent CRM, CodeExec, max_rounds 6). Le dernier appel déclare désormais les outils, n'exécute
# jamais ses tool_calls et renvoie un message explicite s'il n'a pas de texte.
#
# LiteLLM et le client OpenAI sont mockés : le faux fournisseur reproduit la règle de Bedrock
# (historique d'outils sans `tools=` → refus). Aucun appel réseau.

import asyncio
import json
from types import SimpleNamespace

import pytest

import rag.llm.chat_model as chat_model
from rag.llm import SupportedLiteLLMProvider
from rag.llm.chat_model import Base, LiteLLMBase
from rag.llm.eurelis_tool_rounds import max_rounds_empty_answer

MAX_ROUNDS = 1
USAGE = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}
BEDROCK_KEY = json.dumps({"auth_mode": "access_key_secret", "bedrock_region": "eu-west-3", "bedrock_ak": "AK", "bedrock_sk": "SK"})
TOOLS = [{"type": "function", "function": {"name": "code_exec", "description": "Run code", "parameters": {"type": "object", "properties": {}}}}]
FINAL_TEXT = "Synthèse : 3 opportunités ouvertes."


class _ToolSession:
    def __init__(self):
        self.calls = 0

    async def tool_call_async(self, name, args):
        self.calls += 1
        return {"ok": True, "n": self.calls}


def _tool_call(i):
    return SimpleNamespace(index=0, id=f"call_{i}", type="function", function=SimpleNamespace(name="code_exec", arguments='{"code": "print(1)"}'))


def _usage():
    return SimpleNamespace(**USAGE)


def _message_response(i, text_on_final, is_final):
    if is_final and text_on_final:
        message = SimpleNamespace(content=FINAL_TEXT, tool_calls=None)
        finish = "stop"
    else:
        message = SimpleNamespace(content="", tool_calls=[_tool_call(i)])
        finish = "tool_calls"
    return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=finish)], usage=_usage())


def _has_tool_history(messages):
    return any(m.get("role") == "tool" or m.get("tool_calls") for m in messages)


class _FakeProvider:
    """Fournisseur factice : appel n°(MAX_ROUNDS+2) = dernier tour ; règle Bedrock sur `tools=`."""

    def __init__(self, text_on_final=False, stream=False):
        self.text_on_final, self.stream = text_on_final, stream
        self.calls = []

    def _check(self, kwargs):
        self.calls.append(kwargs)
        if _has_tool_history(kwargs["messages"]) and not kwargs.get("tools"):
            raise Exception("litellm.UnsupportedParamsError: Bedrock doesn't support tool calling without `tools=` param specified.")
        return len(self.calls), len(self.calls) == MAX_ROUNDS + 2

    async def acompletion(self, **kwargs):
        i, is_final = self._check(kwargs)
        if self.stream:
            return self._chunks(i, is_final)
        return _message_response(i, self.text_on_final, is_final)

    async def _chunks(self, i, is_final):
        if is_final and self.text_on_final:
            for piece in ("Synthèse : ", "3 opportunités ouvertes."):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=piece, tool_calls=None), finish_reason=None)], usage=None)
        else:
            delta = SimpleNamespace(content=None, tool_calls=[_tool_call(i)])
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason="tool_calls")], usage=None)
        yield SimpleNamespace(choices=[], usage=_usage())


class _ConcreteLiteLLM(LiteLLMBase):
    pass


class _ConcreteOpenAI(Base):
    pass


def _make_litellm():
    mdl = _ConcreteLiteLLM.__new__(_ConcreteLiteLLM)
    mdl.model_name = "bedrock/eu.anthropic.claude-opus-4-8"
    mdl.provider = SupportedLiteLLMProvider.Bedrock
    mdl.prefix = "bedrock/"
    mdl.api_key = BEDROCK_KEY
    mdl.base_url = ""
    mdl.timeout = 60
    mdl.max_retries = 0
    mdl.base_delay = 0
    mdl.max_rounds = MAX_ROUNDS
    mdl.last_usage = {}
    mdl.bind_tools(_ToolSession(), TOOLS)
    return mdl


def _make_openai(provider):
    mdl = _ConcreteOpenAI.__new__(_ConcreteOpenAI)
    mdl.model_name = "gpt-4.1"
    mdl.max_retries = 0
    mdl.base_delay = 0
    mdl.max_rounds = MAX_ROUNDS
    mdl.last_usage = {}
    mdl.async_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=provider.acompletion)))
    mdl.bind_tools(_ToolSession(), TOOLS)
    return mdl


@pytest.fixture(params=["litellm", "openai"])
def backend(request, monkeypatch):
    """(fabrique de modèle, installation du faux fournisseur) pour LiteLLMBase et Base (client OpenAI)."""
    if request.param == "litellm":
        def install(provider):
            monkeypatch.setattr(chat_model.litellm, "acompletion", provider.acompletion)
            return _make_litellm()
    else:
        def install(provider):
            return _make_openai(provider)
    return install


def _chat_with_tools(mdl):
    return asyncio.run(mdl.async_chat_with_tools("Tu es un agent CRM.", [{"role": "user", "content": "Chiffre le pipeline."}], {"temperature": 0.1}))


def test_final_round_declares_tools_and_never_runs_them(backend):
    """Outil appelé à chaque tour : le dernier appel déclare `tools`, n'exécute rien et ne renvoie pas d'erreur."""
    provider = _FakeProvider(text_on_final=False)
    mdl = backend(provider)

    ans, tokens = _chat_with_tools(mdl)

    assert len(provider.calls) == MAX_ROUNDS + 2
    assert all(call.get("tools") for call in provider.calls), "un appel a été envoyé sans `tools=`"
    assert provider.calls[-1]["tool_choice"] == "auto"
    assert mdl.toolcall_session.calls == MAX_ROUNDS + 1, "un tool_call du dernier tour a été exécuté"
    assert "**ERROR**" not in ans and "UnsupportedParams" not in ans, ans
    assert ans.endswith(max_rounds_empty_answer(MAX_ROUNDS))
    final_prompt = provider.calls[-1]["messages"][-1]
    assert final_prompt["role"] == "user" and "Do not call any tool anymore" in final_prompt["content"]
    assert tokens == USAGE["total_tokens"] * (MAX_ROUNDS + 2)


def test_final_round_text_is_returned_and_usage_aggregated(backend):
    """Le dernier appel renvoie du texte : il est rendu, et l'usage couvre tous les tours."""
    provider = _FakeProvider(text_on_final=True)
    mdl = backend(provider)

    ans, tokens = _chat_with_tools(mdl)

    assert ans.endswith(FINAL_TEXT), ans
    assert "**ERROR**" not in ans
    rounds = MAX_ROUNDS + 2
    assert tokens == USAGE["total_tokens"] * rounds
    assert mdl.last_usage == {k: v * rounds for k, v in USAGE.items()}


def test_streaming_fallback_unchanged(monkeypatch):
    """Chemin streaming (référence) : dernier appel avec `tools`, texte relayé, usage agrégé."""
    provider = _FakeProvider(text_on_final=True, stream=True)
    monkeypatch.setattr(chat_model.litellm, "acompletion", provider.acompletion)
    mdl = _make_litellm()

    async def collect():
        history = [{"role": "user", "content": "Chiffre le pipeline."}]
        return [chunk async for chunk in mdl.async_chat_streamly_with_tools("Tu es un agent CRM.", history, {"temperature": 0.1})]

    out = asyncio.run(collect())

    rounds = MAX_ROUNDS + 2
    assert len(provider.calls) == rounds and all(call.get("tools") for call in provider.calls)
    assert mdl.toolcall_session.calls == MAX_ROUNDS + 1
    text = "".join(c for c in out if isinstance(c, str) and not c.startswith("<tool_call>"))
    assert text == FINAL_TEXT
    assert out[-1] == USAGE["total_tokens"] * rounds
