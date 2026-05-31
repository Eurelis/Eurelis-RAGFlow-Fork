#
#  Copyright 2024 The Eurelis Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""
PII Masking module for RAGFlow (Eurelis fork).

Detects and masks Personally Identifiable Information in LLM messages
before they are sent to any LLM provider, using Microsoft Presidio.

Configuration via environment variables — see docker/.env for reference.

Usage:
    # At server startup (ragflow_server.py):
    PiiMaskingEngine.initialize()

    # In LiteLLMBase._construct_completion_args():
    history, effective_model = apply_pii_masking(history, model_name, prefix, provider)
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# Suffix convention for "masked" variant of a model (Option A).
# e.g. "gpt-4o__pii@OpenAI" → actual model "gpt-4o", PII masking enabled.
PII_MODEL_SUFFIX = "__pii"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PiiBlockedException(Exception):
    """Raised when a message contains a PII entity configured as BLOCK."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DetectedEntity:
    """A single PII entity detected by Presidio."""
    entity_type: str   # e.g. "EMAIL_ADDRESS"
    start: int         # position in original text
    end: int           # position in original text
    score: float       # Presidio confidence score (0.0–1.0)
    placeholder: str   # e.g. "<EMAIL_ADDRESS>"


@dataclass
class MaskingResult:
    """Result of masking a single text."""
    masked_text: str
    mapping: dict[str, str] = field(default_factory=dict)  # placeholder → original value (v1)
    entities: list[DetectedEntity] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Shared masking state — consistent placeholders across all messages in a request
# ---------------------------------------------------------------------------

class _SharedMaskingState:
    """
    Maintains a canonical value → placeholder mapping for a single masking request.

    Ensures that the same original value always gets the same numbered placeholder,
    even when it appears across different messages (e.g. user and system/RAG context).

    Example:
        "Jean Dupont" → "<PERSON_1>" in the user message AND in the RAG system message.
        "alice@corp.com" → "<EMAIL_ADDRESS_1>" consistently in all messages.
    """

    def __init__(self) -> None:
        self._value_to_placeholder: dict[str, str] = {}
        self._placeholder_to_value: dict[str, str] = {}
        self._counters: dict[str, int] = {}

    def get_or_create(self, entity_type: str, original_value: str) -> str:
        """Return the placeholder for *original_value*, creating a new numbered one if needed."""
        existing = self._value_to_placeholder.get(original_value)
        if existing is not None:
            return existing
        count = self._counters.get(entity_type, 0) + 1
        self._counters[entity_type] = count
        placeholder = f"<{entity_type}_{count}>"
        self._value_to_placeholder[original_value] = placeholder
        self._placeholder_to_value[placeholder] = original_value
        return placeholder

    def get_placeholder(self, original_value: str) -> str | None:
        """Return the existing placeholder for *original_value*, or None if not yet mapped."""
        return self._value_to_placeholder.get(original_value)

    @property
    def placeholder_to_value(self) -> dict[str, str]:
        """Snapshot of the placeholder → original value mapping (for v1 unmasking)."""
        return dict(self._placeholder_to_value)


# ---------------------------------------------------------------------------
# Streaming unmasker (v1 — included but not wired in MVP)
# ---------------------------------------------------------------------------

class StreamingUnmasker:
    """
    Replaces PII placeholders in a streaming response on-the-fly.

    Uses a sliding-window buffer: content is passed through immediately
    unless a '<' signals a potential placeholder. Only the placeholder
    tokens are buffered while waiting for the closing '>'.
    """

    MAX_PLACEHOLDER_LEN = 60

    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping
        self.buffer = ""

    def process_chunk(self, chunk: str) -> str:
        self.buffer += chunk
        output = ""

        while self.buffer:
            if not self.buffer.startswith("<"):
                # No placeholder in sight — flush up to the next '<'
                lt = self.buffer.find("<")
                if lt == -1:
                    output += self.buffer
                    self.buffer = ""
                else:
                    output += self.buffer[:lt]
                    self.buffer = self.buffer[lt:]
            else:
                gt = self.buffer.find(">")
                if gt == -1:
                    # Incomplete placeholder — wait for more data
                    if len(self.buffer) > self.MAX_PLACEHOLDER_LEN:
                        # Too long to be a placeholder — release one char
                        output += self.buffer[0]
                        self.buffer = self.buffer[1:]
                    else:
                        break
                else:
                    candidate = self.buffer[: gt + 1]  # e.g. "<EMAIL_ADDRESS>"
                    output += self.mapping.get(candidate, candidate)
                    self.buffer = self.buffer[gt + 1:]

        return output

    def flush(self) -> str:
        """Flush remaining buffer at end-of-stream."""
        remaining = self.buffer
        self.buffer = ""
        for placeholder, original in self.mapping.items():
            remaining = remaining.replace(placeholder, original)
        return remaining


async def unmask_stream(
    stream: AsyncIterator[str],
    mapping: dict[str, str],
) -> AsyncIterator[str]:
    """Async wrapper around StreamingUnmasker for RAGFlow generators."""
    unmasker = StreamingUnmasker(mapping)
    async for chunk in stream:
        out = unmasker.process_chunk(chunk)
        if out:
            yield out
    tail = unmasker.flush()
    if tail:
        yield tail


# ---------------------------------------------------------------------------
# Audit logger
# ---------------------------------------------------------------------------

class PiiAuditLogger:
    """
    Logs PII detection events without ever exposing original values.

    Configuration:
        PII_AUDIT_LOG_LEVEL       : "summary" | "detailed"
        PII_AUDIT_LOG_DESTINATION : "app" | "file" | "both"
        PII_AUDIT_LOG_FILE        : path to dedicated log file
    """

    def __init__(self) -> None:
        self._level = os.getenv("PII_AUDIT_LOG_LEVEL", "summary")
        self._destination = os.getenv("PII_AUDIT_LOG_DESTINATION", "app")
        self._file_path = os.getenv("PII_AUDIT_LOG_FILE", "/ragflow/logs/pii_audit.log")
        self._file_handler: logging.Handler | None = None
        self._audit_logger = logging.getLogger("ragflow.pii")

        if self._destination in ("file", "both"):
            self._setup_file_handler()

    def _setup_file_handler(self) -> None:
        import logging.handlers
        try:
            log_dir = os.path.dirname(self._file_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
            handler = logging.handlers.RotatingFileHandler(
                self._file_path,
                maxBytes=50 * 1024 * 1024,  # 50 MB
                backupCount=5,
                encoding="utf-8",
            )
            handler.setLevel(logging.WARNING)
            self._file_handler = handler
        except Exception as e:
            logger.warning(f"PiiAuditLogger: could not set up file handler at {self._file_path}: {e}")

    def _emit(self, msg: str) -> None:
        if self._destination in ("app", "both"):
            self._audit_logger.warning(msg)
        if self._destination in ("file", "both") and self._file_handler:
            record = logging.LogRecord(
                name="ragflow.pii",
                level=logging.WARNING,
                pathname="",
                lineno=0,
                msg=msg,
                args=(),
                exc_info=None,
            )
            self._file_handler.emit(record)

    def log_detection(
        self,
        entities: list[DetectedEntity],
        conversation_id: str | None = None,
        message_role: str = "user",
        model: str | None = None,
    ) -> None:
        """
        Log a PII detection event.
        Never logs original values or placeholder→value mappings.
        """
        if not entities:
            return

        conv_id = conversation_id or "unknown"
        model_part = f" model={model}" if model else ""

        if self._level == "summary":
            counts: dict[str, int] = {}
            for e in entities:
                counts[e.entity_type] = counts.get(e.entity_type, 0) + 1
            entities_str = ",".join(f"{k}:{v}" for k, v in sorted(counts.items()))
            self._emit(
                f"pii_detected conversation_id={conv_id} role={message_role}"
                f" entities={entities_str} total={len(entities)}{model_part}"
            )

        elif self._level == "detailed":
            for e in entities:
                self._emit(
                    f"pii_detected conversation_id={conv_id} role={message_role}"
                    f" entity_type={e.entity_type} placeholder={e.placeholder}"
                    f" start={e.start} end={e.end} score={e.score:.2f}{model_part}"
                )


# ---------------------------------------------------------------------------
# PII Masking Engine (singleton)
# ---------------------------------------------------------------------------

class PiiMaskingEngine:
    """
    Singleton that holds Presidio AnalyzerEngine + AnonymizerEngine.
    Loaded once at server startup via PiiMaskingEngine.initialize().

    Both engines are stateless per-call and thread-safe.
    """

    _instance: PiiMaskingEngine | None = None
    _lock = threading.Lock()

    def __init__(
        self,
        analyzer,
        anonymizer,
        entities_config: dict[str, str],
        score_thresholds: dict[str, float],
        audit_logger: PiiAuditLogger,
    ) -> None:
        self.analyzer = analyzer
        self.anonymizer = anonymizer
        self.entities_config = entities_config   # {entity_type: "MASK"|"BLOCK"}
        self.score_thresholds = score_thresholds  # per-entity overrides
        self.audit_logger = audit_logger

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @classmethod
    def initialize(cls) -> None:
        """
        Load Presidio engines and spaCy models (if NER is enabled).
        No-op if both PII_MASKING_ENABLED and PII_AUDIT_LOG_ENABLED are false.

        On failure:
            PII_MASKING_STARTUP_FAIL=true  → raises RuntimeError (default)
            PII_MASKING_STARTUP_FAIL=false → logs error, engine stays None
        """
        masking_enabled = os.getenv("PII_MASKING_ENABLED", "false").lower() == "true"
        audit_enabled = os.getenv("PII_AUDIT_LOG_ENABLED", "false").lower() == "true"

        if not masking_enabled and not audit_enabled:
            logging.info("PII masking disabled — PiiMaskingEngine skipped")
            return

        with cls._lock:
            if cls._instance is not None:
                return  # Already initialized (idempotent)
            try:
                cls._instance = cls._do_initialize()
            except Exception as exc:
                fail_on_error = os.getenv("PII_MASKING_STARTUP_FAIL", "true").lower() == "true"
                if fail_on_error:
                    raise RuntimeError(
                        f"PiiMaskingEngine initialization failed: {exc}"
                    ) from exc
                logging.error(
                    f"PiiMaskingEngine initialization failed (PII masking disabled): {exc}"
                )

    @classmethod
    def _do_initialize(cls) -> PiiMaskingEngine:
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry
        from presidio_anonymizer import AnonymizerEngine

        ts = time.time()

        entities_config = cls._parse_entities_config()
        score_thresholds = cls._parse_score_thresholds()
        languages = [lg.strip() for lg in os.getenv("PII_MASKING_LANGUAGES", "en").split(",") if lg.strip()]
        ner_enabled = os.getenv("PII_MASKING_NER", "false").lower() == "true"

        # Determine if NER models are needed
        ner_entity_types = {"PERSON", "LOCATION", "DATE_TIME"}
        needs_ner = ner_enabled and bool(ner_entity_types & set(entities_config.keys()))

        nlp_engine = None
        if needs_ner:
            nlp_engine = cls._load_nlp_engine(languages)
        else:
            logging.info(
                "NER disabled — spaCy not loaded"
                " (PERSON, LOCATION, DATE_TIME detection unavailable)"
            )

        # Build recognizer registry
        registry = RecognizerRegistry()
        registry.load_predefined_recognizers(languages=languages, nlp_engine=nlp_engine)

        # Load custom recognizers
        custom_count, custom_names = 0, []
        custom_file = os.getenv("PII_MASKING_CUSTOM_RECOGNIZERS_FILE", "").strip()
        if custom_file and os.path.exists(custom_file):
            custom_count, custom_names = cls._load_custom_recognizers(registry, custom_file)

        analyzer = AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=languages,
        )
        anonymizer = AnonymizerEngine()
        audit_logger = PiiAuditLogger()

        elapsed = time.time() - ts
        ner_tag = (
            f"NER: {os.getenv('PII_MASKING_NER_MODEL_EN', 'en_core_web_lg')}"
            if needs_ner
            else "regex/checksum only"
        )
        custom_tag = f", custom recognizers: {custom_count}" if custom_count else ""
        logging.info(f"PiiMaskingEngine initialized in {elapsed:.1f}s ({ner_tag}{custom_tag})")

        if custom_names:
            logging.info(
                f"PiiMaskingEngine: {custom_count} custom recognizers loaded"
                f" ({', '.join(custom_names)})"
            )

        return cls(analyzer, anonymizer, entities_config, score_thresholds, audit_logger)

    @classmethod
    def _load_nlp_engine(cls, languages: list[str]):
        from presidio_analyzer.nlp_engine import NlpEngineProvider

        models = []
        for lang in languages:
            if lang == "en":
                model = os.getenv("PII_MASKING_NER_MODEL_EN", "en_core_web_lg")
            elif lang == "fr":
                model = os.getenv("PII_MASKING_NER_MODEL_FR", "fr_core_news_lg")
            else:
                logging.warning(f"PiiMaskingEngine: no NER model configured for language '{lang}', skipping")
                continue
            logging.info(f"Loading spaCy model {model} (excluding: tagger, parser, lemmatizer)…")
            models.append({"lang_code": lang, "model_name": model})

        if not models:
            return None

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": models,
        })
        return provider.create_engine()

    @classmethod
    def _load_custom_recognizers(
        cls, registry, yaml_file: str
    ) -> tuple[int, list[str]]:
        """Load custom recognizers from YAML. Returns (count, names)."""
        import yaml
        from presidio_analyzer import Pattern, PatternRecognizer

        with open(yaml_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        recognizers_cfg = config.get("recognizers", [])
        loaded, names = 0, []

        for rec_cfg in recognizers_cfg:
            try:
                name = rec_cfg["name"]
                entity = rec_cfg["supported_entity"]
                rec_type = rec_cfg.get("type", "pattern")
                langs = rec_cfg.get("language", "en")
                if isinstance(langs, str):
                    langs = [langs]

                for lang in langs:
                    if rec_type == "pattern":
                        patterns = [
                            Pattern(
                                name=p["name"],
                                regex=p["regex"],
                                score=float(p.get("score", 0.8)),
                            )
                            for p in rec_cfg.get("patterns", [])
                        ]
                        recognizer = PatternRecognizer(
                            supported_entity=entity,
                            patterns=patterns,
                            context=rec_cfg.get("context", []),
                            supported_language=lang,
                            name=f"{name}_{lang}",
                        )
                    elif rec_type == "deny_list":
                        recognizer = PatternRecognizer(
                            supported_entity=entity,
                            deny_list=rec_cfg.get("deny_list", []),
                            supported_language=lang,
                            name=f"{name}_{lang}",
                        )
                    else:
                        logging.warning(
                            f"PiiMaskingEngine: unknown recognizer type '{rec_type}'"
                            f" for '{name}', skipping"
                        )
                        continue

                    registry.add_recognizer(recognizer)

                loaded += 1
                names.append(name)

            except Exception as exc:
                logging.warning(
                    f"PiiMaskingEngine: failed to load custom recognizer"
                    f" '{rec_cfg.get('name', '?')}': {exc}"
                )

        return loaded, names

    @classmethod
    def get(cls) -> PiiMaskingEngine:
        """Return the initialized singleton. Raises RuntimeError if not initialized."""
        if cls._instance is None:
            raise RuntimeError(
                "PiiMaskingEngine not initialized. "
                "Call PiiMaskingEngine.initialize() at server startup."
            )
        return cls._instance

    @classmethod
    def is_available(cls) -> bool:
        """True if the engine was successfully initialized."""
        return cls._instance is not None

    # ------------------------------------------------------------------
    # Config parsing helpers
    # ------------------------------------------------------------------

    @classmethod
    def _parse_entities_config(cls) -> dict[str, str]:
        """Parse PII_MASKING_ENTITIES → {entity_type: "MASK"|"BLOCK"}."""
        raw = os.getenv(
            "PII_MASKING_ENTITIES",
            "PERSON:MASK,EMAIL_ADDRESS:MASK,PHONE_NUMBER:MASK,"
            "CREDIT_CARD:MASK,IBAN_CODE:MASK,IP_ADDRESS:MASK",
        )
        config: dict[str, str] = {}
        for item in raw.split(","):
            item = item.strip()
            if ":" in item:
                entity, action = item.split(":", 1)
                config[entity.strip()] = action.strip().upper()
        return config

    @classmethod
    def _parse_score_thresholds(cls) -> dict[str, float]:
        """Parse PII_MASKING_SCORE_OVERRIDES → {entity_type: float}."""
        raw = os.getenv("PII_MASKING_SCORE_OVERRIDES", "PERSON:0.85,CREDIT_CARD:0.6").strip()
        thresholds: dict[str, float] = {}
        for item in raw.split(","):
            item = item.strip()
            if ":" in item:
                entity, score_str = item.split(":", 1)
                try:
                    thresholds[entity.strip()] = float(score_str.strip())
                except ValueError:
                    logging.warning(
                        f"PiiMaskingEngine: invalid score '{score_str.strip()}'"
                        f" for entity '{entity.strip()}', ignoring"
                    )
        return thresholds

    # ------------------------------------------------------------------
    # Masking
    # ------------------------------------------------------------------

    def mask_messages(
        self,
        messages: list[dict],
        language: str = "en",
        roles_to_mask: list[str] | None = None,
        mask: bool = True,
    ) -> tuple[list[dict], dict[str, str], list[DetectedEntity]]:
        """
        Analyze (and optionally anonymize) PII in a list of OpenAI-format messages.

        Args:
            messages:      List of {"role": ..., "content": ...} dicts.
            language:      Language code for Presidio analysis (e.g. "en", "fr").
            roles_to_mask: Only process messages with these roles (default: ["user"]).
            mask:          If True, replace PII with placeholders. If False, analyze only.

        Returns:
            (masked_messages, mapping, all_entities)
            - masked_messages: messages with PII replaced (or original if mask=False)
            - mapping: {placeholder: original_value} for v1 unmasking (empty in MVP)
            - all_entities: all DetectedEntity instances across all processed messages
        """
        if roles_to_mask is None:
            roles_to_mask = ["user"]

        all_entities: list[DetectedEntity] = []
        masked_messages: list[dict] = []
        # One shared state for the whole request — same value → same placeholder across messages.
        shared_state = _SharedMaskingState()

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")

            if role not in roles_to_mask or not isinstance(content, str) or not content:
                masked_messages.append(msg)
                continue

            result = self._mask_text(content, language=language, mask=mask, shared_state=shared_state)
            all_entities.extend(result.entities)

            if mask and result.masked_text != content:
                masked_msg = dict(msg)
                masked_msg["content"] = result.masked_text
                masked_messages.append(masked_msg)
            else:
                masked_messages.append(msg)

        return masked_messages, shared_state.placeholder_to_value, all_entities

    def _mask_text(
        self,
        text: str,
        language: str = "en",
        mask: bool = True,
        shared_state: _SharedMaskingState | None = None,
    ) -> MaskingResult:
        """Analyze and optionally anonymize PII in a single text string.

        Args:
            shared_state: Optional shared state for cross-message placeholder consistency.
                          If None, a local state is created (standalone call).
                          Pass the same instance across multiple messages to ensure
                          identical values receive identical numbered placeholders.
        """
        from presidio_anonymizer.entities import OperatorConfig

        global_threshold = float(os.getenv("PII_MASKING_SCORE_THRESHOLD", "0.7"))
        entity_types = list(self.entities_config.keys())

        # Analyze
        try:
            raw_results = self.analyzer.analyze(
                text=text,
                language=language,
                entities=entity_types,
                score_threshold=global_threshold,
            )
        except Exception as exc:
            logging.warning(f"Presidio analysis failed: {exc}")
            return MaskingResult(masked_text=text)

        # Apply per-entity score overrides
        filtered = [
            r for r in raw_results
            if r.score >= self.score_thresholds.get(r.entity_type, global_threshold)
        ]

        # Build DetectedEntity list
        entities = [
            DetectedEntity(
                entity_type=r.entity_type,
                start=r.start,
                end=r.end,
                score=r.score,
                placeholder=f"<{r.entity_type}>",
            )
            for r in filtered
        ]

        # BLOCK check — raise before any anonymization
        for entity in entities:
            if self.entities_config.get(entity.entity_type) == "BLOCK":
                raise PiiBlockedException(
                    f"Request blocked: message contains {entity.entity_type}"
                )

        if not mask or not filtered:
            return MaskingResult(masked_text=text, entities=entities)

        # Use provided shared state or create a local one for this standalone call.
        # The shared state ensures the same original value always receives the same
        # numbered placeholder (e.g. <PERSON_1>) across all messages of a request.
        _state = shared_state if shared_state is not None else _SharedMaskingState()

        def _make_replacer(entity_type: str, state: _SharedMaskingState):
            return lambda original_text: state.get_or_create(entity_type, original_text)

        operators = {
            et: OperatorConfig("custom", {"lambda": _make_replacer(et, _state)})
            for et, action in self.entities_config.items()
            if action == "MASK"
        }

        # Anonymize
        try:
            anonymized = self.anonymizer.anonymize(
                text=text,
                analyzer_results=filtered,
                operators=operators,
            )
        except Exception as exc:
            logging.warning(f"Presidio anonymization failed: {exc}")
            return MaskingResult(masked_text=text, entities=entities)

        # Update each entity's placeholder to the actual numbered value assigned
        # by _state during anonymization (e.g. <PERSON_2> instead of generic <PERSON>).
        for entity in entities:
            original_value = text[entity.start:entity.end]
            actual = _state.get_placeholder(original_value)
            if actual is not None:
                entity.placeholder = actual

        return MaskingResult(
            masked_text=anonymized.text,
            mapping={},   # MVP: unmasking not implemented
            entities=entities,
        )


# ---------------------------------------------------------------------------
# Hook function — called from LiteLLMBase._construct_completion_args()
# ---------------------------------------------------------------------------

def apply_pii_masking(
    history: list[dict],
    model_name: str,
    prefix: str,
    provider: str,
) -> tuple[list[dict], str]:
    """
    Apply PII masking to LLM history if the model matches PII_MASKING_PROVIDERS.

    Also strips the ``__pii`` suffix from the model name so LiteLLM receives
    the real model name (e.g. "openai/gpt-4o" instead of "openai/gpt-4o__pii").

    Args:
        history:    OpenAI-format message list.
        model_name: Full LiteLLM model name (e.g. "openai/gpt-4o__pii").
        prefix:     LiteLLM provider prefix (e.g. "openai/").
        provider:   RAGFlow factory name (e.g. "OpenAI").

    Returns:
        (masked_history, effective_model_name, mapping)
        - mapping: {placeholder → original_value} for response rehydration.
          Empty dict when masking is disabled or no PII detected.
    """
    # Strip __pii suffix from the name sent to LiteLLM
    raw_model_name = model_name.removeprefix(prefix)
    if raw_model_name.endswith(PII_MODEL_SUFFIX):
        effective_model_name = prefix + raw_model_name[: -len(PII_MODEL_SUFFIX)]
    else:
        effective_model_name = model_name

    masking_enabled = os.getenv("PII_MASKING_ENABLED", "false").lower() == "true"
    audit_enabled = os.getenv("PII_AUDIT_LOG_ENABLED", "false").lower() == "true"

    if not (masking_enabled or audit_enabled) or not PiiMaskingEngine.is_available():
        return history, effective_model_name, {}

    # Check provider whitelist
    providers_filter = os.getenv("PII_MASKING_PROVIDERS", "").strip()
    if not providers_filter:
        return history, effective_model_name, {}

    match_target = f"{raw_model_name}@{provider}"
    should_process = _matches_providers_filter(match_target, providers_filter)

    if not should_process:
        return history, effective_model_name, {}

    # Apply masking / analysis
    engine = PiiMaskingEngine.get()
    language = os.getenv("PII_MASKING_LANGUAGES", "en").split(",")[0].strip()
    roles = [r.strip() for r in os.getenv("PII_MASKING_ROLES", "user").split(",")]

    masked_history, mapping, all_entities = engine.mask_messages(
        messages=history,
        language=language,
        roles_to_mask=roles,
        mask=masking_enabled,
    )

    if audit_enabled and all_entities:
        engine.audit_logger.log_detection(
            entities=all_entities,
            message_role="user",
            model=match_target,
        )

    return masked_history, effective_model_name, mapping


def unmask_text(text: str, mapping: dict[str, str]) -> str:
    """Replace all placeholders in *text* with their original values.

    Safe to call with an empty mapping (returns text unchanged).
    """
    for placeholder, original in mapping.items():
        text = text.replace(placeholder, original)
    return text


def _matches_providers_filter(match_target: str, providers_filter: str) -> bool:
    """Test if match_target matches any pattern in the comma-separated providers_filter."""
    for pattern in providers_filter.split(","):
        pattern = pattern.strip()
        if not pattern:
            continue
        try:
            if re.fullmatch(pattern, match_target):
                return True
        except re.error:
            logging.warning(
                f"PII masking: invalid regex pattern '{pattern}'"
                f" in PII_MASKING_PROVIDERS, ignoring"
            )
    return False
