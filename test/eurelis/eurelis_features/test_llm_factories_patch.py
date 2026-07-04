# Eurelis — P1 : le patch conf/llm_factories.patch.json est bien fusionné au catalogue au démarrage.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Le fork n'édite jamais conf/llm_factories.json (upstream) : les surcharges Eurelis vivent dans
# conf/llm_factories.patch.json, appliqué au boot par common/settings.py (nouveau provider, ajout de
# modèle, override de clé, suppression par null). Ce test vérifie le mécanisme en intégration : un patch
# SYNTHÉTIQUE (test/eurelis/fixtures/llm_factories.patch.json) est monté dans la stack de test
# (docker/docker-compose-test.yml → /ragflow/conf/llm_factories.patch.json) et on assert que le catalogue
# fusionné, exposé par l'API, contient bien ses entrées.
#
# NB : dépend du montage du patch par le compose de test. Si les assertions échouent, soit le merge a
# régressé (common/settings.py), soit le patch n'est plus monté.

import pytest

from configs import VERSION

pytestmark = pytest.mark.p1

# Doit rester synchronisé avec test/eurelis/fixtures/llm_factories.patch.json
PATCH_NEW_PROVIDER = "EurelisMergeTest"
PATCH_NEW_MODEL = "eurelis-merge-marker"
PATCH_TARGET_PROVIDER = "OpenAI"
PATCH_APPENDED_MODEL = "eurelis-openai-marker"


def _available_providers(api) -> set:
    data = api.get(f"/api/{VERSION}/providers", params={"available": "true"}).json()["data"]
    return {(p.get("provider_name") or p.get("name")) for p in data}


def _provider_models(api, provider: str) -> set:
    data = api.get(f"/api/{VERSION}/providers/{provider}/models").json().get("data") or []
    return {(m.get("llm_name") or m.get("name")) for m in data}


def test_patch_adds_new_provider(api):
    """Le patch ajoute un provider absent de la base → présent dans le catalogue fusionné."""
    providers = _available_providers(api)
    assert PATCH_NEW_PROVIDER in providers, (
        f"provider '{PATCH_NEW_PROVIDER}' du patch absent du catalogue "
        f"(merge non appliqué ou patch non monté). Vus : {sorted(providers)[:8]}…"
    )


def test_patch_new_provider_exposes_its_model(api):
    """Le modèle déclaré par le nouveau provider du patch est disponible."""
    assert PATCH_NEW_MODEL in _provider_models(api, PATCH_NEW_PROVIDER), (
        f"modèle '{PATCH_NEW_MODEL}' absent de {PATCH_NEW_PROVIDER}"
    )


def test_patch_appends_model_to_existing_provider(api):
    """Le patch ajoute un modèle à un provider existant (append + dédup sur llm_name)."""
    models = _provider_models(api, PATCH_TARGET_PROVIDER)
    assert PATCH_APPENDED_MODEL in models, (
        f"modèle '{PATCH_APPENDED_MODEL}' non appendé à {PATCH_TARGET_PROVIDER} : {sorted(models)[:8]}…"
    )
