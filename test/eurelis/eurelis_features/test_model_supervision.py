# Eurelis — P1 : supervision admin des modèles par tenant (:9381). Feature Eurelis.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Propriété de sécurité critique : les clés API ne sont JAMAIS renvoyées en clair (aucun champ
# `api_key` brut) — uniquement un indice masqué `api_key_hint` + un booléen `has_api_key`.

import pytest

from configs import (
    HOST_ADDRESS,
    OLLAMA_INSTANCE,
    OLLAMA_PROVIDER,
    TEAMMATE_EMAIL,
    TEAMMATE_NICKNAME,
    VERSION,
)
from libs.contract import assert_valid
from libs.ragflow_api import get_own_tenant_id, login, register_user
from schemas.admin_supervision import TENANT_MODELS_SCHEMA

ADMIN_SUP = f"/api/{VERSION}/admin"


def _assert_no_raw_api_key(node, path="<root>"):
    """Parcourt récursivement la structure et échoue si un champ `api_key` brut est exposé."""
    if isinstance(node, dict):
        assert "api_key" not in node, f"champ `api_key` brut exposé en {path}"
        for k, v in node.items():
            _assert_no_raw_api_key(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            _assert_no_raw_api_key(v, f"{path}[{i}]")


@pytest.mark.p1
def test_tenant_models_contract(admin, own_tenant_id):
    r = admin.get(f"/api/{VERSION}/admin/tenants/{own_tenant_id}/models")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert_valid(data, TENANT_MODELS_SCHEMA, label="tenant models")
    assert data["tenant_id"] == own_tenant_id


@pytest.mark.p1
def test_api_keys_are_masked(admin, own_tenant_id):
    """Aucune clé API en clair ; chaque instance expose un indice masqué (api_key_hint)."""
    r = admin.get(f"/api/{VERSION}/admin/tenants/{own_tenant_id}/models")
    data = r.json()["data"]
    _assert_no_raw_api_key(data)
    for inst in data["instances"]:
        assert inst.get("api_key_hint"), f"api_key_hint manquant : {inst}"
        assert "*" in inst["api_key_hint"], f"api_key_hint non masqué : {inst['api_key_hint']!r}"
        assert isinstance(inst.get("has_api_key"), bool)


@pytest.mark.p1
def test_models_compare_matrix(admin, own_tenant_id):
    """Matrice de comparaison multi-tenants : inclut le tenant demandé, sans clé en clair."""
    r = admin.get(f"/api/{VERSION}/admin/tenants/models/compare", params={"tenant_ids": own_tenant_id})
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    _assert_no_raw_api_key(data)
    import json

    assert own_tenant_id in json.dumps(data), "tenant demandé absent de la matrice de comparaison"


# --- Mutations : copy / defaults / delete vers un tenant cible ------------------------------
def _ollama_instances(admin, tenant_id):
    data = admin.get(f"{ADMIN_SUP}/tenants/{tenant_id}/models").json()["data"]
    return [i for i in data.get("instances", []) if i["provider_name"] == OLLAMA_PROVIDER]


def _default_providers(admin, tenant_id):
    data = admin.get(f"{ADMIN_SUP}/tenants/{tenant_id}/models").json()["data"]
    return {d["model_type"]: d["model_provider"] for d in data.get("default_models", [])}


@pytest.fixture
def target_tenant(admin, token):
    """Tenant cible vierge (tenant personnel du coéquipier), nettoyé avant et après le test."""
    register_user(HOST_ADDRESS, email=TEAMMATE_EMAIL, nickname=TEAMMATE_NICKNAME)
    b_tid = get_own_tenant_id(HOST_ADDRESS, login(HOST_ADDRESS, email=TEAMMATE_EMAIL))

    def _cleanup():
        admin.post(
            f"{ADMIN_SUP}/tenants/models/instances/delete",
            json={"provider_name": OLLAMA_PROVIDER, "instance_name": OLLAMA_INSTANCE, "target_tenant_ids": [b_tid]},
        )

    _cleanup()
    yield b_tid
    _cleanup()


@pytest.mark.p1
def test_supervision_copy_defaults_delete(admin, own_tenant_id, target_tenant):
    """Roundtrip : copie d'instance A→B (clé propagée mais masquée) → copie des défauts → suppression."""
    assert not _ollama_instances(admin, target_tenant), "le tenant cible devrait être vierge"

    # 1) Copier l'instance Ollama de A vers B
    r = admin.post(
        f"{ADMIN_SUP}/tenants/models/instances/copy",
        json={
            "source_tenant_id": own_tenant_id,
            "provider_name": OLLAMA_PROVIDER,
            "instance_name": OLLAMA_INSTANCE,
            "target_tenant_ids": [target_tenant],
        },
    )
    assert r.status_code == 200 and r.json()["code"] == 0, r.text
    assert r.json()["data"]["added"] >= 1, r.json()

    # 2) B possède l'instance, clé propagée mais TOUJOURS masquée
    binst = _ollama_instances(admin, target_tenant)
    assert binst, "instance non copiée chez la cible"
    inst = binst[0]
    assert inst["has_api_key"] is True, "la clé API n'a pas été propagée"
    assert "*" in inst["api_key_hint"] and "api_key" not in inst, "clé exposée en clair côté cible !"

    # 3) Copier les modèles par défaut de A vers B
    r = admin.post(
        f"{ADMIN_SUP}/tenants/models/defaults/copy",
        json={"source_tenant_id": own_tenant_id, "target_tenant_ids": [target_tenant]},
    )
    assert r.status_code == 200 and r.json()["code"] == 0, r.text
    defaults = _default_providers(admin, target_tenant)
    assert defaults.get("chat") == OLLAMA_PROVIDER and defaults.get("embedding") == OLLAMA_PROVIDER, defaults

    # 4) Supprimer l'instance chez B
    r = admin.post(
        f"{ADMIN_SUP}/tenants/models/instances/delete",
        json={"provider_name": OLLAMA_PROVIDER, "instance_name": OLLAMA_INSTANCE, "target_tenant_ids": [target_tenant]},
    )
    assert r.status_code == 200 and r.json()["code"] == 0, r.text
    assert r.json()["data"]["deleted"] >= 1, r.json()
    assert not _ollama_instances(admin, target_tenant), "instance non supprimée chez la cible"
