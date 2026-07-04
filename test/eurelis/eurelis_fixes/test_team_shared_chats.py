# Eurelis — P1 : correctif « chats partagés en équipe absents de la liste » (dialog_service).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Correctif : le listing des chats calcule joined_tenant_ids via get_joined_tenants_by_user_id,
# de sorte qu'un membre d'un tenant voit les chats permission=team de ce tenant.
# Scénario : A invite B dans son tenant → B accepte → A crée un chat `team` → B doit le voir
# (et NE doit PAS voir les chats privés `me` de A).

import httpx
import pytest

from configs import (
    HOST_ADDRESS,
    HTTP_TIMEOUT,
    REF_DATASET_NAME,
    TEAMMATE_EMAIL,
    TEAMMATE_NICKNAME,
    VERSION,
)
from libs.ragflow_api import get_api_token, get_own_tenant_id, login, register_user

TEAM_CHAT_NAME = "eurelis-team-chat"


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    )


def _list_chats(client: httpx.Client) -> list:
    return (client.get(f"/api/{VERSION}/chats").json().get("data") or {}).get("chats") or []


@pytest.fixture(scope="module")
def team_setup(token):
    """A invite B dans son tenant, B accepte, A crée un chat `team`. Nettoie en fin de module."""
    a = _client(token)
    a_tid = get_own_tenant_id(HOST_ADDRESS, f"Bearer {token}")

    datasets = a.get(f"/api/{VERSION}/datasets", params={"name": REF_DATASET_NAME}).json()["data"]
    assert datasets, "dataset de référence introuvable"
    dataset_id = datasets[0]["id"]

    # Utilisateur B
    register_user(HOST_ADDRESS, email=TEAMMATE_EMAIL, nickname=TEAMMATE_NICKNAME)
    b_token = get_api_token(HOST_ADDRESS, login(HOST_ADDRESS, email=TEAMMATE_EMAIL))
    b = _client(b_token)
    b_tid = get_own_tenant_id(HOST_ADDRESS, f"Bearer {b_token}")

    # A invite B (idempotent), B accepte
    inv = a.post(f"/api/{VERSION}/tenants/{a_tid}/users", json={"email": TEAMMATE_EMAIL}).json()
    assert inv.get("code") == 0 or "already" in (inv.get("message") or "").lower(), inv
    acc = b.patch(f"/api/{VERSION}/tenants/{a_tid}").json()
    assert acc.get("code") == 0, acc

    # A crée (ou retrouve) un chat partagé équipe
    existing = [c for c in _list_chats(a) if c["name"] == TEAM_CHAT_NAME]
    if existing:
        team_chat_id = existing[0]["id"]
    else:
        r = a.post(
            f"/api/{VERSION}/chats",
            json={"name": TEAM_CHAT_NAME, "dataset_ids": [dataset_id], "permission": "team"},
        ).json()
        assert r.get("code") == 0, r
        team_chat_id = r["data"]["id"]

    yield {"a": a, "b": b, "a_tid": a_tid, "b_tid": b_tid, "team_chat_id": team_chat_id}

    a.request("DELETE", f"/api/{VERSION}/chats", json={"ids": [team_chat_id]})
    a.request("DELETE", f"/api/{VERSION}/tenants/{a_tid}/users", json={"user_id": b_tid})
    a.close()
    b.close()


@pytest.mark.p1
def test_teammate_sees_team_chat(team_setup):
    """Le coéquipier voit le chat partagé (permission=team) — cœur du correctif."""
    chats = _list_chats(team_setup["b"])
    match = next((c for c in chats if c["id"] == team_setup["team_chat_id"]), None)
    assert match is not None, "le coéquipier ne voit pas le chat partagé (permission=team)"
    assert match.get("permission") == "team"


@pytest.mark.p1
def test_teammate_does_not_see_private_chat(team_setup, ref_chat_id):
    """Contrôle : le coéquipier ne voit PAS les chats privés (permission=me) de A."""
    ids = {c["id"] for c in _list_chats(team_setup["b"])}
    assert ref_chat_id not in ids, "fuite : un chat privé (permission=me) est visible par le coéquipier"
