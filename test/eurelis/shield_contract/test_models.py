# Eurelis — contrat P0 de GET /api/v1/models, consommé par le Shield pour résoudre
# les llm_id au format UUID (tenant_model, RAGFlow >= 0.27) en noms composites
# "modele@instance@provider" (feature Shield 030-llm-id-resolution).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
# NB : la docstring Swagger de la route est obsolète ; ce contrat fige la réponse réelle.

import pytest

from configs import VERSION
from libs.contract import assert_valid
from schemas.models import MODEL_SCHEMA, MODELS_ENVELOPE_SCHEMA


@pytest.mark.p0
def test_list_models_contract(api):
    """GET /models?type=chat : enveloppe {code, data[]} figée — le Shield lit
    model_id, name, provider_name, instance_name, model_type."""
    r = api.get(f"/api/{VERSION}/models", params={"type": "chat"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert_valid(body, MODELS_ENVELOPE_SCHEMA, label="models")
    assert body["code"] == 0, body
    assert body["data"], "data attendu (liste non vide : au moins un modèle chat configuré)"
    for i, model in enumerate(body["data"]):
        assert_valid(model, MODEL_SCHEMA, label=f"model[{i}]")
        assert "chat" in model["model_type"], f"model[{i}] ne porte pas le type 'chat'"


@pytest.mark.p0
def test_list_models_scoped_by_owner_tenant(api):
    """GET /models?type=chat&owner_tenant_id= : le paramètre de scoping par tenant
    (chats partagés d'autres tenants) est accepté et renvoie le même contrat."""
    r = api.get(f"/api/{VERSION}/models", params={"type": "chat"})
    assert r.status_code == 200, r.text
    models = r.json().get("data") or []
    assert models, "prérequis : au moins un modèle chat"
    tenant_id = models[0].get("tenant_id")
    assert tenant_id, "chaque entrée de modèle porte le tenant_id propriétaire"

    r2 = api.get(f"/api/{VERSION}/models", params={"type": "chat", "owner_tenant_id": tenant_id})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert_valid(body, MODELS_ENVELOPE_SCHEMA, label="models(owner_tenant_id)")
    assert body["code"] == 0, body
    assert body["data"], "le tenant propriétaire doit retrouver ses propres modèles"
