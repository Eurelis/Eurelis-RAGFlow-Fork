---
title: "Statistiques de consommation par utilisateur"
type: feature
status: implemented
reviewed: 2026-06-28
---

# Statistiques de consommation par utilisateur

**Dernière mise à jour :** 2026-06-22

> **Note refactoring `source`/`token_type`.** Ce document de suivi conserve sa valeur historique. Le modèle `usage_log` a depuis évolué : la colonne `source` ne contient plus que les **flux** `chat` · `search` · `agent` · `ingestion` (les anciens `chatbot`/`agentbot` sont fusionnés dans `chat`/`agent`), et une colonne `token_type` (`llm` · `embedding`) porte la nature du token. Les colonnes `dialog_id`/`session_id` sont renommées `resource_id`/`object_id`. Référence à jour : `docs/eurelis/specs/usage-stats/usage-log-table.md` et `docs/eurelis/specs/usage-stats/api-usage-stats-user.md`.

---

## TODO — Plan de mise en œuvre

- [x] **Bug 1** — Corriger `tenants[0].tenant_id` dans `/system/stats` → PR upstream [#16214](https://github.com/infiniflow/ragflow/pull/16214) ✅
- [x] **Bug 2** — Corriger le JOIN agent dans `API4ConversationService.stats()` (`dialog_id` pointe vers `user_canvas`, pas `dialog`) → PR upstream [#16215](https://github.com/infiniflow/ragflow/pull/16215) ✅
- [x] **Bug 3** — `tokens` et `duration` toujours à 0 : `append_message` n'incrémente que `round` → PR upstream [#16216](https://github.com/infiniflow/ragflow/pull/16216) ✅
- [x] **Étape 1** — Exposer `usage` dans `dialog_service.async_chat()` ✅
- [x] **Étape 2** — Table `usage_log` append-only ✅ : `UsageLog` + `UsageLogService`
- [x] **Étape 3** — Persistance des métriques ✅ : `UsageLogService.log()` câblé dans les 5 points de completion
- [x] **Étape 4** — `GET /api/v1/usage-stats/me` ✅ : endpoint utilisateur (période, totaux, by_day, by_usage) — `usage_stats_api.py`
- [x] **Étape 4+** — `GET /api/v1/usage-stats/me/session/{session_id}` ✅ : détail par tour (tokens, durée, modèle) — `usage_stats_api.py` + `UsageLogService.stats_for_session()`
- [x] **Étape 5** — `GET /api/v1/admin/stats/users` ✅ : liste agrégée des utilisateurs actifs — `admin/server/stats_routes.py`
- [x] **Étape 6** — `GET /api/v1/admin/stats/users/{user_email}` ✅ : détail par utilisateur (timeseries, by_usage) — `admin/server/stats_routes.py`
- [x] **Étape 9** — UI Admin RAGFlow ✅ : dashboard global (`stats.tsx`) + deep dive par utilisateur (`stats-user-detail.tsx`) avec i18n fr/en
- [x] **Étape 8 (partiel)** — UI utilisateur RAGFlow ✅ : page `/user-setting/stats` avec KPIs, graphiques, tableau par dialog — `pages/user-setting/stats/index.tsx`
- [x] **Étape 8 (suite)** — UI Shield : bloc de stats dans l'en-tête de conversation (tokens, durée, histogramme par tour) — spec : `conversation-stats-header/spec.md` dans Shield
- [ ] **Étape 7** — Endpoint Shield `GET /stats/me` : proxy + agrégation multi-serveurs RAGFlow
- [ ] **Ingestion** — Historisation des tokens d'embedding dans `usage_log` (`source='ingestion'`) — spec : `docs/eurelis/specs/usage-stats/usage-stats-ingestion.md`
- [ ] **Endpoints futurs** — `GET /usage-stats/me/timeseries` et `GET /usage-stats/me/breakdown?group_by=source|model` — spec : `docs/eurelis/specs/usage-stats/api-usage-stats-user.md`

---

## Bugs à corriger sur `/system/stats`

### Bug 1 — `tenants[0].tenant_id` arbitraire ✅ CORRIGÉ

**Fichier :** `api/apps/restful_apis/stats_api.py`

`UserTenantService.query(user_id=current_user.id)` retourne toutes les appartenances dans un ordre arbitraire. `tenants[0].tenant_id` peut pointer sur n'importe quel tenant, jamais sur le tenant propre de l'utilisateur.

**Fix :** utiliser `current_user.id` directement — invariant RAGFlow : le tenant principal d'un utilisateur a toujours le même ID que l'utilisateur.

→ PR upstream [#16214](https://github.com/infiniflow/ragflow/pull/16214)

---

### Bug 2 — JOIN cassé pour les sessions agents

**Fichier :** `api/db/services/api_service.py` — `API4ConversationService.stats()`

Pour les sessions agents (canvas), `api_4_conversation.dialog_id` pointe vers `user_canvas`, pas vers `dialog`. La query fait un `INNER JOIN dialog ON dialog_id = dialog.id` — ce JOIN ne matche jamais pour les agents. `GET /system/stats?canvas_id=xxx` retourne toujours vide.

**Fix :** distinguer le cas `source = "agent"` dans la query et joindre `user_canvas` à la place de `dialog`.

→ Candidat PR upstream

---

### Bug 3 — `tokens` et `duration` toujours à 0

**Fichier :** `api/db/services/api_service.py` — `API4ConversationService.append_message()`

`append_message` n'incrémente que le compteur `round`. Les champs `tokens` et `duration` de `API4Conversation` restent à 0 en base, ce qui rend les métriques `speed`, `tokens` de `/system/stats` inutiles.

**Prérequis :** exposer le dict `usage` dans `dialog_service.async_chat()` (Étape 1), puis le propager jusqu'à `append_message`.

→ Candidat PR upstream (lié à l'issue [#9146](https://github.com/infiniflow/ragflow/issues/9146))

---

### Bug Eurelis — Sessions Shield invisibles des stats ✅ CORRIGÉ

**Contexte :** Les sessions Shield (`chat_api.py` → table `conversation`) n'avaient aucune métrique de consommation, contrairement aux sessions iframe/agent (`api_4_conversation`).

**Fix (Étapes 2 & 3) :** table `usage_log` append-only (source unique, toutes surfaces) + `UsageLogService.log()` câblé dans les 5 points de completion (`chat`, `chatbot`, `agent`). Les données survivent à la suppression des conversations.

→ Voir spec : `docs/eurelis/specs/usage-stats/usage-log-table.md`

---

## Contexte

RAGFlow stocke les métriques de consommation par session dans deux tables distinctes selon le mode d'accès :

| Table                | Chemin d'accès                                              | Métriques                                   |
|----------------------|-------------------------------------------------------------|---------------------------------------------|
| `api_4_conversation` | iframe / chatbot (`POST /api/v1/chatbots/{id}/completions`) | `tokens`, `duration`, `round`, `thumb_up` ✅ |
| `conversation`       | Shield / RESTful (`POST /api/v1/chats/{id}/completions`)    | absentes (non modifiée)                     |
| **`usage_log`** ✅    | **toutes surfaces** (chat, chatbot, agent, agentbot)        | `tokens`, `duration` — append-only, pérenne |

L'endpoint existant `GET /system/stats` n'agrège que par tenant, sans filtre par utilisateur. Aucun endpoint ne permet à un utilisateur de consulter sa propre consommation. L'interface admin ne propose pas de vue par utilisateur.

L'objectif est d'exploiter la donnée déjà présente (ou à ajouter) en base pour exposer des statistiques à deux niveaux : **admin** (vue globale + deep dive) et **utilisateur** (consommation dans le Shield).

---

## État actuel des données

| Donnée                        | Stockée en DB                   | Exposée en API                 | Filtrée par user |
|-------------------------------|---------------------------------|--------------------------------|------------------|
| Nombre de sessions            | ✅                               | ✅ `/system/stats` (pv)         | ❌                |
| Utilisateurs uniques          | ✅                               | ✅ `/system/stats` (uv)         | ❌                |
| Tokens consommés              | ✅ `usage_log` (toutes surfaces) | ✅ `/system/stats` (toujours 0) | ❌ (Étape 4)      |
| Durée / vitesse               | ✅ `usage_log` (toutes surfaces) | ✅ `/system/stats` (toujours 0) | ❌ (Étape 4)      |
| Tours par session             | ✅ `api_4_conversation`          | ✅ `/system/stats`              | ❌                |
| Feedback (thumb up)           | ✅ `api_4_conversation`          | ✅ `/system/stats`              | ❌                |
| Stats par utilisateur         | ✅ `usage_log`                   | ❌                              | ❌ (Étape 4)      |
| Stats par chat                | ✅ `usage_log`                   | ❌                              | ❌ (Étape 4)      |
| Consommation session courante | ✅ `usage_log`                   | ❌                              | ❌ (Étape 4)      |

---

## Étape 1 — Champ `usage` dans la réponse de completion ✅

**Déjà implémenté** dans `api/db/services/dialog_service.py` :
- `async_chat()` : `usage` dict présent dans le chunk final (ligne ~917) avec `prompt_tokens`, `completion_tokens`, `total_tokens`, `duration_ms`, `tokens_per_second`
- `async_chat_solo()` : idem (ligne ~344), `prompt_tokens` corrigé par PR [#16216](https://github.com/infiniflow/ragflow/pull/16216)

`structure_answer()` propage le dict sans modification — `usage` est disponible dans la réponse API et dans `last_ans` / `final_answer` pour les appelants.

**Note upstream :** correspond à [issue #9146](https://github.com/infiniflow/ragflow/issues/9146).

---

## Étape 2 — Table `usage_log` (append-only) ✅

**Décision :** au lieu d'ajouter des colonnes à `conversation` (données perdues à la suppression), une table dédiée `usage_log` est créée. Elle est la source unique pour toutes les surfaces.

**Implémenté :**
- `class UsageLog(DataBaseModel)` dans `api/db/db_models.py` (après `API4Conversation`) — table `usage_log` auto-créée par `init_database_tables()` au démarrage
- `UsageLogService` dans `api/db/services/usage_log_service.py` — méthodes `log()`, `stats_for_user()`, `stats_all_users()`, `stats_by_day()`

→ Voir spec complète : `docs/eurelis/specs/usage-stats/usage-log-table.md`

---

## Étape 3 — Persistance des métriques après completion ✅

`UsageLogService.log()` câblé dans les 5 points de completion :

| Point | Fichier                                                           | Source loguée                  |
|-------|-------------------------------------------------------------------|--------------------------------|
| C1    | `chat_api.py` — streaming `finally`                               | `chat`                         |
| C2    | `chat_api.py` — non-streaming                                     | `chat`                         |
| C3    | `conversation_service.py:async_iframe_completion` — streaming     | `chatbot`                      |
| C4    | `conversation_service.py:async_iframe_completion` — non-streaming | `chatbot`                      |
| C5    | `agent_api.py:_run_workflow_session`                              | `agent` (tokens=0 placeholder) |

Le `finally` en C1 garantit l'écriture même si le client se déconnecte à mi-stream (`GeneratorExit`).

---

## Étape 4 — `GET /api/v1/stats/me`

**Fichier :** `api/apps/restful_apis/stats_api.py`

Endpoint authentifié (API key ou JWT RAGFlow), retournant la consommation de l'utilisateur courant.

### Résolution du `user_id`

Le Shield authentifie avec la clé API de l'utilisateur connecté — pas un compte de service. `current_user` est donc toujours l'utilisateur final, que la requête vienne de l'UI, d'un JWT ou du Shield. `current_user.id` est systématiquement correct.

```python
@manager.route("/api/v1/stats/me", methods=["GET"])
@login_required
def stats_me():
    user_id = current_user.id  # correct dans tous les cas
    ...
```

**Stockage :** dans la table `conversation` (sessions Shield), `chat_api.py:802` enregistre `"user_id": current_user.id` — cohérent avec le filtrage.

### Route

```
GET /api/v1/stats/me
    ?session_id=<id>   (optionnel)
    ?from_date=...     (optionnel, défaut : 1er du mois courant)
    ?to_date=...       (optionnel, défaut : maintenant)
```

La query cible `usage_log` filtrée par `user_id == current_user.id`, avec agrégation par période via `UsageLogService.stats_for_user()`. Source unique pour toutes les surfaces (chat, chatbot, agent).

**Note sur `user_id` :** pour les sessions chatbot iframe, `user_id` est ce que le client passe librement (sub Keycloak ou chaîne vide). Pour les sessions Shield (`source="chat"`), `user_id = current_user.id` — fiable.

### Réponse

```json
{
  "user_id": "550e8400e29b41d4a716446655440000",
  "today": {
    "sessions": 5,
    "tokens": 2100,
    "avg_duration_ms": 2800
  },
  "this_week": {
    "sessions": 18,
    "tokens": 7400,
    "avg_duration_ms": 3100
  },
  "this_month": {
    "sessions": 42,
    "tokens": 18500,
    "avg_duration_ms": 3200
  },
  "current_session": {
    "session_id": "...",
    "tokens": 340,
    "round": 4,
    "duration_ms": 8500,
    "thumb_up": 0
  }
}
```

`current_session` n'est présent que si `session_id` est fourni.

---

## Étapes 5 & 6 — Endpoints admin

**Fichiers :** `admin/server/routes.py` + `admin/server/services.py`

Nouveau `UserStatsMgr` dans `admin/server/services.py` avec deux méthodes :

### `GET /api/v1/admin/stats/users`

```
GET /api/v1/admin/stats/users
    ?from_date=2026-05-01
    ?to_date=2026-05-31
    ?chat_id=<dialog_id>    (optionnel)
    ?sort_by=tokens|sessions|thumb_up   (optionnel, défaut: tokens)
    ?limit=50               (optionnel, défaut: 50)
```

```json
[
  {
    "user_id": "550e8400e29b41d4a716446655440000",
    "sessions": 42,
    "tokens": 18500,
    "avg_duration_ms": 3200,
    "avg_round": 4.1,
    "thumb_up": 12
  }
]
```

### `GET /api/v1/admin/stats/users/{user_id}`

```
GET /api/v1/admin/stats/users/{user_id}
    ?from_date=...&to_date=...
```

```json
{
  "user_id": "...",
  "period": { "from": "2026-05-01", "to": "2026-05-31" },
  "totals": {
    "sessions": 42,
    "tokens": 18500,
    "avg_duration_ms": 3200,
    "avg_round": 4.1,
    "thumb_up": 12
  },
  "by_chat": [
    { "dialog_id": "...", "dialog_name": "Assistant général", "sessions": 20, "tokens": 9000, "avg_round": 3.8 }
  ],
  "by_day": [
    { "date": "2026-05-01", "sessions": 3, "tokens": 1200 }
  ]
}
```

---

## Étape 7 — Endpoint Shield `GET /stats/me`

Le Shield expose un endpoint proxy vers `GET /api/v1/stats/me` de RAGFlow, enrichi du contexte multi-serveurs :

```
GET /stats/me
    ?session_id=<namespaced_session_id>   (optionnel)
```

Le Shield agrège les réponses de chaque serveur RAGFlow et consolide :

```json
{
  "today":      { "sessions": 7,  "tokens": 3200 },
  "this_week":  { "sessions": 22, "tokens": 9800 },
  "this_month": { "sessions": 51, "tokens": 24000 },
  "by_server": {
    "common":  { "today": { "sessions": 4, "tokens": 1800 } },
    "dept-rh": { "today": { "sessions": 3, "tokens": 1400 } }
  },
  "current_session": { "tokens": 340, "round": 4, "duration_ms": 8500 }
}
```

---

## Étape 8 — UI Shield

**Page d'accueil :**
- Widgets "aujourd'hui / cette semaine / ce mois" (tokens, sessions)
- Indicateur de tendance vs période précédente

**Dans le fil de conversation :**
- Compteur de tokens de la session courante (mise à jour après chaque réponse)
- Durée de réponse du dernier tour

---

## Étape 9 — UI Admin RAGFlow

**Composant :** nouvelle page dans `web/src/pages/admin/` (ou section dans le dashboard existant)

**Overview globale :** graphe d'activité journalière, top utilisateurs par tokens, top chats par sessions, répartition feedbacks, métriques de performance.

**Deep dive par utilisateur :** identité, courbe de consommation, breakdown par chat, sessions récentes avec tokens/durée/feedback.

---

## Relation avec l'upstream

| Issue                                                        | Titre                                        | État                    | Action                                                                           |
|--------------------------------------------------------------|----------------------------------------------|-------------------------|----------------------------------------------------------------------------------|
| [#9146](https://github.com/infiniflow/ragflow/issues/9146)   | Usage object from RAG-enabled endpoint       | OPEN, sans assigné      | PR upstream — exposer `usage` dans `dialog_service.async_chat()`                 |
| [#11576](https://github.com/infiniflow/ragflow/issues/11576) | Token usage and timing for agents            | OPEN, assigné à Wang Qi | Implémenter le total dans le fork ; attendre upstream pour le breakdown par nœud |
| [#12241](https://github.com/infiniflow/ragflow/issues/12241) | Admin dashboard                              | Backlog, non planifié   | Développer dans le fork Eurelis (per-user non prévu upstream)                    |
| [#16214](https://github.com/infiniflow/ragflow/pull/16214)   | fix(stats): use current_user.id as tenant_id | OPEN                    | Bug 1 — PR soumise                                                               |

### Agents — token usage

Ajouter le total tokens + durée totale dans la réponse des agents (`api/apps/restful_apis/agent_api.py`), sur le même modèle que l'Étape 1. Le breakdown par nœud (durée par composant du canvas) est **hors périmètre** — à laisser à l'upstream ([#11576](https://github.com/infiniflow/ragflow/issues/11576)).

---

## Dépendances

| Étape              | Dépend de                                        |
|--------------------|--------------------------------------------------|
| ~~Bug 3~~ ✅        | ~~Étape 1~~ ✅                                    |
| ~~Étapes 2 & 3~~ ✅ | ~~Étape 1~~ ✅                                    |
| Étape 4            | Étapes 2 & 3 ✅ (`usage_log` + `UsageLogService`) |
| Étapes 5 & 6       | Étape 4                                          |
| Étape 7 Shield     | Étape 4                                          |
| Étape 8 UI Shield  | Étape 7                                          |
| Étape 9 UI Admin   | Étapes 5 & 6                                     |

**Dépendances externes :**
- Shield multi-serveurs (`key_attr`, routing par `server_id`) — requis pour l'agrégation Shield (Étape 7)
- `session_id` namespaced (`server_id__original_id`) — requis pour que `current_session` soit resolvable par le Shield

Voir : `docs/integration/keycloak-authentication.md`

---

## Hors périmètre

- Breakdown par nœud pour les agents — upstream [#11576](https://github.com/infiniflow/ragflow/issues/11576)
- Stats Langfuse par `user_id` / `session_id` — voir `docs/eurelis/features/roadmap/langfuse-session-user-integration.md`
