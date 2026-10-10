# Eurelis — P0 : contrat des sessions d'agent consommées par le Shield (031, T007).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Le Shield crée chaque exécution par POST /sessions (release=true, user_id=<owner Shield>) : session
# vierge (path=[]) sur la version publiée. Il cloisonne lui-même les sessions par user_id (RAGFlow ne
# filtre que par agent) : le filtre `user_id` de la liste doit donc rester opérant.

import pytest

from configs import VERSION
from libs.agents import ok, session_dsl
from libs.contract import assert_valid
from schemas.agents import SESSION_CREATED_SCHEMA, SESSION_DETAIL_SCHEMA, SESSION_LIST_ITEM_SCHEMA

OWNER_A = "contract-owner-a"
OWNER_B = "contract-owner-b"


@pytest.mark.p0
def test_session_lifecycle_and_user_filter(agent_member, contract_agent_id):
    base = f"/api/{VERSION}/agents/{contract_agent_id}/sessions"
    created = ok(agent_member.post(base, json={"release": True, "user_id": OWNER_A, "name": "contract-a"}))["data"]
    assert_valid(created, SESSION_CREATED_SCHEMA, label="session created")
    assert session_dsl(created)["path"] == [], "session créée non vierge"
    other = ok(agent_member.post(base, json={"release": True, "user_id": OWNER_B, "name": "contract-b"}))["data"]
    try:
        listed = ok(agent_member.get(base, params={"user_id": OWNER_A, "dsl": "false", "page_size": 100}))["data"]
        for i, s in enumerate(listed):
            assert_valid(s, SESSION_LIST_ITEM_SCHEMA, label=f"session[{i}]")
        ids = {s["id"] for s in listed}
        assert created["id"] in ids and other["id"] not in ids, "le filtre user_id ne cloisonne plus les sessions"

        detail = ok(agent_member.get(f"{base}/{created['id']}"))["data"]
        assert_valid(detail, SESSION_DETAIL_SCHEMA, label="session detail")
        assert detail["dialog_id"] == contract_agent_id and detail["user_id"] == OWNER_A
    finally:
        for sid in (created["id"], other["id"]):
            ok(agent_member.delete(f"{base}/{sid}"))
    gone = agent_member.get(f"{base}/{created['id']}").json()
    assert gone.get("code") != 0, "session toujours lisible après suppression"


@pytest.mark.p0
def test_release_session_requires_published_version(agent_member, contract_agent_id):
    """Créer une session release=true sur un agent publié réussit (le Shield traduit l'échec en 404)."""
    base = f"/api/{VERSION}/agents/{contract_agent_id}/sessions"
    sid = ok(agent_member.post(base, json={"release": True, "user_id": OWNER_A}))["data"]["id"]
    ok(agent_member.delete(f"{base}/{sid}"))
