# Eurelis — ContextVar-based token accumulator for LLM calls during document ingestion.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

from collections import defaultdict
from contextvars import ContextVar
from typing import Optional

# Maps (model_name, provider) → token count
_Accumulator = dict[tuple[str, str], int]


class _Counter:
    __slots__ = ("by_model",)

    def __init__(self) -> None:
        self.by_model: _Accumulator = defaultdict(int)


_ingestion_counter: ContextVar[Optional[_Counter]] = ContextVar(
    "_ingestion_counter", default=None
)


def start_ingestion_llm_tracking() -> None:
    """Activate LLM token accumulation for the current async context."""
    _ingestion_counter.set(_Counter())


def add_ingestion_llm_tokens(n: int, model: str = "", provider: str = "") -> None:
    """Add tokens to the per-(model, provider) accumulator if active (no-op outside ingestion)."""
    counter = _ingestion_counter.get()
    if counter is not None and n:
        counter.by_model[(model, provider)] += n


def stop_ingestion_llm_tracking() -> _Accumulator:
    """Read accumulated LLM tokens by (model, provider) and deactivate tracking.

    Returns an empty dict when called outside an active tracking context.
    """
    counter = _ingestion_counter.get()
    _ingestion_counter.set(None)
    return dict(counter.by_model) if counter else {}
