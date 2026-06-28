---
title: "Spec — Table `usage_log` (append-only)"
type: spec
status: implemented
reviewed: 2026-06-28
---

# Spec — Table `usage_log` (append-only)

Table append-only et immuable : chaque fin de completion / retrieval / tâche d'ingestion y écrit un enregistrement. Elle survit à la suppression des sessions et dialogs, et constitue la source de vérité unique pour toutes les statistiques de consommation (dashboards admin et utilisateur).

---

## Modèle orthogonal

Deux dimensions indépendantes décrivent chaque entrée :

- **`source`** — le **flux** : `chat`, `search`, `agent`, `ingestion`
- **`token_type`** — la **nature du token** : `llm`, `embedding`

Toute combinaison `(source, token_type)` est possible. Exemple : une recherche IA produit `(search, embedding)` (embedding de la requête) **et** `(search, llm)` (synthèse).

| `source` | Couvre | `token_type` observés |
|---|---|---|
| `chat` | chat applicatif **et** widget chatbot iframe | `llm`, `embedding` |
| `search` | recherche IA (`/searches/.../completions`) **et** retrievals dataset déclenchés par une app Search (`/datasets/search` avec `search_id`) | `llm`, `embedding` |
| `agent` | workflows d'agent (retrieval inclus) | `embedding` (le LLM d'agent n'est pas encore tracé) |
| `ingestion` | indexation de documents | `embedding` (chunks), `llm` (GraphRAG/RAPTOR/extraction) |

> Le SDK dataset autonome (`/datasets/search` **sans** `search_id`) est également loggé sous `source="search"`.

---

## Schéma

```sql
CREATE TABLE usage_log (
    id          VARCHAR(32)  NOT NULL PRIMARY KEY,
    user_id     VARCHAR(255) NOT NULL,
    resource_id VARCHAR(32)  NOT NULL,
    object_id   VARCHAR(32)  NOT NULL,
    source      VARCHAR(16)  NOT NULL DEFAULT 'chat',
    token_type  VARCHAR(16)  NOT NULL DEFAULT 'llm',
    tokens      INTEGER      NOT NULL DEFAULT 0,
    duration    FLOAT        NOT NULL DEFAULT 0.0,
    model       VARCHAR(128) NOT NULL DEFAULT '',
    provider    VARCHAR(64)  NOT NULL DEFAULT '',
    create_time BIGINT       NOT NULL,
    create_date DATETIME     NOT NULL
);
```

`create_time` / `create_date` sont fournis par `BaseModel`. Index sur `user_id`, `resource_id`, `object_id`, `source`, `token_type`, `model`, `provider`, `create_date`.

### Sémantique de `resource_id` / `object_id` selon le flux

| `source` | `resource_id` | `object_id` |
|---|---|---|
| `chat` | `dialog_id` | `conversation_id` |
| `search` | `search_id` (app Search) ou `dataset_id` (SDK) | `""` |
| `agent` | `agent_id` (canvas) | `task_id` |
| `ingestion` | `kb_id` | `doc_id` |

> Colonnes partagées entre flux : **ne jamais joindre `resource_id` / `object_id` entre flux différents sans filtrer sur `source`** (et au besoin `token_type`).

### `user_id` — sémantique mixte

- Vrai utilisateur (`current_user.id`) pour `chat`, `search`.
- Utilisateur runtime du canvas pour `agent`.
- `Document.created_by` pour `ingestion`.
- Tenant / propriétaire de clé API pour les accès SDK.

---

## Modèle Peewee

**Fichier :** `api/db/db_models.py` — `class UsageLog(DataBaseModel)` (après `API4Conversation`).

```python
class UsageLog(DataBaseModel):
    id = CharField(max_length=32, primary_key=True)
    user_id = CharField(max_length=255, null=False, index=True)
    resource_id = CharField(max_length=32, null=False, index=True)
    object_id = CharField(max_length=32, null=False, index=True)
    source = CharField(max_length=16, null=False, default="chat", index=True)
    token_type = CharField(max_length=16, null=False, default="llm", index=True)
    tokens = IntegerField(default=0)
    duration = FloatField(default=0.0)
    model = CharField(max_length=128, null=False, default="", index=True)
    provider = CharField(max_length=64, null=False, default="", index=True)

    class Meta:
        db_table = "usage_log"
```

### Migration

La table est créée par `init_database_tables()` au démarrage (nouvelle table). La colonne **`token_type` n'est PAS ajoutée par `migrate_db()`** — sur une base existante, exécuter manuellement l'ALTER **avant** de démarrer le serveur sur cette version :

```sql
ALTER TABLE usage_log
  ADD COLUMN token_type VARCHAR(16) NOT NULL DEFAULT 'llm';
CREATE INDEX usage_log_token_type ON usage_log (token_type);
```

`NOT NULL DEFAULT 'llm'` ⇒ les lignes existantes prennent `token_type='llm'` (pas de backfill du flux pour les anciens embeddings — choix assumé).

---

## Écriture

Toute la logique d'écriture des flux non-conversationnels est centralisée dans **`api/db/services/eurelis_usage_log.py`** :

| Fonction | Usage |
|---|---|
| `log_embedding_from_bundle(embd_mdl, *, source, …)` | embeddings de requête, lit `LLMBundle.used_tokens` (search, agent, dataset) |
| `log_embedding_from_usage(usage, *, source, …)` | embeddings du chat, depuis le dict `usage` propagé par `async_chat` |
| `log_search_completion(…)` | tokens LLM de synthèse du search (`num_tokens_from_string`) |

Le cœur appelle `UsageLogService.log(..., source=..., token_type=...)`. `log()` ignore toute entrée `tokens == 0 ET duration == 0` (les lignes agent placeholder ne sont donc jamais écrites).

| Flux | `token_type=llm` | `token_type=embedding` |
|---|---|---|
| `chat` | `chat_api.py`, `conversation_service.py` | idem (via `log_embedding_from_usage`) |
| `search` | `dialog_service.async_ask` (`log_search_completion`) | `dialog_service.async_ask`, `dataset_api_service` |
| `agent` | `agent_api` (placeholder, non écrit) | `agent/tools/retrieval.py` |
| `ingestion` | `task_executor_refactor/task_handler.py` | task executors |

---

## Lecture — `UsageLogService`

**Fichier :** `api/db/services/usage_log_service.py`. Toutes les méthodes d'agrégation acceptent les filtres `source` et `token_type` (str ou liste) :

- `stats_for_user`, `stats_by_day`, `stats_by_usage` (par utilisateur)
- `stats_all_users`, `active_users_count`, `stats_by_dialog` (admin)
- `stats_timeseries`, `stats_timeseries_by_source`, `stats_timeseries_by_token_type`
- `stats_by_source`, `stats_by_token_type`, `stats_by_model`
- `stats_ingestion_for_user`, `stats_ingestion_by_kb`
- `available_sources()`, `available_types()`

> **Durée moyenne** : `avg_duration_ms` utilise `AVG(NULLIF(duration, 0))` — les entrées à durée nulle (embeddings) sont exclues du calcul, évitant de tirer la moyenne vers le bas.

---

## Limites connues

- **Données historiques** : les sessions antérieures au déploiement n'apparaissent pas. Les anciennes lignes (avant le refactoring `source`/`token_type`) gardent `token_type='llm'` par défaut.
- **Agent LLM** : les tokens des composants LLM/Agent d'un workflow ne sont pas encore tracés (seul l'embedding de retrieval l'est). L'entrée `source="agent"` reste à `tokens=0` (donc non persistée).
- **Dédoublonnage** : une completion retentée peut créer deux entrées ; `object_id` + `create_date` permettent de les identifier en post-traitement.
