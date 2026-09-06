# Eurelis — tests unitaires de la resynchronisation tenant_model ↔ catalogue (SQLite en mémoire).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import json

import pytest
from peewee import SqliteDatabase

from api.db import db_models
from api.db.db_models import TenantModel, TenantModelInstance, TenantModelProvider

MODELS = [TenantModelProvider, TenantModelInstance, TenantModel]

CATALOGUE = [
    {
        "name": "Bedrock",
        "llm": [
            {"llm_name": "amazon.titan-embed-text-v2:0", "model_type": "embedding", "max_tokens": 8192},
            {"llm_name": "eu.anthropic.claude-sonnet-4-6", "model_type": ["chat", "image2text"], "max_tokens": 1000000, "is_tools": True},
            {"llm_name": "cohere.rerank-v3-5:0", "model_type": "rerank", "max_tokens": 4096},
            {"llm_name": "no-type-entry", "max_tokens": 1},
        ],
    },
    {"name": "OpenAI", "llm": [{"llm_name": "gpt-5", "model_type": "chat", "max_tokens": 400000, "is_tools": True, "features": ["thinking"]}]},
    {"name": "siliconflow", "llm": [{"llm_name": "cn-only", "model_type": "chat", "max_tokens": 1}]},
    {"name": "siliconflow_intl", "llm": [{"llm_name": "intl-only", "model_type": "chat", "max_tokens": 1}]},
]


@pytest.fixture
def sqlite_db(monkeypatch):
    db = SqliteDatabase(":memory:")
    db.bind(MODELS, bind_refs=False, bind_backrefs=False)
    db.connect()
    db.create_tables(MODELS)
    monkeypatch.setattr(db_models, "DB", db)
    monkeypatch.setattr(db_models.settings, "FACTORY_LLM_INFOS", CATALOGUE)
    yield db
    db.drop_tables(MODELS)
    db.close()


def _row(model, **kwargs):
    now = 1
    return model.create(create_time=now, create_date="2026-01-01 00:00:00", update_time=now, update_date="2026-01-01 00:00:00", **kwargs)


def _instance(provider, instance_id, name="Default", status="active", extra="{}"):
    return _row(TenantModelInstance, id=instance_id, instance_name=name, provider_id=provider.id, api_key="k", status=status, extra=extra)


def _names(instance_id):
    return {m.model_name: m for m in TenantModel.select().where(TenantModel.instance_id == instance_id)}


def test_inserts_catalogue_models_missing_from_active_instance(sqlite_db):
    provider = _row(TenantModelProvider, id="p1", provider_name="Bedrock", tenant_id="t1")
    _instance(provider, "i1")
    _row(TenantModel, id="m1", model_name="amazon.titan-embed-text-v2:0", provider_id="p1", instance_id="i1", model_type=2, status="inactive", extra='{"max_tokens": 42}')

    db_models.sync_tenant_model_instances_with_catalogue()

    rows = _names("i1")
    assert set(rows) == {"amazon.titan-embed-text-v2:0", "eu.anthropic.claude-sonnet-4-6", "cohere.rerank-v3-5:0"}
    # existing row untouched (status and extra preserved)
    assert rows["amazon.titan-embed-text-v2:0"].status == "inactive"
    assert json.loads(rows["amazon.titan-embed-text-v2:0"].extra) == {"max_tokens": 42}
    # inserted rows mirror create_provider_instance expansion
    chat = rows["eu.anthropic.claude-sonnet-4-6"]
    assert chat.model_type == 1 | 8
    assert chat.status == "active"
    assert chat.provider_id == "p1"
    assert len(chat.id) == 32
    assert json.loads(chat.extra) == {"max_tokens": 1000000, "is_tools": True, "thinking": False, "verify": "unknown"}
    assert rows["cohere.rerank-v3-5:0"].model_type == 16


def test_is_idempotent(sqlite_db):
    provider = _row(TenantModelProvider, id="p1", provider_name="OpenAI", tenant_id="t1")
    _instance(provider, "i1")

    db_models.sync_tenant_model_instances_with_catalogue()
    first = {m.id for m in TenantModel.select()}
    db_models.sync_tenant_model_instances_with_catalogue()
    second = {m.id for m in TenantModel.select()}

    assert first == second
    assert len(first) == 1
    assert json.loads(TenantModel.get().extra)["thinking"] is True


def test_skips_inactive_instances_and_unknown_providers(sqlite_db):
    bedrock = _row(TenantModelProvider, id="p1", provider_name="Bedrock", tenant_id="t1")
    _instance(bedrock, "i-inactive", status="inactive")
    unknown = _row(TenantModelProvider, id="p2", provider_name="NotInCatalogue", tenant_id="t1")
    _instance(unknown, "i-unknown")

    db_models.sync_tenant_model_instances_with_catalogue()

    assert TenantModel.select().count() == 0


def test_siliconflow_intl_region_uses_intl_catalogue(sqlite_db):
    provider = _row(TenantModelProvider, id="p1", provider_name="siliconflow", tenant_id="t1")
    _instance(provider, "i-cn", name="cn", extra=json.dumps({"region": "default"}))
    _instance(provider, "i-intl", name="intl", extra=json.dumps({"region": "intl"}))

    db_models.sync_tenant_model_instances_with_catalogue()

    assert set(_names("i-cn")) == {"cn-only"}
    assert set(_names("i-intl")) == {"intl-only"}


def test_noop_without_catalogue(sqlite_db, monkeypatch):
    provider = _row(TenantModelProvider, id="p1", provider_name="Bedrock", tenant_id="t1")
    _instance(provider, "i1")
    monkeypatch.setattr(db_models.settings, "FACTORY_LLM_INFOS", [])

    db_models.sync_tenant_model_instances_with_catalogue()

    assert TenantModel.select().count() == 0
