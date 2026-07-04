# Eurelis — test de fumée : valide le socle (stack up, auth token, tenant amorcé sur Ollama).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import pytest

from configs import HOST_ADDRESS, OLLAMA_PROVIDER, VERSION


@pytest.mark.p0
def test_healthz(api):
    """La stack RAGFlow répond et toutes ses dépendances sont OK."""
    r = api.get(f"{HOST_ADDRESS}/api/{VERSION}/system/healthz")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("status") == "ok", body
    for dep in ("db", "doc_engine", "redis", "storage"):
        assert body.get(dep) == "ok", f"{dep} = {body.get(dep)}"


@pytest.mark.p0
def test_api_token_auth(api):
    """Le Bearer token (auth de type clé, comme le Shield) est accepté par l'API RESTful."""
    r = api.get("/api/v1/models")
    assert r.status_code == 200, r.text
    assert r.json().get("code") == 0, r.text


@pytest.mark.p0
def test_default_models_are_ollama(api):
    """Le tenant de test est bien amorcé : modèles chat + embedding par défaut = Ollama."""
    r = api.get("/api/v1/models/default")
    assert r.status_code == 200, r.text
    models = (r.json().get("data") or {}).get("models") or []
    by_type = {m.get("model_type"): m for m in models}
    assert by_type.get("chat", {}).get("model_provider") == OLLAMA_PROVIDER, models
    assert by_type.get("embedding", {}).get("model_provider") == OLLAMA_PROVIDER, models
