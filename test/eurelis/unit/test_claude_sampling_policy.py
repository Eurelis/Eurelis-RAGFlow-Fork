# Eurelis — non-régression : paramètres de sampling refusés par les Claude (Anthropic direct et Bedrock).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Un chat configuré avec temperature ET top_p sur `eu.anthropic.claude-sonnet-4-6` (Bedrock)
# échouait en `litellm.BadRequestError: BedrockException - temperature and top_p cannot both
# be specified for this model`. La politique upstream ne couvrait que le provider Anthropic
# direct pour opus-4-7/4-8 ; `_apply_claude_sampling_policy` la généralise à tout nom de
# modèle contenant "claude" sur Anthropic et Bedrock.

import pytest

from rag.llm import SupportedLiteLLMProvider
from rag.llm.chat_model import _apply_claude_sampling_policy, _apply_model_family_policies

pytestmark = pytest.mark.p1

DIALOG_GEN_CONF = {"temperature": 0.8, "top_p": 0.9, "presence_penalty": 0.1, "frequency_penalty": 0.1}


def _policies(model_name, provider, gen_conf):
    sanitized, _ = _apply_model_family_policies(model_name, backend="litellm", provider=provider, gen_conf=gen_conf)
    return sanitized


def test_bedrock_claude_sonnet_4_6_keeps_temperature_and_drops_top_p():
    gen_conf = _policies("eu.anthropic.claude-sonnet-4-6", SupportedLiteLLMProvider.Bedrock, DIALOG_GEN_CONF)

    assert gen_conf["temperature"] == 0.8
    assert "top_p" not in gen_conf
    assert gen_conf["presence_penalty"] == 0.1  # untouched


def test_bedrock_claude_top_p_alone_is_preserved():
    gen_conf = _policies("eu.anthropic.claude-sonnet-4-6", SupportedLiteLLMProvider.Bedrock, {"top_p": 0.9})

    assert gen_conf == {"top_p": 0.9}


@pytest.mark.parametrize(
    "model_name",
    [
        "eu.anthropic.claude-opus-4-7-v1",
        "eu.anthropic.claude-opus-4-8-v1:0",
        "eu.anthropic.claude-opus-5",
        "eu.anthropic.claude-sonnet-5",
        "anthropic.claude-fable-5-1",
    ],
)
def test_bedrock_claude_without_sampling_drops_everything(model_name):
    gen_conf = _policies(model_name, SupportedLiteLLMProvider.Bedrock, {**DIALOG_GEN_CONF, "top_k": 40})

    assert not {"temperature", "top_p", "top_k"} & set(gen_conf)
    assert gen_conf["presence_penalty"] == 0.1


def test_claude_sonnet_4_5_is_not_confused_with_sonnet_5():
    gen_conf = _policies("eu.anthropic.claude-sonnet-4-5", SupportedLiteLLMProvider.Bedrock, DIALOG_GEN_CONF)

    assert gen_conf["temperature"] == 0.8
    assert "top_p" not in gen_conf


def test_anthropic_direct_upstream_rule_still_holds():
    gen_conf = _policies("claude-opus-4-8", SupportedLiteLLMProvider.Anthropic, DIALOG_GEN_CONF)

    assert not {"temperature", "top_p", "top_k"} & set(gen_conf)


def test_bedrock_non_claude_model_is_untouched():
    gen_conf = _policies("mistral.mistral-large-2402-v1:0", SupportedLiteLLMProvider.Bedrock, DIALOG_GEN_CONF)

    assert gen_conf == DIALOG_GEN_CONF


def test_helper_drops_top_p_across_all_targets_when_temperature_is_anywhere():
    gen_conf, kwargs = {"top_p": 0.9}, {"temperature": 0.2}

    _apply_claude_sampling_policy("eu.anthropic.claude-sonnet-4-6", gen_conf, kwargs)

    assert gen_conf == {}
    assert kwargs == {"temperature": 0.2}
