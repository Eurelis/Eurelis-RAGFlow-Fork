# Eurelis — contrat du paramètre `reasoning` de POST /api/v1/chats/{id}/completions.
# Le Shield envoie systématiquement un niveau de raisonnement sous forme de chaîne :
# "0"=naive (chat classique), "1"=low, "2"=medium, "3"=high, "4"=ultra.
# Ce contrat fige l'acceptation de ces valeurs et la structure du flux SSE résultant.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import httpx
import pytest

from configs import HOST_ADDRESS, HTTP_TIMEOUT, VERSION
from libs.contract import assert_valid
from libs.sse import stream_completions
from schemas.completions import ANSWER_DATA_SCHEMA, ENVELOPE_SCHEMA

QUESTION = "Qu'est-ce que RAGFlow ?"


def _stream_with_reasoning(token, chat_id, reasoning):
    """Crée une session, streame une complétion avec le niveau demandé, nettoie."""
    with httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        r = client.post(f"/api/{VERSION}/chats/{chat_id}/sessions", json={"name": f"reasoning-{reasoning}"})
        session_id = r.json()["data"]["id"]
        try:
            frames = stream_completions(client, chat_id, QUESTION, session_id, reasoning=reasoning)
        finally:
            client.request("DELETE", f"/api/{VERSION}/chats/{chat_id}/sessions", json={"ids": [session_id]})
    return frames, session_id


def _assert_stream_contract(frames, session_id):
    """Enveloppe valide sur chaque frame, sentinelle terminale unique, réponses conformes."""
    assert len(frames) >= 2, f"flux trop court : {frames}"
    for i, frame in enumerate(frames):
        assert_valid(frame, ENVELOPE_SCHEMA, label=f"frame[{i}]")
        assert frame["code"] == 0, f"frame[{i}] code={frame['code']}"
    terminals = [f for f in frames if f.get("data") is True]
    assert len(terminals) == 1, f"attendu 1 sentinelle terminale, trouvé {len(terminals)}"
    assert frames[-1]["data"] is True, "la sentinelle n'est pas la dernière frame"
    answers = [f for f in frames if isinstance(f.get("data"), dict)]
    assert answers, "aucune frame de réponse (data objet)"
    for i, frame in enumerate(answers):
        assert_valid(frame["data"], ANSWER_DATA_SCHEMA, label=f"answer_frame[{i}]")
        assert frame["data"]["session_id"] == session_id


@pytest.mark.p0
def test_reasoning_zero_forces_naive_chat(token, ref_chat_id):
    """`reasoning="0"` (naive) est accepté et suit le contrat SSE du chat classique."""
    frames, session_id = _stream_with_reasoning(token, ref_chat_id, "0")
    _assert_stream_contract(frames, session_id)


@pytest.mark.p0
def test_reasoning_level_low_streams_valid_contract(token, ref_chat_id):
    """`reasoning="1"` (low) déclenche l'advanced RAG sans casser le contrat SSE."""
    frames, session_id = _stream_with_reasoning(token, ref_chat_id, "1")
    _assert_stream_contract(frames, session_id)
