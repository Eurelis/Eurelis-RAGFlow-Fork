# Eurelis — helpers des tests de contrat Agent (canvas) consommés par le Shield (feature 031).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Agent de contrat SANS LLM (fixtures/agent_contract_canvas.json) :
#   Begin (sujet:line, regime:options, document:file facultatif) → Message:Intro
#   → UserFillUp:Valid (retour:paragraph, tips Markdown) → Message:Final (output_format markdown)
# Il est créé chez l'utilisateur de test A, PUBLIÉ et partagé `team` ; l'utilisateur B (membre de
# l'équipe de A) l'exécute avec SA clé — exactement le schéma d'usage du Shield.

import json
from pathlib import Path

import httpx

from configs import ADMIN_ADDRESS, HOST_ADDRESS, HTTP_TIMEOUT, TEAMMATE_EMAIL, TEAMMATE_NICKNAME, VERSION
from libs.ragflow_api import get_api_token, get_own_tenant_id, login, register_user

CONTRACT_AGENT_TITLE = "eurelis-contract-agent"
CANVAS_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_contract_canvas.json"


def client(token: str) -> httpx.Client:
    return httpx.Client(base_url=HOST_ADDRESS, headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT)


def ok(resp: httpx.Response) -> dict:
    body = resp.json()
    assert resp.status_code == 200 and body.get("code") == 0, f"{resp.request.method} {resp.request.url}: {body}"
    return body


def ensure_contract_agent(owner: httpx.Client) -> str:
    """Crée ou remet à jour (idempotent) l'agent de contrat, publié et partagé `team` ; renvoie son id."""
    dsl = json.loads(CANVAS_FILE.read_text())
    listed = ok(owner.get(f"/api/{VERSION}/agents", params={"keywords": CONTRACT_AGENT_TITLE, "page_size": 0}))
    existing = next((a for a in listed["data"]["canvas"] if a["title"] == CONTRACT_AGENT_TITLE), None)
    body = {"dsl": dsl, "title": CONTRACT_AGENT_TITLE, "permission": "team", "release": True}
    if existing:
        ok(owner.put(f"/api/{VERSION}/agents/{existing['id']}", json=body))
        return existing["id"]
    created = ok(owner.post(f"/api/{VERSION}/agents", json={**body, "canvas_category": "agent_canvas",
                                                            "description": "Agent de contrat Shield (031)"}))
    return created["data"]["id"]


def team_member_token(owner_token: str, admin_token: str) -> str:
    """Rend B membre actif (`normal`) de l'équipe de A via l'API admin ; renvoie la clé d'API de B.

    Pas d'invitation côté utilisateur : test_admin_teams laisse B en soft-delete (status invalide,
    rôle `admin`) dans l'équipe de A, et l'invitation refuse alors B (« is in the team, but the role:
    admin is invalid ») sans le réactiver. L'ajout admin réactive l'appartenance (cf.
    test_admin_team_reenrollment_after_removal) et ne demande pas d'acceptation.
    """
    a_tid = get_own_tenant_id(HOST_ADDRESS, f"Bearer {owner_token}")
    register_user(HOST_ADDRESS, email=TEAMMATE_EMAIL, nickname=TEAMMATE_NICKNAME)
    b_token = get_api_token(HOST_ADDRESS, login(HOST_ADDRESS, email=TEAMMATE_EMAIL))
    with httpx.Client(base_url=ADMIN_ADDRESS, headers={"Authorization": admin_token}, timeout=HTTP_TIMEOUT) as admin:
        r = admin.get(f"/api/{VERSION}/admin/users/{TEAMMATE_EMAIL}")
        assert r.status_code == 200 and r.json().get("data"), r.text
        b_id = r.json()["data"][0]["id"]
        base = f"/api/{VERSION}/admin/tenants/{a_tid}/users"
        admin.request("DELETE", f"{base}/{b_id}")  # état de départ propre (no-op si B absent)
        r = admin.post(base, json={"user_id": b_id, "role": "normal"})
        assert r.status_code == 200 and r.json().get("code") == 0, r.text
    return b_token


def stream_agent(c: httpx.Client, body: dict) -> list:
    """POST /agents/chat/completions en streaming ; renvoie les frames décodées (dicts, ou "[DONE]")."""
    frames = []
    with c.stream("POST", f"/api/{VERSION}/agents/chat/completions", json={"stream": True, **body},
                  timeout=httpx.Timeout(HTTP_TIMEOUT, read=None)) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data:"):
                continue
            raw = line[len("data:"):].strip()
            if raw == "[DONE]":
                frames.append("[DONE]")
                continue
            frames.append(json.loads(raw))
    return frames


def events(frames: list) -> list:
    return [f["event"] if isinstance(f, dict) and "event" in f else f for f in frames]


def session_dsl(session: dict) -> dict:
    dsl = session["dsl"]
    return json.loads(dsl) if isinstance(dsl, str) else dsl
