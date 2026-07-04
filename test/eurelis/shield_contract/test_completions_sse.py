# Eurelis — contrat P0 du flux SSE POST /api/v1/chats/{id}/completions (cœur consommé par le Shield).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import httpx
import pytest

from configs import HOST_ADDRESS, HTTP_TIMEOUT, VERSION
from libs.contract import assert_valid
from libs.sse import stream_completions
from schemas.completions import (
    ANSWER_DATA_SCHEMA,
    CHUNK_SCHEMA,
    DOC_AGG_SCHEMA,
    ENVELOPE_SCHEMA,
    REFERENCE_SCHEMA,
    USAGE_SCHEMA,
)

QUESTION = "Qu'est-ce que RAGFlow et que fait Eurelis ?"


@pytest.fixture(scope="module")
def completion(token, ref_chat_id):
    """Streame une complétion une seule fois ; partage les frames avec tous les tests du module."""
    with httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        r = client.post(f"/api/{VERSION}/chats/{ref_chat_id}/sessions", json={"name": "sse-contract"})
        session_id = r.json()["data"]["id"]
        frames = stream_completions(client, ref_chat_id, QUESTION, session_id)
        yield {"frames": frames, "session_id": session_id, "chat_id": ref_chat_id}
        client.request("DELETE", f"/api/{VERSION}/chats/{ref_chat_id}/sessions", json={"ids": [session_id]})


def _object_frames(frames):
    return [f for f in frames if isinstance(f.get("data"), dict)]


def _final_frame(frames):
    finals = [f for f in _object_frames(frames) if f["data"].get("final") is True]
    assert len(finals) == 1, f"attendu 1 frame finale, trouvé {len(finals)}"
    return finals[0]["data"]


@pytest.mark.p0
def test_frames_received(completion):
    """Le flux SSE renvoie au moins une frame de réponse et une frame terminale."""
    frames = completion["frames"]
    assert len(frames) >= 2, f"flux trop court : {frames}"
    assert _object_frames(frames), "aucune frame de réponse (data objet)"


@pytest.mark.p0
def test_every_frame_is_valid_envelope(completion):
    """Chaque frame respecte l'enveloppe {code, message, data}."""
    for i, frame in enumerate(completion["frames"]):
        assert_valid(frame, ENVELOPE_SCHEMA, label=f"frame[{i}]")
        assert frame["code"] == 0, f"frame[{i}] code={frame['code']}"


@pytest.mark.p0
def test_terminal_sentinel(completion):
    """La dernière frame est la sentinelle terminale `data: true`, et elle est unique."""
    frames = completion["frames"]
    terminals = [f for f in frames if f.get("data") is True]
    assert len(terminals) == 1, f"attendu 1 sentinelle terminale, trouvé {len(terminals)}"
    assert frames[-1]["data"] is True, "la sentinelle n'est pas la dernière frame"


@pytest.mark.p0
def test_answer_frames_contract(completion):
    """Chaque frame de réponse respecte le contrat, avec les bons session_id/chat_id."""
    for i, frame in enumerate(_object_frames(completion["frames"])):
        assert_valid(frame["data"], ANSWER_DATA_SCHEMA, label=f"answer_frame[{i}]")
        assert frame["data"]["session_id"] == completion["session_id"]
        assert frame["data"]["chat_id"] == completion["chat_id"]


@pytest.mark.p0
def test_streaming_answer_accumulates(completion):
    """Au moins une frame de streaming (final=false) porte du texte de réponse."""
    streaming = [f["data"] for f in _object_frames(completion["frames"]) if f["data"].get("final") is False]
    assert streaming, "aucune frame de streaming (final=false)"
    assert any(d.get("answer") for d in streaming), "aucune frame de streaming ne porte de texte"


@pytest.mark.p0
def test_final_frame_reference_and_citations(completion):
    """La frame finale porte une `reference` conforme (chunks + doc_aggs) — citations du Shield."""
    data = _final_frame(completion["frames"])
    assert_valid(data["reference"], REFERENCE_SCHEMA, label="reference")
    chunks = data["reference"]["chunks"]
    assert chunks, "reference.chunks vide : la donnée de référence n'a pas été retrouvée"
    for i, chunk in enumerate(chunks):
        assert_valid(chunk, CHUNK_SCHEMA, label=f"chunk[{i}]")
    for i, agg in enumerate(data["reference"]["doc_aggs"]):
        assert_valid(agg, DOC_AGG_SCHEMA, label=f"doc_agg[{i}]")


@pytest.mark.p0
def test_final_frame_usage_contract(completion):
    """La frame finale porte `usage` (compteurs de tokens — enrichissement Eurelis + Shield)."""
    data = _final_frame(completion["frames"])
    assert "usage" in data, "usage absent de la frame finale"
    assert_valid(data["usage"], USAGE_SCHEMA, label="usage")
    u = data["usage"]
    assert u["total_tokens"] >= u["prompt_tokens"], "total_tokens < prompt_tokens (incohérent)"
