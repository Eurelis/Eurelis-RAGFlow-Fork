# Eurelis — non-régression : paramètres de sampling refusés par les Claude (Anthropic direct et Bedrock).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Un chat configuré avec temperature ET top_p sur `eu.anthropic.claude-sonnet-4-6` (Bedrock)
# échouait en `litellm.BadRequestError: BedrockException - temperature and top_p cannot both
# be specified for this model`. La politique upstream ne couvrait que le provider Anthropic
# direct pour opus-4-7/4-8 ; `_apply_claude_sampling_policy` la généralise à tout nom de
# modèle contenant "claude" sur Anthropic et Bedrock.

import logging

import pytest

from rag.llm import SupportedLiteLLMProvider
from rag.llm.chat_model import _apply_claude_sampling_policy, _apply_model_family_policies, _claude_version

pytestmark = pytest.mark.p1

CLAUDE_GEN_CONF = DIALOG_GEN_CONF = {"temperature": 0.8, "top_p": 0.9, "presence_penalty": 0.1, "frequency_penalty": 0.1}


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


def test_helper_logs_applied_policy(caplog):
    with caplog.at_level(logging.DEBUG):
        _apply_claude_sampling_policy("eu.anthropic.claude-sonnet-4-6", {"temperature": 0.8, "top_p": 0.9})
        _apply_claude_sampling_policy("eu.anthropic.claude-opus-4-8-v1:0", {"temperature": 0.8})
        _apply_claude_sampling_policy("eu.anthropic.claude-sonnet-4-6", {"top_p": 0.9})

    records = [record for record in caplog.records if "Claude sampling policy" in record.getMessage()]
    assert [record.levelno for record in records] == [logging.WARNING, logging.WARNING]
    messages = [record.getMessage() for record in records]
    assert "dropped top_p for model eu.anthropic.claude-sonnet-4-6" in messages[0]
    assert "dropped temperature/top_p/top_k for model eu.anthropic.claude-opus-4-8-v1:0" in messages[1]


@pytest.mark.parametrize(
    ("model_name", "expected"),
    [
        ("claude-sonnet-4-5", (4, 5)),
        ("claude-sonnet-4-5-20250929", (4, 5)),
        ("claude-opus-4-1-20250805", (4, 1)),
        ("claude-sonnet-4-20250514", (4, 0)),
        ("us.anthropic.claude-sonnet-4-20250514-v1:0", (4, 0)),
        ("eu.anthropic.claude-sonnet-4-6", (4, 6)),
        ("claude-haiku-4-5-20251001", (4, 5)),
        ("claude-fable-5-1", (5, 1)),
        ("claude-3-5-sonnet-20241022", (3, 5)),
        ("anthropic.claude-3-7-sonnet-20250219-v1:0", (3, 7)),
        ("claude-3-haiku-20240307", (3, 0)),
        ("claude-instant-1.2", None),
    ],
)
def test_claude_version_parsing(model_name, expected):
    assert _claude_version(model_name) == expected


@pytest.mark.parametrize("provider", [SupportedLiteLLMProvider.Anthropic, SupportedLiteLLMProvider.Bedrock])
@pytest.mark.parametrize(
    "model_name",
    ["claude-3-7-sonnet-20250219", "claude-3-5-sonnet-20241022", "claude-sonnet-4-20250514", "anthropic.claude-opus-4-20250514-v1:0"],
)
def test_claude_before_4_1_keeps_temperature_and_top_p(model_name, provider):
    gen_conf = _policies(model_name, provider, CLAUDE_GEN_CONF)

    assert gen_conf == CLAUDE_GEN_CONF


@pytest.mark.parametrize("provider", [SupportedLiteLLMProvider.Anthropic, SupportedLiteLLMProvider.Bedrock])
@pytest.mark.parametrize("model_name", ["claude-opus-4-1-20250805", "claude-sonnet-4-5", "claude-haiku-4-5-20251001", "claude-opus-4-6"])
def test_claude_4_1_and_later_drop_top_p_on_both_providers(model_name, provider):
    gen_conf = _policies(model_name, provider, CLAUDE_GEN_CONF)

    assert gen_conf["temperature"] == 0.8
    assert "top_p" not in gen_conf


def test_claude_with_unparsable_version_is_treated_as_recent():
    gen_conf = _policies("claude-latest", SupportedLiteLLMProvider.Anthropic, CLAUDE_GEN_CONF)

    assert "top_p" not in gen_conf
