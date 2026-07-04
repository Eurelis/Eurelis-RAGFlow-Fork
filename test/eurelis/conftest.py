# Eurelis — fixtures pytest des tests de non-régression (auth, clients HTTP, amorçage Ollama).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import sys
from pathlib import Path

import httpx
import pytest

from configs import ADMIN_ADDRESS, HOST_ADDRESS, HTTP_TIMEOUT, REF_CHAT_NAME, REF_CHAT_PII_NAME, VERSION
from libs.ragflow_api import (
    admin_login,
    ensure_default_ollama_models,
    get_api_token,
    get_own_tenant_id,
    login,
    register_user,
)


# --- Authentification (portée session) ------------------------------------------------------
@pytest.fixture(scope="session")
def auth() -> str:
    """En-tête Authorization (JWT de session) obtenu par register + login."""
    register_user(HOST_ADDRESS)
    return login(HOST_ADDRESS)


@pytest.fixture(scope="session")
def token(auth: str) -> str:
    """Token d'API persistant (auth de type clé, comme l'utilise le Shield)."""
    return get_api_token(HOST_ADDRESS, auth)


@pytest.fixture(scope="session", autouse=True)
def provisioned(auth: str) -> None:
    """Amorce le tenant de test sur Ollama local (idempotent) avant tout test."""
    ensure_default_ollama_models(HOST_ADDRESS, auth)


# --- Clients HTTP ---------------------------------------------------------------------------
@pytest.fixture
def api(token: str):
    """Client httpx vers l'API RAGFlow (:9380), authentifié par Bearer token."""
    with httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        yield client


@pytest.fixture(scope="session")
def ref_chat_id(token: str) -> str:
    """
    id du chat de référence (`eurelis-ref-chat`). S'il est absent, exécute le seed pour que la
    suite soit auto-suffisante (pas besoin d'un `make e2e-seed` préalable).
    """
    def find() -> str | None:
        r = httpx.get(
            f"{HOST_ADDRESS}/api/{VERSION}/chats",
            params={"name": REF_CHAT_NAME},
            headers={"Authorization": f"Bearer {token}"},
            timeout=HTTP_TIMEOUT,
        )
        chats = (r.json().get("data") or {}).get("chats") or []
        return chats[0]["id"] if chats else None

    chat_id = find()
    if not chat_id:
        import seed
        seed.main()
        chat_id = find()
    assert chat_id, "chat de référence introuvable même après seed"
    return chat_id


def pytest_configure(config):
    # Marker local (évite d'éditer le pyproject upstream).
    config.addinivalue_line("markers", "pii: tests d'intégration du masquage PII (stack PII activée)")
    config.addinivalue_line("markers", "vision: palier vision/image2text opt-in (EURELIS_RUN_VISION=1)")


def _find_chat(token: str, name: str) -> str | None:
    r = httpx.get(
        f"{HOST_ADDRESS}/api/{VERSION}/chats",
        params={"name": name},
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    )
    chats = (r.json().get("data") or {}).get("chats") or []
    return chats[0]["id"] if chats else None


@pytest.fixture(scope="session")
def ref_chat_pii_id(token: str, ref_chat_id: str) -> str:
    """id du chat de référence AVEC masquage PII (`eurelis-ref-chat-pii`, modèle ::pii)."""
    # ref_chat_id garantit que le seed a tourné (il crée les deux chats).
    chat_id = _find_chat(token, REF_CHAT_PII_NAME)
    assert chat_id, "chat PII de référence introuvable même après seed"
    return chat_id


@pytest.fixture
def session_id(api, ref_chat_id: str):
    """Crée une session fraîche sur le chat de référence, la supprime en fin de test."""
    r = api.post(f"/api/{VERSION}/chats/{ref_chat_id}/sessions", json={"name": "contract-test"})
    assert r.status_code == 200 and r.json().get("code") == 0, r.text
    sid = r.json()["data"]["id"]
    yield sid
    api.request("DELETE", f"/api/{VERSION}/chats/{ref_chat_id}/sessions", json={"ids": [sid]})


@pytest.fixture(scope="session")
def own_tenant_id(token: str) -> str:
    """id du tenant personnel de l'utilisateur de test (pour la supervision admin)."""
    return get_own_tenant_id(HOST_ADDRESS, f"Bearer {token}")


@pytest.fixture(scope="session")
def admin_token() -> str:
    """En-tête Authorization (JWT) de l'admin sur le serveur Flask :9381."""
    return admin_login(ADMIN_ADDRESS)


@pytest.fixture
def admin(admin_token: str):
    """Client httpx authentifié vers le serveur admin Flask (:9381)."""
    with httpx.Client(
        base_url=ADMIN_ADDRESS,
        headers={"Authorization": admin_token},
        timeout=HTTP_TIMEOUT,
    ) as client:
        yield client


# --- SDK optionnel (scénarios lisibles) -----------------------------------------------------
@pytest.fixture(scope="session")
def sdk_client(token: str):
    """
    Client SDK RAGFlow, pour les scénarios de haut niveau. Le SDK vit dans sdk/python et
    n'est pas installé par défaut : on l'ajoute au path, et on skip proprement s'il manque
    (les tests de contrat, eux, tapent l'API en httpx directement).
    """
    sdk_path = Path(__file__).resolve().parents[2] / "sdk" / "python"
    if str(sdk_path) not in sys.path:
        sys.path.insert(0, str(sdk_path))
    try:
        from ragflow_sdk import RAGFlow
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"ragflow_sdk indisponible ({e}). Installer via: uv pip install -e sdk/python")
    return RAGFlow(api_key=token, base_url=HOST_ADDRESS)
