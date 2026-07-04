---
title: "Historisation des tokens d'ingestion dans `usage_log`"
type: spec
status: implemented
reviewed: 2026-06-28
---

# Historisation des tokens d'ingestion dans `usage_log`

L'ingestion de documents consomme des tokens de deux natures, désormais toutes deux historisées dans `usage_log` sous le flux `source='ingestion'`, distinguées par la colonne `token_type` :

| `token_type` | Origine |
|---|---|
| `embedding` | Vectorisation des chunks de documents |
| `llm` | Appels LLM d'ingestion : GraphRAG, RAPTOR, extraction de métadonnées |

---

## Mapping des colonnes

`usage_log` est partagé entre tous les flux. Pour `source='ingestion'`, les colonnes génériques portent une sémantique d'ingestion :

| Colonne `usage_log` | Sémantique ingestion |
|---|---|
| `user_id` | `Document.created_by` — utilisateur ayant uploadé le document |
| `resource_id` | `kb_id` — dataset (knowledgebase) |
| `object_id` | `doc_id` — document parsé |
| `source` | `ingestion` |
| `token_type` | `embedding` (chunks) ou `llm` (GraphRAG/RAPTOR/extraction) |
| `tokens` | Tokens consommés sur le batch |
| `duration` | Durée de la tâche d'ingestion (ms) |
| `model` | Modèle d'embedding ou LLM utilisé |
| `provider` | Provider du modèle |

> **Ne jamais joindre `resource_id` / `object_id` entre flux différents sans filtrer sur `source` (et au besoin `token_type`).**

---

## Écriture — `UsageLogService.log_ingestion()`

**Fichier :** `api/db/services/usage_log_service.py`

```python
@classmethod
@DB.connection_context()
def log_ingestion(cls, *, user_id, kb_id, doc_id, tokens,
                  duration_ms=0.0, model="", provider="",
                  token_type="embedding"):
    """Log token consumption from a document ingestion task.

    Always writes source='ingestion', resource_id=kb_id, object_id=doc_id.
    token_type='embedding' for chunk embeddings, 'llm' for ingestion LLM
    tokens (graphrag/raptor/extraction).
    """
    if not tokens:
        return
    cls.insert(
        user_id=user_id, resource_id=kb_id, object_id=doc_id,
        source="ingestion", token_type=token_type,
        tokens=tokens, duration=duration_ms, model=model, provider=provider,
    )
```

### Sites d'appel

| Type de token | Fichier | Détail |
|---|---|---|
| `embedding` | `rag/svr/task_executor.py` | après `DocumentService.increment_chunk_num()` (deux pipelines) |
| `embedding` | `rag/svr/task_executor_refactor/task_handler.py` / `dataflow_service.py` | pipeline nouvelle architecture |
| `llm` | `rag/svr/task_executor_refactor/task_handler.py` | un appel par `(model, provider)`, `token_type="llm"` |

Les tokens LLM d'ingestion sont accumulés par `(model, provider)` via le compteur dédié `api/db/services/ingestion_token_counter.py` (`start_ingestion_llm_tracking()` / `stop_ingestion_llm_tracking()`), branché sur `LLMBundle`, puis écrits en fin de tâche.

---

## ⚠️ Mise en cache LLM et sous-comptage

L'extraction mots-clés / questions (et les autres appels LLM d'ingestion) consulte d'abord un **cache LLM** dans Redis, dont la clé est **`xxh64(llm_name + contenu_du_chunk + …)`** (`rag/graphrag/utils.py::get_llm_cache`). Sur un **cache hit**, l'appel LLM est **sauté** — donc `add_ingestion_llm_tokens()` n'est **pas** invoqué et **aucun token `llm` n'est historisé** pour ce chunk.

**Conséquence pour l'interprétation des stats :**

- Les tokens **`llm` d'ingestion** reflètent le **travail LLM réellement effectué**, pas le volume de contenu ingéré. Si un même contenu de chunk se répète — dans un autre document, un autre dataset, voire un autre tenant (le cache est **global par contenu**, non cloisonné) — le second traitement **ne re-facture pas** les tokens LLM.
- Les tokens **`embedding` d'ingestion** ne sont **pas** concernés : ils sont historisés directement, sans cache, à chaque vectorisation.

Ce comportement est **correct** (pas d'appel LLM ⇒ pas de tokens), mais il faut en tenir compte : deux ingestions de contenus identiques afficheront des `llm@ingestion` très différents (première > 0, suivantes ≈ 0). Vérifié empiriquement : contenu unique → 603 tokens ; ré-ingestion du même contenu → 0.

> Le test de non-régression `test/eurelis/eurelis_features/test_usage_logging_matrix.py::test_ingestion_llm_logged` contourne le cache en utilisant un **contenu unique** à chaque exécution (cache miss garanti), pour une assertion déterministe.

---

## Lecture — méthodes de service

**Fichier :** `api/db/services/usage_log_service.py`

- `stats_ingestion_for_user(user_id, from_date, to_date)` — agrégats (`tasks`, `tokens`, `total_duration_ms`), filtre `source='ingestion'`.
- `stats_ingestion_by_kb(user_id, from_date, to_date)` — répartition par dataset, enrichie du nom de KB.

> Ces deux méthodes ciblent les embeddings d'ingestion ; les agrégats généraux (`stats_for_user`, `stats_by_model`, etc.) couvrent l'ensemble des flux et acceptent les filtres `source` / `token_type`.

---

## Endpoint HTTP

`GET /api/v1/usage-stats/me/ingestion` — voir `api-usage-stats-user.md`.

---

## Notes

| Point | Détail |
|---|---|
| `user_id` = `Document.created_by` | En cas de re-parsing par un autre utilisateur, les tokens restent attribués à l'uploader initial (acceptable). |
| Tokens LLM d'ingestion | Désormais tracés (`token_type='llm'`), contrairement à la première version embedding-only. |
| Sous-comptage LLM par cache | Les appels LLM d'ingestion passent par un cache Redis keyé sur le contenu → un contenu déjà vu (tous tenants/datasets confondus) ne re-facture pas de tokens `llm`. Voir « Mise en cache LLM et sous-comptage » ci-dessus. L'embedding n'est pas concerné. |
| `provider` éventuellement vide | Rempli depuis la config du modèle quand disponible. |
| Sémantique partagée des colonnes | `resource_id`/`object_id` ont un sens différent selon `source` — toujours filtrer. |
