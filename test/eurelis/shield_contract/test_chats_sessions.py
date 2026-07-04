# Eurelis — contrat P0 des endpoints Chat / Session / version consommés par le Shield.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import pytest

from configs import REF_CHAT_NAME, VERSION
from libs.contract import assert_valid
from schemas.chats import CHAT_SCHEMA, MESSAGE_SCHEMA, SESSION_SCHEMA
from schemas.system import SYSTEM_VERSION_ENVELOPE_SCHEMA


@pytest.mark.p0
def test_system_version(api):
    """GET /system/version : enveloppe {code,message,data} figée — le Shield lit
    code, data (version) et message (diagnostic d'erreur)."""
    r = api.get(f"/api/{VERSION}/system/version")
    assert r.status_code == 200, r.text
    body = r.json()
    assert_valid(body, SYSTEM_VERSION_ENVELOPE_SCHEMA, label="system/version")
    assert body["code"] == 0, body


@pytest.mark.p0
def test_list_chats_contract(api):
    """GET /chats : data.chats[] conforme au contrat d'agent du Shield."""
    r = api.get(f"/api/{VERSION}/chats")
    assert r.status_code == 200, r.text
    chats = (r.json().get("data") or {}).get("chats")
    assert isinstance(chats, list) and chats, "data.chats attendu (liste non vide)"
    for i, chat in enumerate(chats):
        assert_valid(chat, CHAT_SCHEMA, label=f"chat[{i}]")


@pytest.mark.p0
def test_get_chat_by_id_contract(api, ref_chat_id):
    """GET /chats?id= : renvoie l'agent ciblé, conforme au contrat."""
    r = api.get(f"/api/{VERSION}/chats", params={"id": ref_chat_id})
    assert r.status_code == 200, r.text
    chats = (r.json().get("data") or {}).get("chats") or []
    match = [c for c in chats if c["id"] == ref_chat_id]
    assert match, f"chat {ref_chat_id} introuvable"
    assert_valid(match[0], CHAT_SCHEMA, label="chat")
    assert match[0]["name"] == REF_CHAT_NAME


@pytest.mark.p0
def test_session_lifecycle_contract(api, ref_chat_id):
    """Cycle de vie session : create → list → history → rename → delete, chaque forme conforme."""
    base = f"/api/{VERSION}/chats/{ref_chat_id}/sessions"

    # create
    r = api.post(base, json={"name": "lifecycle"})
    assert r.status_code == 200 and r.json().get("code") == 0, r.text
    session = r.json()["data"]
    assert_valid(session, SESSION_SCHEMA, label="session (create)")
    sid = session["id"]
    assert session["chat_id"] == ref_chat_id

    try:
        # list — data est une LISTE de sessions (forme propre à cet endpoint)
        r = api.get(base)
        sessions = r.json().get("data")
        assert isinstance(sessions, list), f"data attendu liste, reçu {type(sessions).__name__}"
        for i, s in enumerate(sessions):
            assert_valid(s, SESSION_SCHEMA, label=f"session[{i}]")
        assert any(s["id"] == sid for s in sessions), "session créée absente de la liste"

        # history — messages conformes
        r = api.get(f"{base}/{sid}")
        hist = r.json().get("data")
        # /{sid} peut renvoyer l'objet ou une liste à un élément
        hist = hist[0] if isinstance(hist, list) else hist
        assert_valid(hist, SESSION_SCHEMA, label="session (history)")
        for i, m in enumerate(hist.get("messages") or []):
            assert_valid(m, MESSAGE_SCHEMA, label=f"message[{i}]")

        # rename
        r = api.patch(f"{base}/{sid}", json={"name": "renamed"})
        assert r.status_code == 200 and r.json().get("code") == 0, r.text
    finally:
        # delete
        r = api.request("DELETE", base, json={"ids": [sid]})
        assert r.status_code == 200 and r.json().get("code") == 0, r.text
