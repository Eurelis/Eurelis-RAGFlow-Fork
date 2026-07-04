# Eurelis — helpers HTTP pour l'auth RAGFlow et l'amorçage des modèles Ollama (tenant de test).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Toutes les requêtes ci-dessous ont été vérifiées empiriquement contre
# l'image eurelis/ragflow:v0.26.1-eurelis.3 (système tenant_model / API RESTful /api/v1).

import httpx

from configs import (
    CHAT_MODEL,
    CHAT_MODEL_PII,
    EMAIL,
    EMBED_MODEL,
    HTTP_TIMEOUT,
    NICKNAME,
    OLLAMA_INSTANCE,
    OLLAMA_INTERNAL_URL,
    OLLAMA_PROVIDER,
    PASSWORD,
    VERSION,
)


class AuthError(RuntimeError):
    pass


def register_user(base_url: str, email: str = EMAIL, nickname: str = NICKNAME) -> None:
    """Inscrit un utilisateur (par défaut l'utilisateur de test). Idempotent : ignore « déjà inscrit »."""
    r = httpx.post(
        f"{base_url}/api/{VERSION}/users",
        json={"email": email, "nickname": nickname, "password": PASSWORD},
        timeout=HTTP_TIMEOUT,
    )
    body = r.json()
    if body.get("code") != 0 and "has already registered" not in (body.get("message") or ""):
        raise AuthError(f"register a échoué : {body.get('message')!r}")


def login(base_url: str, email: str = EMAIL) -> str:
    """Connecte un utilisateur (mot de passe partagé) et renvoie l'en-tête Authorization (Bearer …)."""
    r = httpx.post(
        f"{base_url}/api/{VERSION}/auth/login",
        json={"email": email, "password": PASSWORD},
        timeout=HTTP_TIMEOUT,
    )
    body = r.json()
    if body.get("code") != 0:
        raise AuthError(f"login a échoué : {body.get('message')!r}")
    authorization = r.headers.get("Authorization")
    if not authorization:
        raise AuthError("login : en-tête Authorization absent de la réponse")
    return authorization


def get_api_token(base_url: str, auth_header: str) -> str:
    """Crée/récupère un token d'API persistant (utilisable comme clé SDK)."""
    r = httpx.post(
        f"{base_url}/api/{VERSION}/system/tokens",
        headers={"Authorization": auth_header},
        timeout=HTTP_TIMEOUT,
    )
    body = r.json()
    if body.get("code") != 0:
        raise AuthError(f"création token a échoué : {body.get('message')!r}")
    return body["data"]["token"]


def admin_login(admin_base: str, email: str = None, password_plain: str = None) -> str:
    """
    Connecte l'admin sur le serveur Flask (:9381) et renvoie l'en-tête Authorization (JWT).
    Le mot de passe est chiffré RSA côté client (même mécanisme que le login RAGFlow).
    """
    from api.utils.crypt import crypt  # import tardif : dépend de la clé publique RAGFlow

    from configs import ADMIN_EMAIL, ADMIN_PASSWORD_PLAIN

    email = email or ADMIN_EMAIL
    password_plain = password_plain or ADMIN_PASSWORD_PLAIN
    r = httpx.post(
        f"{admin_base}/api/{VERSION}/admin/login",
        json={"email": email, "password": crypt(password_plain)},
        timeout=HTTP_TIMEOUT,
    )
    if r.status_code != 200 or r.json().get("code") != 0:
        raise AuthError(f"login admin a échoué : {r.status_code} {r.text[:200]}")
    jwt = r.headers.get("Authorization")
    if not jwt:
        raise AuthError("login admin : en-tête Authorization (JWT) absent")
    return jwt


def get_own_tenant_id(base_url: str, auth_header: str) -> str:
    """Renvoie l'id du tenant personnel de l'utilisateur courant (= son user id)."""
    r = httpx.get(
        f"{base_url}/api/{VERSION}/users/me/models",
        headers={"Authorization": auth_header},
        timeout=HTTP_TIMEOUT,
    )
    body = r.json()
    if body.get("code") != 0:
        raise AuthError(f"users/me/models a échoué : {body.get('message')!r}")
    return body["data"]["tenant_id"]


def _defaults_already_ollama(base_url: str, headers: dict) -> bool:
    r = httpx.get(f"{base_url}/api/{VERSION}/models/default", headers=headers, timeout=HTTP_TIMEOUT)
    if r.status_code != 200:
        return False
    models = (r.json().get("data") or {}).get("models") or []
    have = {(m.get("model_type"), m.get("model_provider")) for m in models}
    return ("chat", OLLAMA_PROVIDER) in have and ("embedding", OLLAMA_PROVIDER) in have


def ensure_default_ollama_models(base_url: str, auth_header: str) -> None:
    """
    Amorçage idempotent du tenant de test sur Ollama local :
      1. ajoute le provider Ollama          (PUT  /api/v1/providers)
      2. crée l'instance + déclare 2 modèles (POST /api/v1/providers/Ollama/instances)
      3. fixe les modèles chat/embedding par défaut (PATCH /api/v1/models/default)

    base_url d'Ollama = OLLAMA_INTERNAL_URL (hostname réseau Docker), la validation étant
    faite côté serveur RAGFlow. Ne relève pas les erreurs « déjà existant ».
    """
    headers = {"Authorization": auth_header, "Content-Type": "application/json"}

    def _ok(body: dict) -> bool:
        msg = (body.get("message") or "").lower()
        return body.get("code") == 0 or "already exist" in msg or "duplicated" in msg

    if not _defaults_already_ollama(base_url, headers):
        # 1) provider
        r = httpx.put(f"{base_url}/api/{VERSION}/providers", headers=headers,
                      json={"provider_name": OLLAMA_PROVIDER}, timeout=HTTP_TIMEOUT)
        if not _ok(r.json()):
            raise AuthError(f"add provider Ollama : {r.json().get('message')!r}")

        # 2) instance + modèles (model_info requis pour un provider à modèles définis par l'utilisateur)
        r = httpx.post(
            f"{base_url}/api/{VERSION}/providers/{OLLAMA_PROVIDER}/instances",
            headers=headers,
            json={
                "instance_name": OLLAMA_INSTANCE,
                "api_key": "ollama",
                "base_url": OLLAMA_INTERNAL_URL,
                "region": "default",
                "model_info": [
                    {"model_type": ["chat"], "model_name": CHAT_MODEL, "max_tokens": 8192},
                    {"model_type": ["embedding"], "model_name": EMBED_MODEL, "max_tokens": 8192},
                ],
            },
            timeout=HTTP_TIMEOUT,
        )
        if not _ok(r.json()):
            raise AuthError(f"create instance Ollama : {r.json().get('message')!r}")

        # 3) défauts (le modèle chat par défaut est le modèle SANS PII)
        for model_type, model_name in (("chat", CHAT_MODEL), ("embedding", EMBED_MODEL)):
            r = httpx.patch(
                f"{base_url}/api/{VERSION}/models/default",
                headers=headers,
                json={
                    "model_provider": OLLAMA_PROVIDER,
                    "model_instance": OLLAMA_INSTANCE,
                    "model_type": model_type,
                    "model_name": model_name,
                },
                timeout=HTTP_TIMEOUT,
            )
            if r.json().get("code") != 0:
                raise AuthError(f"set default {model_type} : {r.json().get('message')!r}")

    # 4) modèle chat variante ::pii (masquage PII opt-in) — idempotent, ajouté à l'instance existante.
    r = httpx.post(
        f"{base_url}/api/{VERSION}/providers/{OLLAMA_PROVIDER}/instances/{OLLAMA_INSTANCE}/models",
        headers=headers,
        json={"model_name": CHAT_MODEL_PII, "model_type": "chat", "max_tokens": 8192},
        timeout=HTTP_TIMEOUT,
    )
    if not _ok(r.json()):
        raise AuthError(f"add modèle {CHAT_MODEL_PII} : {r.json().get('message')!r}")
