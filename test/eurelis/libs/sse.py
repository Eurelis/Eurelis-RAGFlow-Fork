# Eurelis — parseur du flux SSE des complétions RAGFlow (frames `data:{...}`).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import json

import httpx

from configs import VERSION


def stream_completions(client: httpx.Client, chat_id: str, question: str, session_id: str, **extra) -> list:
    """
    Poste une complétion en streaming et renvoie la liste des frames SSE décodées (JSON).
    Chaque frame est le dict issu d'une ligne `data:{...}`.
    """
    payload = {"question": question, "stream": True, "session_id": session_id}
    payload.update(extra)
    frames = []
    with client.stream("POST", f"/api/{VERSION}/chats/{chat_id}/completions", json=payload) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line or not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            try:
                frames.append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return frames
