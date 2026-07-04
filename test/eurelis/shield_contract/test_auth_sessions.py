# Eurelis — contrat P0 des sessions interactives (login JWT) consommées par le Shield.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Deux garanties observables dont dépend le Shield quand il ouvre des sessions JWT (API :9380 et
# serveur admin :9381) :
#   1. Multi-appareils : un nouveau login NE révoque PAS un token déjà émis pour le même compte.
#      (Avant le fork : rotation systématique de l'access_token à chaque login → la 1re session
#      était éjectée. Régression silencieuse pour tout client qui garde plusieurs sessions.)
#   2. TTL 12 h : un JWT plus vieux que 12 h est refusé (401), ce qui force une reconnexion
#      périodique. Le test forge un token expiré signé avec le secret RÉEL du serveur ; il se
#      SKIP proprement si ce secret n'est pas récupérable/concordant côté hôte (ex. image distante).

import httpx
import pytest
from itsdangerous.url_safe import URLSafeTimedSerializer as Serializer

from configs import ADMIN_ADDRESS, EMAIL, HOST_ADDRESS, HTTP_TIMEOUT, VERSION
from libs.ragflow_api import admin_login, login, register_user

# Endpoint authentifié léger et sans effet de bord : 200 si le token est valide, 401 sinon.
_PROBE = f"/api/{VERSION}/users/me/models"
_ADMIN_PROBE = f"/api/{VERSION}/admin/users/{EMAIL}"


def _auth_status(base: str, path: str, token: str) -> int:
    r = httpx.get(f"{base}{path}", headers={"Authorization": token}, timeout=HTTP_TIMEOUT)
    return r.status_code


@pytest.mark.p0
def test_relogin_keeps_previous_token_valid():
    """API :9380 — un 2e login (même compte) n'invalide pas le token du 1er login (multi-appareils)."""
    register_user(HOST_ADDRESS)
    tok_a = login(HOST_ADDRESS)
    assert _auth_status(HOST_ADDRESS, _PROBE, tok_a) == 200, "le 1er token devrait être valide après login"

    tok_b = login(HOST_ADDRESS)  # 2e appareil / 2e session, même compte
    assert _auth_status(HOST_ADDRESS, _PROBE, tok_b) == 200, "le 2e token devrait être valide"
    assert _auth_status(HOST_ADDRESS, _PROBE, tok_a) == 200, (
        "régression multi-session : le 1er token a été invalidé par le 2e login "
        "(rotation de l'access_token) — les sessions ne coexistent plus"
    )


@pytest.mark.p0
def test_admin_relogin_keeps_previous_token_valid():
    """Admin :9381 — même garantie multi-session (le Shield consomme des endpoints admin)."""
    tok_a = admin_login(ADMIN_ADDRESS)
    assert _auth_status(ADMIN_ADDRESS, _ADMIN_PROBE, tok_a) == 200, "le 1er token admin devrait être valide"

    tok_b = admin_login(ADMIN_ADDRESS)
    assert _auth_status(ADMIN_ADDRESS, _ADMIN_PROBE, tok_b) == 200, "le 2e token admin devrait être valide"
    assert _auth_status(ADMIN_ADDRESS, _ADMIN_PROBE, tok_a) == 200, (
        "régression multi-session admin : le 1er token admin a été évincé par le 2e login"
    )


@pytest.fixture(scope="session")
def server_serializer():
    """Sérialiseur signé avec le secret RÉEL du serveur (même dérivation que get_secret_key).

    Skip si le secret n'est pas récupérable ou ne concorde pas avec le serveur en cours — le test
    TTL n'est alors pas exécutable en boîte noire (ex. suite lancée contre une image distante).
    """
    try:
        from common import settings

        secret = settings.get_secret_key()
        ser = Serializer(secret_key=secret)
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"secret serveur indisponible côté hôte : {e}")
    if not secret:
        pytest.skip("secret serveur indisponible (None)")
    # Concordance : un vrai JWT de login doit se décoder avec ce secret.
    register_user(HOST_ADDRESS)
    try:
        raw = str(ser.loads(login(HOST_ADDRESS)))
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"secret hôte ne concorde pas avec le serveur : {e}")
    if len(raw) < 32:
        pytest.skip("access_token décodé invalide")
    return ser


@pytest.mark.p0
def test_session_ttl_enforced(server_serializer):
    """TTL 12 h — un JWT stampé il y a plus de 12 h est refusé (401) ; un token frais passe (200)."""
    ser = server_serializer
    register_user(HOST_ADDRESS)
    raw = str(ser.loads(login(HOST_ADDRESS)))  # access_token courant (valide)

    # Contrôle : un token re-forgé à l'instant (même access_token) authentifie → isole l'effet TTL.
    assert _auth_status(HOST_ADDRESS, _PROBE, ser.dumps(raw)) == 200, "un token frais valide devrait passer"

    # Forge un token daté de 13 h dans le passé → doit expirer (SignatureExpired → 401).
    import itsdangerous.timed as _t

    orig = _t.time.time
    _t.time.time = lambda: orig() - 13 * 3600
    try:
        expired = ser.dumps(raw)
    finally:
        _t.time.time = orig
    assert _auth_status(HOST_ADDRESS, _PROBE, expired) == 401, (
        "TTL non appliqué : un JWT vieux de 13 h a été accepté (max_age manquant côté jwt.loads)"
    )
