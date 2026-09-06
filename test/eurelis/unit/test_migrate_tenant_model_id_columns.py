# Eurelis — tests unitaires de la migration int → varchar(32) des colonnes tenant_*_id (base factice).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import pytest

from api.db import db_models


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class FakeDB:
    """Enregistre les requêtes émises et répond aux introspections information_schema."""

    def __init__(self, column_types: dict[tuple[str, str], str | None], tables: set[str] | None = None):
        self.column_types = column_types
        self.tables = tables if tables is not None else {t for t, _ in column_types}
        self.statements: list[str] = []

    def table_exists(self, table_name):
        return table_name in self.tables

    def execute_sql(self, sql, params=None):
        if "information_schema" in sql:
            table_name, column_name = params
            return _Cursor((self.column_types.get((table_name, column_name)),))
        self.statements.append(sql)
        return _Cursor(None)


@pytest.fixture
def fake_columns(monkeypatch):
    monkeypatch.setattr(db_models, "_tenant_model_id_columns", lambda: [("tenant", "tenant_llm_id"), ("tenant", "tenant_ocr_id"), ("dialog", "tenant_llm_id"), ("memory", "tenant_embd_id")])


def _install(monkeypatch, db, database_type):
    monkeypatch.setattr(db_models, "DB", db)
    monkeypatch.setattr(db_models.settings, "DATABASE_TYPE", database_type)


def test_column_derivation_matches_only_tenant_model_id_fields():
    columns = db_models._tenant_model_id_columns()
    assert ("tenant", "tenant_llm_id") in columns
    assert ("tenant", "tenant_ocr_id") in columns
    assert ("knowledgebase", "tenant_embd_id") in columns
    assert ("dialog", "tenant_rerank_id") in columns
    assert ("memory", "tenant_llm_id") in columns
    assert all(column != "tenant_id" for _, column in columns)


def test_mysql_resets_then_widens_only_int_columns(monkeypatch, fake_columns):
    db = FakeDB(
        {
            ("tenant", "tenant_llm_id"): "int",
            ("tenant", "tenant_ocr_id"): "varchar",
            ("dialog", "tenant_llm_id"): "bigint",
            ("memory", "tenant_embd_id"): "int",
        },
        tables={"tenant", "dialog"},  # memory table absent
    )
    _install(monkeypatch, db, "mysql")

    db_models.migrate_tenant_model_id_columns_to_varchar()

    assert db.statements == [
        "UPDATE tenant SET tenant_llm_id = NULL",
        "ALTER TABLE tenant MODIFY tenant_llm_id VARCHAR(32) NULL",
        "UPDATE dialog SET tenant_llm_id = NULL",
        "ALTER TABLE dialog MODIFY tenant_llm_id VARCHAR(32) NULL",
    ]


def test_postgres_uses_alter_column_type(monkeypatch, fake_columns):
    db = FakeDB({("tenant", "tenant_llm_id"): "integer", ("tenant", "tenant_ocr_id"): "character varying", ("dialog", "tenant_llm_id"): "character varying", ("memory", "tenant_embd_id"): None})
    _install(monkeypatch, db, "postgres")

    db_models.migrate_tenant_model_id_columns_to_varchar()

    assert db.statements == [
        "UPDATE tenant SET tenant_llm_id = NULL",
        "ALTER TABLE tenant ALTER COLUMN tenant_llm_id TYPE VARCHAR(32) USING tenant_llm_id::VARCHAR(32)",
    ]


def test_is_noop_once_columns_are_varchar(monkeypatch, fake_columns):
    db = FakeDB({("tenant", "tenant_llm_id"): "varchar", ("tenant", "tenant_ocr_id"): "varchar", ("dialog", "tenant_llm_id"): "varchar", ("memory", "tenant_embd_id"): "varchar"})
    _install(monkeypatch, db, "mysql")

    db_models.migrate_tenant_model_id_columns_to_varchar()

    assert db.statements == []


def test_failure_on_one_column_does_not_stop_the_others(monkeypatch, fake_columns):
    class FailingOnDialog(FakeDB):
        def execute_sql(self, sql, params=None):
            if sql.startswith("ALTER TABLE dialog"):
                raise RuntimeError("boom")
            return super().execute_sql(sql, params)

    db = FailingOnDialog({("tenant", "tenant_llm_id"): "int", ("tenant", "tenant_ocr_id"): "varchar", ("dialog", "tenant_llm_id"): "int", ("memory", "tenant_embd_id"): "int"})
    _install(monkeypatch, db, "mysql")

    db_models.migrate_tenant_model_id_columns_to_varchar()

    assert "UPDATE memory SET tenant_embd_id = NULL" in db.statements
    assert "ALTER TABLE memory MODIFY tenant_embd_id VARCHAR(32) NULL" in db.statements
