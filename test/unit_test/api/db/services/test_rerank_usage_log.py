# Eurelis — tests unitaires du logging de consommation du reranking (token_type="rerank").
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Vérifie (1) que LLMBundle.similarity accumule les tokens rerank sur le bundle
# et (2) que les wrappers eurelis_usage_log écrivent bien une ligne token_type="rerank".

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from api.db.services.llm_service import LLMBundle
from api.db.services import eurelis_usage_log

pytestmark = pytest.mark.p1


def _bundle(used_tokens_returned):
    b = LLMBundle.__new__(LLMBundle)
    b.langfuse = None
    b.used_tokens = 0
    b.mdl = MagicMock()
    b.mdl.similarity.return_value = (np.array([0.5]), used_tokens_returned)
    return b


def test_similarity_accumulates_used_tokens_on_the_bundle():
    b = _bundle(42)
    _, used = b.similarity("q", ["a"])
    assert used == 42
    assert b.used_tokens == 42
    b.mdl.similarity.return_value = (np.array([0.1]), 8)
    b.similarity("q", ["c"])
    assert b.used_tokens == 50  # accumulated across calls


@pytest.mark.asyncio
async def test_log_rerank_from_bundle_writes_rerank_row():
    rerank_mdl = MagicMock()
    rerank_mdl.used_tokens = 123
    rerank_mdl.model_config = {"llm_name": "cohere.rerank-v3-5:0", "llm_factory": "Bedrock"}
    with patch.object(eurelis_usage_log.UsageLogService, "log") as log:
        await eurelis_usage_log.log_rerank_from_bundle(rerank_mdl, source="search", user_id="u1", resource_id="s1")
    log.assert_called_once()
    kw = log.call_args.kwargs
    assert kw["token_type"] == "rerank"
    assert kw["tokens"] == 123
    assert kw["source"] == "search"
    assert kw["model"] == "cohere.rerank-v3-5:0"
    assert kw["provider"] == "Bedrock"


@pytest.mark.asyncio
async def test_log_rerank_from_usage_reads_usage_dict():
    usage = {"rerank_tokens": 77, "rerank_model": "amazon.rerank-v1:0", "rerank_provider": "Bedrock"}
    with patch.object(eurelis_usage_log.UsageLogService, "log") as log:
        await eurelis_usage_log.log_rerank_from_usage(usage, source="chat", user_id="u1", resource_id="d1", object_id="c1")
    kw = log.call_args.kwargs
    assert kw["token_type"] == "rerank"
    assert kw["tokens"] == 77
    assert kw["object_id"] == "c1"


@pytest.mark.asyncio
async def test_log_rerank_from_bundle_noop_without_model():
    with patch.object(eurelis_usage_log.UsageLogService, "log") as log:
        await eurelis_usage_log.log_rerank_from_bundle(None, source="search", user_id="u1", resource_id="s1")
    log.assert_not_called()


@pytest.mark.asyncio
async def test_zero_rerank_tokens_are_not_logged():
    usage = {"rerank_tokens": 0}
    with patch.object(eurelis_usage_log.UsageLogService, "log") as log:
        await eurelis_usage_log.log_rerank_from_usage(usage, source="chat", user_id="u1", resource_id="d1")
    log.assert_not_called()
