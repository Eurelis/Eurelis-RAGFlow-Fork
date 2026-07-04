# Eurelis — contrat P0 de l'endpoint Admin de création d'utilisateur consommé par le Shield.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Le Shield auto-provisionne les comptes via POST /api/v1/admin/users (le chemin OIDC/Keycloak,
# lui, ne valide pas l'email : il vient d'une claim de token). Deux invariants sont figés :
#
#   A. Un email avec plus-addressing (partie locale contenant « + », ex. alice+tag@example.com) —
#      valide au sens RFC 5321 — DOIT être accepté (200 / code 0), pas rejeté en 400
#      « Invalid email address ». Régression historique : la classe de caractères de la validation
#      côté admin (admin/server/services.py, UserMgr.create_user) omettait le « + ».
#   B. Un email réellement invalide (sans « @ »/domaine) DOIT toujours être rejeté en 400 avec le
#      message « Invalid email address » — la validation n'est pas simplement désactivée.
#
# NB : le champ password est chiffré RSA côté client (crypt(), même mécanisme que le login admin) ;
# la route le retire de la réponse — l'absence de `password` fait partie du contrat.

import pytest

from configs import VERSION
from libs.contract import assert_valid
from schemas.admin import ADMIN_CREATED_USER_SCHEMA, ADMIN_ENVELOPE_SCHEMA

# Email de test avec plus-addressing (partie locale = « qa+shield »). Fixe → nettoyable/rejouable.
PLUS_EMAIL = "qa+shield@eurelis.test"
# Email volontairement invalide (ni « @ » ni domaine) → doit rester refusé.
INVALID_EMAIL = "not-an-email"


def _encrypted_password(plain: str = "Pw-Contract-123") -> str:
    """Mot de passe chiffré RSA (clé publique RAGFlow), comme l'envoie le client admin/Shield."""
    from api.utils.crypt import crypt  # import tardif : dépend de la clé publique RAGFlow

    return crypt(plain)


def _delete_user(admin, email: str) -> None:
    """Supprime un utilisateur par email (idempotent : ignore l'absence).

    L'endpoint DELETE refuse un compte ACTIF (« is active and can't be deleted ») ; on le
    désactive donc d'abord (activate_status=off), best-effort, avant la suppression.
    """
    admin.put(f"/api/{VERSION}/admin/users/{email}/activate", json={"activate_status": "off"})
    admin.request("DELETE", f"/api/{VERSION}/admin/users/{email}")


@pytest.mark.p0
def test_admin_create_user_accepts_plus_addressing(admin):
    """A. Un email avec « + » dans la partie locale est accepté (200 / code 0), password non renvoyé."""
    _delete_user(admin, PLUS_EMAIL)  # état de départ propre (exécution antérieure)
    try:
        r = admin.post(
            f"/api/{VERSION}/admin/users",
            json={"username": PLUS_EMAIL, "password": _encrypted_password(), "role": "user"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["code"] == 0, body
        # Le « + » ne doit JAMAIS déclencher le rejet de validation d'email.
        assert "Invalid email address" not in (body.get("message") or ""), body
        assert_valid(body["data"], ADMIN_CREATED_USER_SCHEMA, label="admin created user")
        assert body["data"]["email"] == PLUS_EMAIL, body
    finally:
        _delete_user(admin, PLUS_EMAIL)  # nettoyage obligatoire (test rejouable)


@pytest.mark.p0
def test_admin_create_user_rejects_invalid_email(admin):
    """B. Un email réellement invalide reste rejeté en 400 « Invalid email address »."""
    r = admin.post(
        f"/api/{VERSION}/admin/users",
        json={"username": INVALID_EMAIL, "password": _encrypted_password(), "role": "user"},
    )
    assert r.status_code == 400, r.text
    assert_valid(r.json(), ADMIN_ENVELOPE_SCHEMA, label="admin invalid-email envelope")
    body = r.json()
    assert body["code"] != 0, body
    assert "Invalid email address" in (body.get("message") or ""), body
