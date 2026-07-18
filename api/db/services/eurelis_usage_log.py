# Eurelis — Helpers de logging dans usage_log pour les flux non instrumentés par l'upstream.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Modèle orthogonal :
#   - source     : le flux (chat | search | agent | dataset | ingestion)
#   - token_type : la nature du token (llm | embedding)
#
# Ce module couvre :
#   - les tokens d'embedding de requête (retrieval)  → token_type="embedding"
#   - les tokens du LLM de synthèse de la recherche IA → token_type="llm", source="search"

import logging

from api.db.services.usage_log_service import UsageLogService
from common.misc_utils import thread_pool_exec
from common.token_utils import num_tokens_from_string

logger = logging.getLogger(__name__)


async def _log(*, source, token_type, user_id, resource_id, object_id, tokens, model, provider, duration=0.0):
    """Write a single usage_log entry. Never raises (logging must not break the flow)."""
    if not tokens and not duration:
        return
    try:
        await thread_pool_exec(
            UsageLogService.log,
            user_id=user_id or "",
            resource_id=resource_id or "",
            object_id=object_id or "",
            source=source,
            token_type=token_type,
            tokens=tokens,
            duration=duration,
            model=model or "",
            provider=provider or "",
        )
    except Exception as e:  # logging must never break retrieval/chat
        logger.warning("Failed to write usage_log (source=%s token_type=%s): %s", source, token_type, e)


async def log_embedding_from_bundle(embd_mdl, *, source, user_id, resource_id, object_id=""):
    """Log query-embedding usage from an LLMBundle's accumulated ``used_tokens``.

    Used by flows that hold the embedding bundle directly (search, agent
    retrieval, dataset SDK retrieval). ``source`` is the originating flow.
    """
    if not embd_mdl:
        return
    await _log(
        source=source,
        token_type="embedding",
        user_id=user_id,
        resource_id=resource_id,
        object_id=object_id,
        tokens=getattr(embd_mdl, "used_tokens", 0),
        model=embd_mdl.model_config.get("llm_name", ""),
        provider=embd_mdl.model_config.get("llm_factory", ""),
    )


async def log_embedding_from_usage(usage, *, source, user_id, resource_id, object_id=""):
    """Log query-embedding usage from a chat ``usage`` dict propagated by async_chat.

    Used by the chat flows where the embedding bundle is not available at the
    API layer; ``async_chat`` surfaces ``embedding_tokens`` in ``usage``.
    """
    usage = usage or {}
    await _log(
        source=source,
        token_type="embedding",
        user_id=user_id,
        resource_id=resource_id,
        object_id=object_id,
        tokens=usage.get("embedding_tokens", 0),
        model=usage.get("embedding_model", ""),
        provider=usage.get("embedding_provider", ""),
    )


async def log_rerank_from_bundle(rerank_mdl, *, source, user_id, resource_id, object_id=""):
    """Log reranking usage from an LLMBundle's accumulated ``used_tokens``.

    Mirrors ``log_embedding_from_bundle`` for the reranker; ``source`` is the
    originating flow. No-op when no reranker is configured.
    """
    if not rerank_mdl:
        return
    await _log(
        source=source,
        token_type="rerank",
        user_id=user_id,
        resource_id=resource_id,
        object_id=object_id,
        tokens=getattr(rerank_mdl, "used_tokens", 0),
        model=rerank_mdl.model_config.get("llm_name", ""),
        provider=rerank_mdl.model_config.get("llm_factory", ""),
    )


async def log_rerank_from_usage(usage, *, source, user_id, resource_id, object_id=""):
    """Log reranking usage from a chat ``usage`` dict propagated by async_chat."""
    usage = usage or {}
    await _log(
        source=source,
        token_type="rerank",
        user_id=user_id,
        resource_id=resource_id,
        object_id=object_id,
        tokens=usage.get("rerank_tokens", 0),
        model=usage.get("rerank_model", ""),
        provider=usage.get("rerank_provider", ""),
    )


async def log_search_completion(*, user_id, resource_id, prompt_text, completion_text,
                                model, provider, object_id="", duration_ms=0.0):
    """Log the LLM synthesis tokens of the search "ask" flow → source="search", token_type="llm".

    Token counts are approximated with num_tokens_from_string (same approach as
    async_chat), since async_ask does not surface provider token usage.
    """
    try:
        tokens = num_tokens_from_string(prompt_text or "") + num_tokens_from_string(completion_text or "")
    except Exception as e:  # token counting must never break the search flow
        logger.warning("Failed to count search completion tokens: %s", e)
        return
    await _log(
        source="search",
        token_type="llm",
        user_id=user_id,
        resource_id=resource_id,
        object_id=object_id,
        tokens=tokens,
        model=model,
        provider=provider,
        duration=duration_ms,
    )
