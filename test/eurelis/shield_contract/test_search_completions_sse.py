# Eurelis — P0 : contrat du résumé SSE /searches/{id}/completions consommé par le Shield (028, T030).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# On fige la STRUCTURE des frames et de la référence (chunks enrichis + doc_aggs), jamais le contenu
# généré (dépendant du LLM local Ollama). La frame finale a answer == "" (le texte arrive en deltas).

import httpx
import pytest

from configs import HOST_ADDRESS, HTTP_TIMEOUT, REF_QUERY, VERSION
from libs.contract import assert_valid
from libs.sse import stream_search_completion
from schemas.searches import (
    DOC_AGG_SCHEMA,
    SUMMARY_ANSWER_DATA_SCHEMA,
    SUMMARY_CHUNK_SCHEMA,
    SUMMARY_ENVELOPE_SCHEMA,
    SUMMARY_REFERENCE_SCHEMA,
)


@pytest.fixture(scope="module")
def summary(token, ref_search_id):
    with httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        frames = stream_search_completion(client, ref_search_id, REF_QUERY)
        return {"frames": frames}


def _object_frames(frames):
    return [f for f in frames if isinstance(f.get("data"), dict)]


def _final(frames):
    finals = [f["data"] for f in _object_frames(frames) if f["data"].get("final") is True]
    assert len(finals) == 1, f"attendu 1 frame finale, trouvé {len(finals)}"
    return finals[0]


@pytest.mark.p0
def test_summary_frames_and_terminal(summary):
    """Au moins une frame de réponse ; sentinelle terminale `data: true` unique et en dernier."""
    frames = summary["frames"]
    assert _object_frames(frames), "aucune frame de réponse (data objet)"
    terminals = [f for f in frames if f.get("data") is True]
    assert len(terminals) == 1 and frames[-1]["data"] is True, "sentinelle terminale absente/non finale"


@pytest.mark.p0
def test_summary_envelope_and_answer(summary):
    """Chaque frame respecte l'enveloppe {code,message,data} ; les frames objet respectent le contrat."""
    for i, frame in enumerate(summary["frames"]):
        assert_valid(frame, SUMMARY_ENVELOPE_SCHEMA, label=f"frame[{i}]")
        assert frame["code"] == 0
    obj = _object_frames(summary["frames"])
    for i, f in enumerate(obj):
        assert_valid(f["data"], SUMMARY_ANSWER_DATA_SCHEMA, label=f"answer[{i}]")
    assert any(f["data"].get("answer") for f in obj if f["data"].get("final") is False), \
        "aucune frame de streaming ne porte de texte"


@pytest.mark.p0
def test_summary_final_reference(summary):
    """La frame finale porte une reference (chunks enrichis + doc_aggs) — citations du Shield."""
    data = _final(summary["frames"])
    assert_valid(data["reference"], SUMMARY_REFERENCE_SCHEMA, label="reference")
    for i, c in enumerate(data["reference"]["chunks"]):
        assert_valid(c, SUMMARY_CHUNK_SCHEMA, label=f"chunk[{i}]")
    for i, a in enumerate(data["reference"].get("doc_aggs", [])):
        assert_valid(a, DOC_AGG_SCHEMA, label=f"doc_agg[{i}]")
