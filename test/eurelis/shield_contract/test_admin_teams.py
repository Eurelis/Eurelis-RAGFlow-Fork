# Eurelis — contrat P0 des endpoints Admin (team enrollment) consommés par le Shield (default teams).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Le Shield rattache un utilisateur fraîchement provisionné à des équipes par défaut. Il consomme :
#   - GET  /api/v1/admin/users/{email}                → résout l'id (hex) d'un utilisateur
#   - POST /api/v1/admin/tenants/{tenant_id}/users    → ajoute le membre (tenant_id == id du proprio)
# Dépendance de contrat particulière : le Shield fait du matching de SOUS-CHAÎNE sur `message`
# ("already" à l'ajout d'un membre déjà présent) — figé ici par assertion inline, car un changement
# de formulation upstream casserait silencieusement l'idempotence côté Shield.
#
# NB (vérifié empiriquement) : GET /admin/users/{email} renvoie data = LISTE, et un utilisateur
# INEXISTANT donne 200 / code 0 / data == [] (jamais 400, jamais "not found"). Le signal
# « introuvable » du Shield est donc la liste vide — c'est ce qui est figé au scénario B.
#
# Scénarios figés :
#   A. résolution d'id (succès)                     — data = liste d'objets {id}
#   B. résolution d'id (inexistant)                 — 200 / code 0 / data == []
#   C. ajout d'un membre (succès)                   — 200 / code 0 / enregistrement {id,user_id,role,status}
#   D. ré-ajout d'un membre ACTIF                   — 400 + sous-chaîne "already" (idempotence Shield)
#   E. ré-enrôlement après SUPPRESSION              — 200 (le Shield re-provisionne un membre retiré)
#   F. ajout d'un user INEXISTANT                   — 400 (validation d'existence ; refus du membre fantôme)
#   G. ajout à une équipe INEXISTANTE               — 400 (validation d'existence du tenant)

import pytest

from configs import EMAIL, HOST_ADDRESS, TEAMMATE_EMAIL, TEAMMATE_NICKNAME, VERSION
from libs.contract import assert_valid
from libs.ragflow_api import register_user
from schemas.admin import (
    ADMIN_ENVELOPE_SCHEMA,
    ADMIN_MEMBER_RECORD_SCHEMA,
    ADMIN_USER_LIST_SCHEMA,
)


def _resolve_user_id(admin, email: str) -> str | None:
    """id (hex) d'un utilisateur via l'admin, ou None si absent (data == [])."""
    r = admin.get(f"/api/{VERSION}/admin/users/{email}")
    assert r.status_code == 200, r.text
    data = r.json().get("data") or []
    return data[0]["id"] if data else None


@pytest.mark.p0
def test_admin_user_resolution_success(admin):
    """A. Résolution d'id (succès) : data = liste d'objets {id} — le Shield lit l'id du 1er élément."""
    r = admin.get(f"/api/{VERSION}/admin/users/{EMAIL}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["code"] == 0, body
    assert_valid(body["data"], ADMIN_USER_LIST_SCHEMA, label="admin user list")
    assert body["data"], "l'utilisateur de test doit être présent"


@pytest.mark.p0
def test_admin_user_resolution_not_found(admin):
    """B. Résolution d'id (inexistant) : 200 / code 0 / data == [] — signal « introuvable » du Shield."""
    r = admin.get(f"/api/{VERSION}/admin/users/no-such-user@nowhere.test")
    assert r.status_code == 200, r.text
    assert_valid(r.json(), ADMIN_ENVELOPE_SCHEMA, label="admin user not found envelope")
    body = r.json()
    assert body["code"] == 0, body
    assert body["data"] == [], body


@pytest.mark.p0
def test_admin_team_enrollment_and_idempotence(admin):
    """C+D. Ajout d'un membre (owner=tenant), puis ré-ajout idempotent (400 + 'already'). Auto-nettoyé."""
    register_user(HOST_ADDRESS, email=TEAMMATE_EMAIL, nickname=TEAMMATE_NICKNAME)
    owner_id = _resolve_user_id(admin, EMAIL)
    member_id = _resolve_user_id(admin, TEAMMATE_EMAIL)
    assert owner_id and member_id, "owner et membre doivent exister"

    base = f"/api/{VERSION}/admin/tenants/{owner_id}/users"
    # Nettoyage préalable : le membre ne doit pas déjà appartenir à l'équipe (exécution antérieure).
    admin.request("DELETE", f"{base}/{member_id}")
    try:
        # C. ajout (succès) — fige la forme de l'enregistrement d'appartenance
        r = admin.post(base, json={"user_id": member_id, "role": "normal"})
        assert r.status_code == 200 and r.json()["code"] == 0, r.text
        assert_valid(r.json()["data"], ADMIN_MEMBER_RECORD_SCHEMA, label="admin member record")

        # D. ré-ajout (déjà membre) — fige le signal 'already'
        r = admin.post(base, json={"user_id": member_id, "role": "normal"})
        assert r.status_code == 400, r.text
        assert_valid(r.json(), ADMIN_ENVELOPE_SCHEMA, label="admin already-member envelope")
        assert "already" in r.json()["message"].lower(), r.text
    finally:
        # Nettoyage obligatoire (test rejouable) : retire le membre de l'équipe.
        r = admin.request("DELETE", f"{base}/{member_id}")
        assert r.status_code == 200, r.text


@pytest.mark.p0
def test_admin_team_reenrollment_after_removal(admin):
    """E. Ré-enrôlement : ajouter -> retirer -> ré-ajouter DOIT réussir (200).

    La suppression est un soft-delete (status=INVALID) ; le Shield re-provisionne un membre
    précédemment retiré et attend un succès, pas un 400 « already ». On fige donc que le
    ré-ajout après suppression renvoie l'enregistrement d'appartenance (réactivé), sans erreur.
    """
    register_user(HOST_ADDRESS, email=TEAMMATE_EMAIL, nickname=TEAMMATE_NICKNAME)
    owner_id = _resolve_user_id(admin, EMAIL)
    member_id = _resolve_user_id(admin, TEAMMATE_EMAIL)
    assert owner_id and member_id, "owner et membre doivent exister"

    base = f"/api/{VERSION}/admin/tenants/{owner_id}/users"
    admin.request("DELETE", f"{base}/{member_id}")  # état de départ propre
    try:
        # 1er ajout
        r = admin.post(base, json={"user_id": member_id, "role": "normal"})
        assert r.status_code == 200 and r.json()["code"] == 0, r.text
        # suppression (soft-delete)
        r = admin.request("DELETE", f"{base}/{member_id}")
        assert r.status_code == 200, r.text
        # ré-ajout après suppression : DOIT réussir (réactivation, pas de doublon ni 400)
        r = admin.post(base, json={"user_id": member_id, "role": "admin"})
        assert r.status_code == 200 and r.json()["code"] == 0, r.text
        assert_valid(r.json()["data"], ADMIN_MEMBER_RECORD_SCHEMA, label="admin reenrolled record")
    finally:
        r = admin.request("DELETE", f"{base}/{member_id}")
        assert r.status_code == 200, r.text


@pytest.mark.p0
def test_admin_team_add_rejects_unknown_user(admin):
    """F. Ajout d'un user inexistant → 400 (validation d'existence, refus du membre fantôme)."""
    owner_id = _resolve_user_id(admin, EMAIL)
    assert owner_id, "owner doit exister"
    base = f"/api/{VERSION}/admin/tenants/{owner_id}/users"
    r = admin.post(base, json={"user_id": "does-not-exist-000000000000", "role": "normal"})
    assert r.status_code == 400, r.text
    assert_valid(r.json(), ADMIN_ENVELOPE_SCHEMA, label="admin unknown-user envelope")
    assert r.json()["code"] != 0, r.text


@pytest.mark.p0
def test_admin_team_add_rejects_unknown_tenant(admin):
    """G. Ajout à une équipe inexistante → 400 (validation d'existence du tenant).

    On fournit un user_id RÉEL (l'owner) pour isoler l'échec sur le tenant, pas sur le user.
    """
    owner_id = _resolve_user_id(admin, EMAIL)
    assert owner_id, "owner doit exister"
    base = f"/api/{VERSION}/admin/tenants/does-not-exist-000000000000/users"
    r = admin.post(base, json={"user_id": owner_id, "role": "normal"})
    assert r.status_code == 400, r.text
    assert_valid(r.json(), ADMIN_ENVELOPE_SCHEMA, label="admin unknown-tenant envelope")
    assert r.json()["code"] != 0, r.text
