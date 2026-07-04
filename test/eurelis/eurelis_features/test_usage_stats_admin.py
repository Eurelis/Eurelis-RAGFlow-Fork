# Eurelis — P1 : statistiques de consommation côté admin (serveur Flask :9381). Feature Eurelis.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import httpx
import pytest

from configs import ADMIN_ADDRESS, EMAIL, HTTP_TIMEOUT, VERSION
from libs.contract import assert_valid
from schemas.admin_supervision import ADMIN_USERS_SCHEMA
from schemas.usage_stats import SOURCES_SCHEMA

BASE = f"/api/{VERSION}/admin/stats"


@pytest.mark.p1
def test_admin_stats_requires_auth():
    """Sans JWT admin, l'endpoint stats refuse l'accès (contrôle d'accès admin)."""
    with httpx.Client(base_url=ADMIN_ADDRESS, timeout=HTTP_TIMEOUT) as anon:
        r = anon.get(f"{BASE}/sources")
    assert r.status_code in (401, 403) or r.json().get("code") not in (0, None), r.text


@pytest.mark.p1
def test_admin_stats_sources(admin):
    r = admin.get(f"{BASE}/sources")
    assert r.status_code == 200, r.text
    assert_valid(r.json()["data"], SOURCES_SCHEMA, label="admin sources")


@pytest.mark.p1
def test_admin_stats_users(admin):
    """La liste des users agrège la consommation ; l'utilisateur de test y figure avec des tokens."""
    r = admin.get(f"{BASE}/users")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert_valid(data, ADMIN_USERS_SCHEMA, label="admin users")
    me = next((u for u in data["users"] if u["email"] == EMAIL), None)
    assert me is not None, f"{EMAIL} absent des stats admin"
    assert me["tokens"] > 0, "aucun token comptabilisé pour l'utilisateur de test"
