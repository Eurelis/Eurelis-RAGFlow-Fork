# Eurelis — non-régression AILAB-22 : injection d'un max_tokens par modèle sur la branche Bedrock.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Sans max_tokens explicite, l'API Bedrock Converse applique un défaut service (~4 096 tokens
# pour Claude) et tronque les réponses longues (finish_reason "length" → suffixe
# "The answer is truncated…"). Le correctif injecte, dans `_construct_completion_args` et
# uniquement pour Bedrock, le vrai max output du modèle depuis le registre litellm — avec
# repli sur l'env var LLM_BEDROCK_DEFAULT_MAX_OUTPUT_TOKENS (défaut 4096) pour les modèles
# inconnus du registre. Attention : LITELLM_LOCAL_MODEL_COST_MAP=True (api/ragflow_server.py)
# fait que le registre effectif est celui EMBARQUÉ dans le litellm pinné (>= 1.92 requis pour
# opus-4-8 / sonnet-5). Le garde-fou `_clean_conf` qui neutralise les `max_tokens` legacy
# reste intact ; le toggle UI des agents passe désormais par `max_completion_tokens`.

import json

import pytest

from agent.component.llm import LLMParam
from rag.llm import SupportedLiteLLMProvider
from rag.llm.chat_model import LiteLLMBase, _bedrock_default_max_output_tokens

# Vraies limites du registre litellm (identiques dans la carte embarquée du pin et la distante).
KNOWN_MODEL = "bedrock/mistral.mistral-large-2402-v1:0"
KNOWN_MODEL_MAX_OUTPUT = 8191
UNKNOWN_MODEL = "bedrock/eu.acme.modele-exotique-v1:0"

BEDROCK_KEY = json.dumps(
    {
        "auth_mode": "access_key_secret",
        "bedrock_region": "eu-west-3",
        "bedrock_ak": "AKIA_TEST",
        "bedrock_sk": "SECRET_TEST",
    }
)

HISTORY = [{"role": "user", "content": "Bonjour"}]


class _ConcreteLiteLLM(LiteLLMBase):
    """Sous-classe concrète pour instancier sans le constructeur réel (pas de réseau)."""


def _make_litellm(model_name: str, provider, api_key: str = BEDROCK_KEY, base_url: str = ""):
    inst = _ConcreteLiteLLM.__new__(_ConcreteLiteLLM)
    inst.model_name = model_name
    inst.provider = provider
    inst.prefix = "bedrock/" if provider == SupportedLiteLLMProvider.Bedrock else ""
    inst.api_key = api_key
    inst.base_url = base_url
    inst.max_retries = 3
    inst.is_tools = False
    inst.tools = []
    return inst


def _completion_args(mdl, **kwargs) -> dict:
    completion_args, _ = mdl._construct_completion_args(history=list(HISTORY), stream=False, tools=False, **kwargs)
    return completion_args


# --------------------------------------------------------------------------- #
# 1. Bedrock sans max_tokens → injection du max output du registre litellm.
# --------------------------------------------------------------------------- #
def test_bedrock_injects_registry_max_output_for_known_model():
    mdl = _make_litellm(KNOWN_MODEL, SupportedLiteLLMProvider.Bedrock)
    args = _completion_args(mdl)
    assert args["max_tokens"] == KNOWN_MODEL_MAX_OUTPUT


@pytest.mark.parametrize(
    "model_name,expected",
    [
        ("bedrock/eu.amazon.nova-pro-v1:0", 10000),
        # Modèles prod AILAB-22 — présents dans le registre embarqué depuis litellm 1.88/1.92 :
        # ce test échoue si le pin litellm redescend sous 1.92 (la troncature reviendrait).
        ("bedrock/eu.anthropic.claude-opus-4-8", 128000),
        ("bedrock/eu.anthropic.claude-sonnet-5", 128000),
    ],
)
def test_registry_lookup_matches_known_bedrock_models(model_name, expected):
    assert _bedrock_default_max_output_tokens(model_name) == expected


# --------------------------------------------------------------------------- #
# 2. Modèle inconnu du registre → repli sur l'env var (4096 sans env var).
# --------------------------------------------------------------------------- #
def test_bedrock_unknown_model_falls_back_to_env_var(monkeypatch):
    monkeypatch.setenv("LLM_BEDROCK_DEFAULT_MAX_OUTPUT_TOKENS", "9000")
    mdl = _make_litellm(UNKNOWN_MODEL, SupportedLiteLLMProvider.Bedrock)
    args = _completion_args(mdl)
    assert args["max_tokens"] == 9000


def test_bedrock_unknown_model_falls_back_to_4096_without_env_var(monkeypatch):
    monkeypatch.delenv("LLM_BEDROCK_DEFAULT_MAX_OUTPUT_TOKENS", raising=False)
    mdl = _make_litellm(UNKNOWN_MODEL, SupportedLiteLLMProvider.Bedrock)
    args = _completion_args(mdl)
    assert args["max_tokens"] == 4096


# --------------------------------------------------------------------------- #
# 3. max_completion_tokens explicite → transmis tel quel, pas d'injection.
# --------------------------------------------------------------------------- #
def test_bedrock_explicit_max_completion_tokens_disables_injection():
    mdl = _make_litellm(KNOWN_MODEL, SupportedLiteLLMProvider.Bedrock)
    args = _completion_args(mdl, max_completion_tokens=1234)
    assert args["max_completion_tokens"] == 1234
    assert "max_tokens" not in args


def test_bedrock_max_completion_tokens_survives_clean_conf():
    mdl = _make_litellm(KNOWN_MODEL, SupportedLiteLLMProvider.Bedrock)
    cleaned = mdl._clean_conf({"max_completion_tokens": 1234, "max_tokens": 256, "temperature": 0.2})
    assert cleaned["max_completion_tokens"] == 1234
    # Le garde-fou historique reste intact : max_tokens legacy neutralisé.
    assert "max_tokens" not in cleaned


# --------------------------------------------------------------------------- #
# 4. Provider non-Bedrock → aucune injection.
# --------------------------------------------------------------------------- #
def test_non_bedrock_provider_gets_no_injection():
    mdl = _make_litellm(
        "anthropic/claude-opus-4-8",
        SupportedLiteLLMProvider.Anthropic,
        api_key="sk-test",
        base_url="https://api.anthropic.com",
    )
    args = _completion_args(mdl)
    assert "max_tokens" not in args
    assert "max_completion_tokens" not in args


# --------------------------------------------------------------------------- #
# 5. Toggle "Max tokens" des composants agent LLM.
# --------------------------------------------------------------------------- #
def test_agent_llm_max_tokens_toggle_enabled_emits_max_completion_tokens():
    param = LLMParam()
    param.max_tokens = 2048
    param.maxTokensEnabled = True
    conf = param.gen_conf()
    assert conf["max_completion_tokens"] == 2048
    assert "max_tokens" not in conf


def test_agent_llm_max_tokens_toggle_disabled_emits_nothing():
    param = LLMParam()
    param.max_tokens = 2048
    param.maxTokensEnabled = False
    assert "max_completion_tokens" not in param.gen_conf()
    assert "max_tokens" not in param.gen_conf()


def test_agent_llm_legacy_dsl_without_toggle_emits_nothing():
    # Les DSL legacy portent max_tokens (256/4096) sans attribut maxTokensEnabled :
    # ils ne doivent réactiver aucun cap.
    param = LLMParam()
    param.max_tokens = 256
    conf = param.gen_conf()
    assert "max_completion_tokens" not in conf
    assert "max_tokens" not in conf
