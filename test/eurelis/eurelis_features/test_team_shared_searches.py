# Eurelis — P1 : partage d'équipe des Search apps (search_service + search_api).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Évolution symétrique au partage des chats : le listing des search calcule joined_tenant_ids
# via get_joined_tenants_by_user_id et filtre (tenant_id IN joined AND permission='team')
# OR (tenant_id == user_id), de sorte qu'un membre voit les search permission=team du tenant.
#
# Cette fonctionnalité de partage est CONSOMMÉE PAR LE SHIELD : une régression (retour au
# `tenants = []` d'origine, ou perte du champ `permission`) casserait la visibilité côté Shield.
#
# Scénario : A invite B dans son tenant → B accepte → A crée un search `team` et un search `me`
# → B doit voir le `team` (avec permission='team') et NE PAS voir le `me`.

import httpx
import pytest

from configs import (
    HOST_ADDRESS,
    HTTP_TIMEOUT,
    TEAMMATE_EMAIL,
    TEAMMATE_NICKNAME,
    VERSION,
)
from libs.contract import assert_valid
from libs.ragflow_api import get_api_token, get_own_tenant_id, login, register_user
from schemas.searches import SEARCH_APP_SCHEMA

TEAM_SEARCH_NAME = "eurelis-team-search"
PRIVATE_SEARCH_NAME = "eurelis-private-search"


def _client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    )


def _list_searches(client: httpx.Client) -> list:
    data = client.get(f"/api/{VERSION}/searches").json().get("data") or {}
    return data.get("search_apps") or []


def _ensure_search(client: httpx.Client, name: str, permission: str) -> str:
    """Retrouve (idempotent) ou crée un search `name` avec la permission donnée ; renvoie son id."""
    existing = next((s for s in _list_searches(client) if s["name"] == name), None)
    if existing:
        return existing["id"]
    r = client.post(
        f"/api/{VERSION}/searches",
        json={"name": name, "permission": permission},
    ).json()
    assert r.get("code") == 0, r
    return r["data"]["search_id"]


@pytest.fixture(scope="module")
def team_setup(token):
    """A invite B, B accepte, A crée un search `team` et un search `me`. Nettoie en fin de module."""
    a = _client(token)
    a_tid = get_own_tenant_id(HOST_ADDRESS, f"Bearer {token}")

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

    team_search_id = _ensure_search(a, TEAM_SEARCH_NAME, "team")
    private_search_id = _ensure_search(a, PRIVATE_SEARCH_NAME, "me")

    yield {
        "a": a,
        "b": b,
        "a_tid": a_tid,
        "b_tid": b_tid,
        "team_search_id": team_search_id,
        "private_search_id": private_search_id,
    }

    a.request("DELETE", f"/api/{VERSION}/searches/{team_search_id}")
    a.request("DELETE", f"/api/{VERSION}/searches/{private_search_id}")
    a.request("DELETE", f"/api/{VERSION}/tenants/{a_tid}/users", json={"user_id": b_tid})
    a.close()
    b.close()


@pytest.mark.p1
def test_teammate_sees_team_search(team_setup):
    """Le coéquipier voit le search partagé (permission=team) — cœur de la fonctionnalité."""
    searches = _list_searches(team_setup["b"])
    match = next((s for s in searches if s["id"] == team_setup["team_search_id"]), None)
    assert match is not None, "le coéquipier ne voit pas le search partagé (permission=team)"
    assert match.get("permission") == "team"


@pytest.mark.p1
def test_teammate_does_not_see_private_search(team_setup):
    """Contrôle : le coéquipier ne voit PAS les search privés (permission=me) de A."""
    ids = {s["id"] for s in _list_searches(team_setup["b"])}
    assert team_setup["private_search_id"] not in ids, (
        "fuite : un search privé (permission=me) est visible par le coéquipier"
    )


@pytest.mark.p1
def test_owner_sees_both_searches(team_setup):
    """Le propriétaire voit ses deux search (team + me), indépendamment de la permission."""
    ids = {s["id"] for s in _list_searches(team_setup["a"])}
    assert team_setup["team_search_id"] in ids
    assert team_setup["private_search_id"] in ids


@pytest.mark.p1
def test_search_app_contract(team_setup):
    """Contrat de l'objet search app renvoyé au Shield (id/name/tenant_id/permission)."""
    match = next(
        s for s in _list_searches(team_setup["a"]) if s["id"] == team_setup["team_search_id"]
    )
    assert_valid(match, SEARCH_APP_SCHEMA, label="GET /searches → search_apps[]")
