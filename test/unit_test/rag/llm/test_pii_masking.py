#
#  Copyright 2024 The Eurelis Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
"""
Unit tests for rag/llm/pii_masking.py
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_engine(entities=None, score_thresholds=None):
    """Build a PiiMaskingEngine with mock Presidio components."""
    from rag.llm.pii_masking import PiiMaskingEngine, PiiAuditLogger

    if entities is None:
        entities = {
            "EMAIL_ADDRESS": "MASK",
            "PERSON": "MASK",
            "PHONE_NUMBER": "MASK",
            "CREDIT_CARD": "MASK",
        }
    if score_thresholds is None:
        score_thresholds = {"PERSON": 0.85, "CREDIT_CARD": 0.6}

    from presidio_analyzer import AnalyzerEngine
    from presidio_anonymizer import AnonymizerEngine

    analyzer = AnalyzerEngine()
    anonymizer = AnonymizerEngine()
    audit_logger = PiiAuditLogger()

    engine = PiiMaskingEngine(
        analyzer=analyzer,
        anonymizer=anonymizer,
        entities_config=entities,
        score_thresholds=score_thresholds,
        audit_logger=audit_logger,
    )
    return engine


# ---------------------------------------------------------------------------
# PiiMaskingEngine — masking
# ---------------------------------------------------------------------------

class TestMaskText:
    def test_mask_email(self):
        import re
        engine = _make_engine()
        result = engine._mask_text("My email is john@example.com", language="en", mask=True)
        assert "john@example.com" not in result.masked_text
        assert re.search(r"<EMAIL_ADDRESS_\d+>", result.masked_text), (
            f"Expected numbered placeholder, got: {result.masked_text}"
        )
        assert any(e.entity_type == "EMAIL_ADDRESS" for e in result.entities)

    def test_mask_person(self):
        engine = _make_engine()
        result = engine._mask_text("My name is John Smith", language="en", mask=True)
        assert any(e.entity_type == "PERSON" for e in result.entities)

    def test_no_pii_returns_original(self):
        engine = _make_engine()
        text = "The sky is blue and water is wet."
        result = engine._mask_text(text, language="en", mask=True)
        assert result.masked_text == text
        assert result.entities == []

    def test_mask_false_returns_original_text(self):
        """mask=False should analyze but not modify the text."""
        engine = _make_engine()
        text = "Call me at +1-555-123-4567"
        result = engine._mask_text(text, language="en", mask=False)
        assert result.masked_text == text   # unchanged
        # entities may or may not be found depending on Presidio config

    def test_block_action_raises(self):
        from rag.llm.pii_masking import PiiBlockedException
        engine = _make_engine(entities={"CREDIT_CARD": "BLOCK"})
        with pytest.raises(PiiBlockedException):
            engine._mask_text("My card is 4111111111111111", language="en", mask=True)


class TestMaskMessages:
    def test_masks_user_role_only(self):
        engine = _make_engine()
        messages = [
            {"role": "system", "content": "You are helpful. Contact admin@corp.com"},
            {"role": "user", "content": "My email is user@example.com"},
            {"role": "assistant", "content": "I see your email is user@example.com"},
        ]
        masked, _, entities_by_role = engine.mask_messages(messages, language="en", roles_to_mask=["user"])

        # system and assistant must be unchanged
        assert masked[0]["content"] == messages[0]["content"]
        assert masked[2]["content"] == messages[2]["content"]
        # user must be masked
        assert "user@example.com" not in masked[1]["content"]

    def test_no_pii_messages_unchanged(self):
        engine = _make_engine()
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        masked, _, entities_by_role = engine.mask_messages(messages, language="en")
        assert masked[0]["content"] == messages[0]["content"]
        assert entities_by_role == {}

    def test_multiple_messages_aggregated_entities(self):
        engine = _make_engine()
        messages = [
            {"role": "user", "content": "My email is a@b.com"},
            {"role": "user", "content": "My other email is c@d.com"},
        ]
        _, _, entities_by_role = engine.mask_messages(messages, language="en")
        all_entities = [e for role_entities in entities_by_role.values() for e in role_entities]
        email_entities = [e for e in all_entities if e.entity_type == "EMAIL_ADDRESS"]
        assert len(email_entities) >= 2

    def test_non_string_content_skipped(self):
        engine = _make_engine()
        messages = [{"role": "user", "content": None}]
        masked, _, entities_by_role = engine.mask_messages(messages, language="en")
        assert masked[0] == messages[0]


class TestCrossMessageConsistency:
    """The same PII value must receive the same numbered placeholder across all messages."""

    def test_same_value_same_placeholder_in_two_messages(self):
        """jean@corp.com in user + system → same placeholder in both."""
        engine = _make_engine()
        messages = [
            {"role": "system", "content": "Context: jean@corp.com is the contact."},
            {"role": "user", "content": "Please contact jean@corp.com for details."},
        ]
        masked, mapping, _ = engine.mask_messages(
            messages, language="en", roles_to_mask=["system", "user"]
        )
        # Exactly one placeholder for this email
        placeholders = [ph for ph, val in mapping.items() if val == "jean@corp.com"]
        assert len(placeholders) == 1, "Same value must map to exactly one placeholder"
        ph = placeholders[0]
        assert ph in masked[0]["content"], "Placeholder must appear in system message"
        assert ph in masked[1]["content"], "Placeholder must appear in user message"

    def test_two_distinct_emails_get_different_placeholders(self):
        """Two different emails → two distinct <EMAIL_ADDRESS_N> placeholders."""
        engine = _make_engine()
        messages = [{"role": "user", "content": "First: a@example.com, second: b@example.com"}]
        masked, mapping, _ = engine.mask_messages(messages, language="en")
        # Both emails must be masked and have distinct placeholders in the mapping
        assert "a@example.com" not in masked[0]["content"]
        assert "b@example.com" not in masked[0]["content"]
        email_values = {v for k, v in mapping.items() if k.startswith("<EMAIL_ADDRESS_")}
        assert "a@example.com" in email_values
        assert "b@example.com" in email_values

    def test_placeholder_format_is_numbered(self):
        """Standalone _mask_text() must also produce numbered placeholders."""
        import re
        engine = _make_engine()
        result = engine._mask_text("Email: test@example.com", language="en", mask=True)
        assert re.search(r"<EMAIL_ADDRESS_\d+>", result.masked_text), (
            f"Expected numbered placeholder, got: {result.masked_text}"
        )

    def test_entity_placeholder_matches_text_placeholder(self):
        """DetectedEntity.placeholder must reflect the actual <TYPE_N> used in masked_text."""
        import re
        engine = _make_engine()
        result = engine._mask_text("Email: user@example.com", language="en", mask=True)
        email_entities = [e for e in result.entities if e.entity_type == "EMAIL_ADDRESS"]
        assert email_entities, "No EMAIL_ADDRESS entity detected"
        entity_ph = email_entities[0].placeholder
        # placeholder must be numbered
        assert re.match(r"<EMAIL_ADDRESS_\d+>$", entity_ph), (
            f"Entity placeholder not numbered: {entity_ph}"
        )
        # placeholder must appear in the masked text
        assert entity_ph in result.masked_text, (
            f"Entity placeholder {entity_ph!r} absent from masked text: {result.masked_text}"
        )

    def test_repeated_value_same_message_gets_same_placeholder(self):
        """The same value repeated within a single message → same placeholder both times."""
        import re
        engine = _make_engine()
        result = engine._mask_text(
            "First: user@test.com and again: user@test.com", language="en", mask=True
        )
        assert "user@test.com" not in result.masked_text
        # Find all email placeholders in the result
        matches = re.findall(r"<EMAIL_ADDRESS_\d+>", result.masked_text)
        # Should be exactly two placeholders, and they must be the same
        assert len(matches) == 2, f"Expected 2 placeholders, got: {matches}"
        assert matches[0] == matches[1], f"Same value must use same placeholder: {matches}"


# ---------------------------------------------------------------------------
# PiiMaskingEngine — singleton lifecycle
# ---------------------------------------------------------------------------

class TestEngineLifecycle:
    def setup_method(self):
        """Reset singleton before each test."""
        from rag.llm.pii_masking import PiiMaskingEngine
        PiiMaskingEngine._instance = None

    def test_get_before_init_raises(self):
        from rag.llm.pii_masking import PiiMaskingEngine
        with pytest.raises(RuntimeError, match="not initialized"):
            PiiMaskingEngine.get()

    def test_is_available_before_init(self):
        from rag.llm.pii_masking import PiiMaskingEngine
        assert PiiMaskingEngine.is_available() is False

    @patch.dict(os.environ, {"PII_MASKING_ENABLED": "false", "PII_AUDIT_LOG_ENABLED": "false"})
    def test_initialize_noop_when_disabled(self):
        from rag.llm.pii_masking import PiiMaskingEngine
        PiiMaskingEngine.initialize()
        assert PiiMaskingEngine.is_available() is False

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_NER": "false",
        "PII_MASKING_ENTITIES": "EMAIL_ADDRESS:MASK,PHONE_NUMBER:MASK",
        "PII_MASKING_PROVIDERS": ".*@OpenAI",
    })
    def test_initialize_without_ner(self):
        from rag.llm.pii_masking import PiiMaskingEngine
        PiiMaskingEngine.initialize()
        assert PiiMaskingEngine.is_available() is True

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_NER": "true",
        "PII_MASKING_LANGUAGES": "fr,en",
        "PII_MASKING_NER_MODEL_FR": "fr_core_news_sm",
        "PII_MASKING_NER_MODEL_EN": "en_core_web_sm",
        "PII_MASKING_ENTITIES": "PERSON:MASK,EMAIL_ADDRESS:MASK",
    })
    def test_initialize_multilang_fr_en(self):
        """Regression: a multi-language registry (fr,en) must stay consistent with
        the AnalyzerEngine's supported_languages, otherwise Presidio raises
        'Misconfigured engine, supported languages have to be consistent'."""
        from rag.llm.pii_masking import PiiMaskingEngine
        PiiMaskingEngine.initialize()
        assert PiiMaskingEngine.is_available() is True

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_NER": "false",
        "PII_MASKING_STARTUP_FAIL": "false",
    })
    def test_initialize_fail_startup_false_does_not_raise(self):
        from rag.llm.pii_masking import PiiMaskingEngine
        with patch.object(PiiMaskingEngine, "_do_initialize", side_effect=RuntimeError("boom")):
            PiiMaskingEngine.initialize()   # should NOT raise
        assert PiiMaskingEngine.is_available() is False

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_NER": "false",
        "PII_MASKING_STARTUP_FAIL": "true",
    })
    def test_initialize_fail_startup_true_raises(self):
        from rag.llm.pii_masking import PiiMaskingEngine
        with patch.object(PiiMaskingEngine, "_do_initialize", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                PiiMaskingEngine.initialize()

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_NER": "false",
    })
    def test_initialize_idempotent(self):
        from rag.llm.pii_masking import PiiMaskingEngine
        PiiMaskingEngine.initialize()
        instance1 = PiiMaskingEngine._instance
        PiiMaskingEngine.initialize()
        instance2 = PiiMaskingEngine._instance
        assert instance1 is instance2


# ---------------------------------------------------------------------------
# Score thresholds
# ---------------------------------------------------------------------------

class TestScoreThresholds:
    def test_global_threshold_filters_low_confidence(self):
        from rag.llm.pii_masking import PiiMaskingEngine, DetectedEntity
        engine = _make_engine()
        # Patch analyzer to return a low-confidence result
        mock_result = MagicMock()
        mock_result.entity_type = "EMAIL_ADDRESS"
        mock_result.start = 0
        mock_result.end = 5
        mock_result.score = 0.3   # Below default threshold of 0.7

        with patch.object(engine.analyzer, "analyze", return_value=[mock_result]):
            result = engine._mask_text("hello", language="en", mask=True)

        assert result.entities == []   # filtered out
        assert result.masked_text == "hello"

    def test_per_entity_override_applies(self):
        """PERSON threshold is 0.85 by default; score 0.80 should be filtered."""
        engine = _make_engine(score_thresholds={"PERSON": 0.85})
        mock_result = MagicMock()
        mock_result.entity_type = "PERSON"
        mock_result.start = 0
        mock_result.end = 10
        mock_result.score = 0.80   # below 0.85 override

        with patch.object(engine.analyzer, "analyze", return_value=[mock_result]):
            result = engine._mask_text("John Smith", language="en", mask=True)

        assert result.entities == []


# ---------------------------------------------------------------------------
# Provider matching / ::pii suffix
# ---------------------------------------------------------------------------

class TestProviderMatching:
    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_PROVIDERS": "",
        "PII_MASKING_NER": "false",
    })
    def test_empty_providers_no_masking(self):
        from rag.llm.pii_masking import apply_pii_masking, PiiMaskingEngine
        PiiMaskingEngine._instance = _make_engine()
        messages = [{"role": "user", "content": "Email: a@b.com"}]
        masked, _, _mapping = apply_pii_masking(messages, "openai/gpt-4o", "openai/", "OpenAI")
        assert masked[0]["content"] == "Email: a@b.com"

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_PROVIDERS": ".*@OpenAI",
        "PII_MASKING_NER": "false",
        "PII_MASKING_ENTITIES": "EMAIL_ADDRESS:MASK",
    })
    def test_matching_provider_masks(self):
        from rag.llm.pii_masking import apply_pii_masking, PiiMaskingEngine
        PiiMaskingEngine._instance = _make_engine()
        messages = [{"role": "user", "content": "Email: user@example.com"}]
        masked, _, _mapping = apply_pii_masking(messages, "openai/gpt-4o", "openai/", "OpenAI")
        assert "user@example.com" not in masked[0]["content"]

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_PROVIDERS": ".*@OpenAI",
        "PII_MASKING_NER": "false",
    })
    def test_non_matching_provider_no_masking(self):
        from rag.llm.pii_masking import apply_pii_masking, PiiMaskingEngine
        PiiMaskingEngine._instance = _make_engine()
        messages = [{"role": "user", "content": "Email: user@example.com"}]
        masked, _, _mapping = apply_pii_masking(messages, "ollama_chat/llama3", "ollama_chat/", "Ollama")
        assert masked[0]["content"] == "Email: user@example.com"

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_PROVIDERS": ".*::pii@.*",
        "PII_MASKING_NER": "false",
        "PII_MASKING_ENTITIES": "EMAIL_ADDRESS:MASK",
    })
    def test_pii_suffix_stripped_from_model_name(self):
        """::pii suffix must be removed before the model name is sent to LiteLLM."""
        from rag.llm.pii_masking import apply_pii_masking, PiiMaskingEngine
        PiiMaskingEngine._instance = _make_engine()
        messages = [{"role": "user", "content": "Email: user@example.com"}]
        _, effective, _mapping = apply_pii_masking(
            messages, "openai/gpt-4o::pii", "openai/", "OpenAI"
        )
        assert effective == "openai/gpt-4o"    # suffix stripped

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "true",
        "PII_MASKING_PROVIDERS": ".*::pii@.*",
        "PII_MASKING_NER": "false",
    })
    def test_pii_suffix_match_uses_suffixed_name(self):
        """Regex matching must happen on the name WITH ::pii, not after stripping."""
        from rag.llm.pii_masking import apply_pii_masking, PiiMaskingEngine, _matches_providers_filter
        # gpt-4o::pii@OpenAI should match .*::pii@.*
        assert _matches_providers_filter("gpt-4o::pii@OpenAI", ".*::pii@.*") is True
        # gpt-4o@OpenAI should NOT match .*::pii@.*
        assert _matches_providers_filter("gpt-4o@OpenAI", ".*::pii@.*") is False

    @patch.dict(os.environ, {
        "PII_MASKING_ENABLED": "false",
        "PII_MASKING_PROVIDERS": ".*::pii@.*",
    })
    def test_pii_suffix_stripped_even_when_masking_disabled(self):
        """The ::pii suffix must always be stripped regardless of masking state."""
        from rag.llm.pii_masking import apply_pii_masking, PiiMaskingEngine
        PiiMaskingEngine._instance = None
        messages = [{"role": "user", "content": "Hello"}]
        _, effective, _mapping = apply_pii_masking(
            messages, "openai/gpt-4o::pii", "openai/", "OpenAI"
        )
        assert effective == "openai/gpt-4o"

    def test_invalid_regex_in_providers_filter_ignored(self):
        from rag.llm.pii_masking import _matches_providers_filter
        # Should not raise, just skip invalid patterns
        result = _matches_providers_filter("gpt-4o@OpenAI", "[invalid(regex,.*@OpenAI")
        # The invalid pattern is skipped; valid one matches
        assert result is True


# ---------------------------------------------------------------------------
# StreamingUnmasker
# ---------------------------------------------------------------------------

class TestStreamingUnmasker:
    def test_passthrough_no_placeholder(self):
        from rag.llm.pii_masking import StreamingUnmasker
        u = StreamingUnmasker({"<EMAIL_ADDRESS>": "a@b.com"})
        assert u.process_chunk("Hello world") == "Hello world"
        assert u.flush() == ""

    def test_complete_placeholder_in_one_chunk(self):
        from rag.llm.pii_masking import StreamingUnmasker
        u = StreamingUnmasker({"<EMAIL_ADDRESS>": "a@b.com"})
        out = u.process_chunk("Contact <EMAIL_ADDRESS> please")
        assert "a@b.com" in out
        assert "<EMAIL_ADDRESS>" not in out

    def test_fragmented_placeholder(self):
        from rag.llm.pii_masking import StreamingUnmasker
        u = StreamingUnmasker({"<EMAIL_ADDRESS>": "a@b.com"})
        out = ""
        out += u.process_chunk("Contact <EMAIL")
        out += u.process_chunk("_ADDR")
        out += u.process_chunk("ESS> please")
        assert "a@b.com" in out
        assert "<EMAIL_ADDRESS>" not in out

    def test_unknown_placeholder_passes_through(self):
        from rag.llm.pii_masking import StreamingUnmasker
        u = StreamingUnmasker({"<EMAIL_ADDRESS>": "a@b.com"})
        out = u.process_chunk("See <UNKNOWN_ENTITY> here")
        out += u.flush()
        assert "<UNKNOWN_ENTITY>" in out

    def test_false_positive_lt_without_gt(self):
        """A lone '<' that never closes should be flushed after MAX_PLACEHOLDER_LEN."""
        from rag.llm.pii_masking import StreamingUnmasker
        u = StreamingUnmasker({})
        # Feed a '<' followed by many chars without '>'
        long_str = "<" + "x" * (StreamingUnmasker.MAX_PLACEHOLDER_LEN + 5)
        out = u.process_chunk(long_str)
        out += u.flush()
        # Everything should eventually be flushed
        assert len(out) >= len(long_str) - StreamingUnmasker.MAX_PLACEHOLDER_LEN

    def test_flush_partial_placeholder(self):
        from rag.llm.pii_masking import StreamingUnmasker
        u = StreamingUnmasker({"<EMAIL_ADDRESS>": "a@b.com"})
        u.process_chunk("end <EMAIL")  # partial placeholder in buffer
        tail = u.flush()
        # Partial placeholder can't be resolved — flushed as-is
        assert "<EMAIL" in tail or "EMAIL" in tail


# ---------------------------------------------------------------------------
# PiiAuditLogger
# ---------------------------------------------------------------------------

class TestPiiAuditLogger:
    def _make_entities(self):
        from rag.llm.pii_masking import DetectedEntity
        return [
            DetectedEntity("EMAIL_ADDRESS", 0, 10, 0.99, "<EMAIL_ADDRESS>"),
            DetectedEntity("PERSON", 15, 25, 0.87, "<PERSON>"),
        ]

    @patch.dict(os.environ, {"PII_AUDIT_LOG_LEVEL": "summary", "PII_AUDIT_LOG_DESTINATION": "app"})
    def test_summary_log_emitted(self):
        from rag.llm.pii_masking import PiiAuditLogger
        al = PiiAuditLogger()
        with patch.object(al._audit_logger, "info") as mock_warn:
            al.log_detection(self._make_entities(), conversation_id="abc123")
        mock_warn.assert_called_once()
        msg = mock_warn.call_args[0][0]
        assert "abc123" in msg
        assert "EMAIL_ADDRESS:1" in msg
        assert "PERSON:1" in msg
        assert "total=2" in msg

    @patch.dict(os.environ, {"PII_AUDIT_LOG_LEVEL": "detailed", "PII_AUDIT_LOG_DESTINATION": "app"})
    def test_detailed_log_per_entity(self):
        from rag.llm.pii_masking import PiiAuditLogger
        al = PiiAuditLogger()
        with patch.object(al._audit_logger, "info") as mock_warn:
            al.log_detection(self._make_entities(), conversation_id="xyz")
        assert mock_warn.call_count == 2
        first_msg = mock_warn.call_args_list[0][0][0]
        assert "score=" in first_msg
        assert "start=" in first_msg

    @patch.dict(os.environ, {"PII_AUDIT_LOG_LEVEL": "summary", "PII_AUDIT_LOG_DESTINATION": "app"})
    def test_no_original_value_in_log(self):
        """Original PII values must never appear in audit logs."""
        from rag.llm.pii_masking import PiiAuditLogger
        al = PiiAuditLogger()
        with patch.object(al._audit_logger, "info") as mock_warn:
            al.log_detection(self._make_entities(), conversation_id="abc")
        msg = mock_warn.call_args[0][0]
        assert "john@example.com" not in msg
        assert "Jean Dupont" not in msg

    @patch.dict(os.environ, {"PII_AUDIT_LOG_LEVEL": "summary", "PII_AUDIT_LOG_DESTINATION": "app"})
    def test_empty_entities_no_log(self):
        from rag.llm.pii_masking import PiiAuditLogger
        al = PiiAuditLogger()
        with patch.object(al._audit_logger, "info") as mock_warn:
            al.log_detection([])
        mock_warn.assert_not_called()

    @patch.dict(os.environ, {"PII_AUDIT_LOG_LEVEL": "summary", "PII_AUDIT_LOG_DESTINATION": "app"})
    def test_model_included_in_log(self):
        from rag.llm.pii_masking import PiiAuditLogger
        al = PiiAuditLogger()
        with patch.object(al._audit_logger, "info") as mock_warn:
            al.log_detection(self._make_entities(), model="gpt-4o::pii@OpenAI")
        msg = mock_warn.call_args[0][0]
        assert "gpt-4o::pii@OpenAI" in msg
