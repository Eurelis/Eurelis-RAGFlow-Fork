# Spec — API statistiques de consommation & dashboard admin

**Branche :** `eurelis/feature/usage-stats`
**Dépend de :** `docs/eurelis/specs/usage-log-table.md` (table `usage_log` ✅ implémentée)

> **⚠ Mise à jour — modèle actuel (fait autorité).** Depuis le refactoring `source`/`token_type`, `usage_log` expose deux dimensions orthogonales :
> - `source` (flux) : **`chat` · `search` · `agent` · `ingestion`** (les anciens `chatbot`/`agentbot` sont fusionnés dans `chat`/`agent` ; `ingestion_llm` et `query_embedding` n'existent plus).
> - `token_type` (nature) : **`llm` · `embedding`**.
>
> Les colonnes `dialog_id`/`session_id` ont été renommées **`resource_id`/`object_id`**. Les endpoints admin (`/api/v1/admin/stats/*`) et utilisateur (`/api/v1/usage-stats/me/*`) acceptent les filtres `source` **et** `type`, le décompte `by_source`/`by_type`, et `group_by=source|type|model|dialog`. Voir `usage-log-table.md` et `api-usage-stats-user.md` pour la référence à jour.
>
> Les sections ci-dessous conservent la valeur historique de conception ; en cas de divergence, le modèle ci-dessus prévaut.

---

## Vue d'ensemble

| Livrable                                  | Étape roadmap | Fichiers RAGFlow | Fichiers Shield               |
|-------------------------------------------|---------------|------------------|-------------------------------|
| `GET /api/v1/stats/me`                    | Étape 4       | `stats_api.py`   | —                             |
| `GET /api/v1/admin/stats/users`           | Étape 5       | `stats_api.py`   | —                             |
| `GET /api/v1/admin/stats/users/{user_id}` | Étape 6       | `stats_api.py`   | —                             |
| `GET /api/v1/admin/stats/timeseries`      | Étape 5       | `stats_api.py`   | —                             |
| `GET /api/v1/admin/stats/breakdown`       | Étape 5       | `stats_api.py`   | —                             |
| Dashboard admin RAGFlow                   | Étape 9       | `web/src/pages/` | —                             |
| `GET /stats/me` (Shield)                  | Étape 7       | —                | `backend/app/routes/stats.py` |
| `GET /stats/sessions/{id}` (Shield)       | Étape 7       | —                | `backend/app/routes/stats.py` |
| UI Shield — widgets de consommation       | Étape 8       | —                | `frontend/chatbot_ui/`        |

---

## TODO — Suivi d'implémentation

### Phase 1 — `UsageLogService` : méthodes analytiques ✅

- [x] `stats_timeseries(from_date, to_date, granularity, user_id, source)` — évolution temporelle par période
- [x] `stats_by_source(from_date, to_date, user_id)` — répartition par flux (chat / search / agent / ingestion)
- [x] `stats_by_model(from_date, to_date, user_id, source)` — répartition modèle / fournisseur avec `pct_tokens`
- [x] `stats_by_usage(from_date, to_date, user_id)` — breakdown par chat
- [x] Enrichir `stats_all_users()` — ajouter `active_users` (COUNT DISTINCT) et `sources` (GROUP_CONCAT)

### Phase 2 — Endpoints admin RAGFlow ✅

- [x] `GET /api/v1/admin/stats/timeseries` — série temporelle, `granularity` auto
- [x] `GET /api/v1/admin/stats/breakdown?group_by=source|model` — répartition avec pourcentages
- [x] `GET /api/v1/admin/stats/users` — top utilisateurs enrichis (email, sources)
- [x] `GET /api/v1/admin/stats/users/{user_id}` — détail + `by_day` + `by_usage`

### Phase 3 — Dashboard admin RAGFlow (frontend) ✅

- [x] **3a** Service stats dans `admin-service.ts` (fonctions + types) + URLs dans `api.ts`
- [x] **3b** Charts intégrés dans les pages (BarChart tokens, PieChart source, BarChart horizontal modèles)
- [x] **3c** Page overview `web/src/pages/admin/stats.tsx`
- [x] **3d** Page détail `web/src/pages/admin/stats-user-detail.tsx`
- [x] **3e** Routing (`Routes.AdminStats`, `Routes.AdminStatsUserDetail`) + entrée sidebar "Usage statistics"

### Phase 4 — Endpoint utilisateur ✅

- [x] `GET /api/v1/stats/me` — today / this_week / period + `current_session` optionnel

### Phase 5 — Shield : endpoints stats

- [ ] `GET /stats/me` — agrégation parallèle multi-serveurs
- [ ] `GET /stats/sessions/{namespaced_id}` — stats d'une session

### Phase 6 — Shield : UI widgets

- [ ] Widget consommation page d'accueil (today / semaine / mois)
- [ ] Compteur tokens session dans le fil de conversation (accumulation SSE)

---

## Axes d'analyse

Le dashboard doit permettre de croiser 4 dimensions indépendantes.

| Axe                      | Champ `usage_log`    | Valeurs possibles                         |
|--------------------------|----------------------|-------------------------------------------|
| **Échelle de temps**     | `create_date`        | jour / semaine / mois (12 mois glissants) |
| **Utilisateur**          | `user_id`            | un ou tous                                |
| **Flux**                 | `source`             | `chat` · `search` · `agent` · `ingestion` |
| **Nature du token**      | `token_type`         | `llm` · `embedding`                       |
| **Modèle / fournisseur** | `model` · `provider` | ex. `claude-sonnet-4-6` · `Bedrock`       |

### Conventions de période

| Libellé UI        | `from_date`                  | `to_date`   | `granularity`                                        |
|-------------------|------------------------------|-------------|------------------------------------------------------|
| Cette semaine     | lundi de la semaine courante | aujourd'hui | `day`                                                |
| Ce mois           | 1er du mois courant          | aujourd'hui | `day`                                                |
| 12 mois glissants | il y a 365 jours             | aujourd'hui | `month`                                              |
| Personnalisé      | libre                        | libre       | auto (≤31j → `day`, ≤365j → `week`, >365j → `month`) |

### Granularité SQL (Peewee)

```python
GRANULARITY_FN = {
    "day":   lambda f: peewee.fn.DATE(f),                          # YYYY-MM-DD
    "week":  lambda f: peewee.fn.DATE_FORMAT(f, "%Y-%u"),          # YYYY-WW
    "month": lambda f: peewee.fn.DATE_FORMAT(f, "%Y-%m"),          # YYYY-MM
}
```

---

## 1. Endpoints RAGFlow

### 1.1 Authentification

Tous les endpoints ci-dessous utilisent l'authentification standard RAGFlow :

- **JWT** (header `Authorization: Bearer <token>`) — sessions Shield / UI
- **API Key** (header `Authorization: Bearer <api_key>`) — intégrations programmatiques

Les endpoints `/admin/stats/*` requièrent en plus `current_user.is_superuser == True`.

### 1.2 `GET /api/v1/stats/me`

Consommation de l'utilisateur authentifié, lue depuis `usage_log`.

**Fichier :** `api/apps/restful_apis/stats_api.py` — ajouter sous le blueprint `manager`

#### Paramètres

| Paramètre    | Type         | Défaut              | Description                                         |
|--------------|--------------|---------------------|-----------------------------------------------------|
| `from_date`  | `YYYY-MM-DD` | 1er du mois courant | Début de la période                                 |
| `to_date`    | `YYYY-MM-DD` | aujourd'hui         | Fin de la période (inclusif)                        |
| `session_id` | string       | —                   | Si fourni, ajoute `current_session` dans la réponse |

#### Implémentation

```python
@manager.route('/api/v1/stats/me', methods=['GET'])
@login_required
async def stats_me():
    from datetime import date, timedelta
    from api.db.services.usage_log_service import UsageLogService

    today = date.today()
    from_date = request.args.get("from_date", today.replace(day=1).isoformat())
    to_date = request.args.get("to_date", today.isoformat())
    session_id = request.args.get("session_id")
    user_id = current_user.id

    period = UsageLogService.stats_for_user(user_id, from_date, to_date)
    today_stats = UsageLogService.stats_for_user(
        user_id, today.isoformat(), today.isoformat()
    )
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    week_stats = UsageLogService.stats_for_user(user_id, week_start, today.isoformat())

    result = {
        "user_id": user_id,
        "period": {"from": from_date, "to": to_date, **period},
        "today": today_stats,
        "this_week": week_stats,
    }
    if session_id:
        session_stats = UsageLogService.stats_for_user(
            user_id, "2000-01-01", today.isoformat(), session_id=session_id
        )
        result["current_session"] = {"session_id": session_id, **session_stats}

    return get_json_result(data=result)
```

#### Réponse — `200 OK`

```json
{
  "code": 0,
  "data": {
    "user_id": "550e8400e29b41d4a716446655440000",
    "period": {
      "from": "2026-06-01",
      "to": "2026-06-21",
      "sessions": 42,
      "tokens": 18500,
      "avg_duration_ms": 3200.0
    },
    "today": {
      "sessions": 5,
      "tokens": 2100,
      "avg_duration_ms": 2800.0
    },
    "this_week": {
      "sessions": 18,
      "tokens": 7400,
      "avg_duration_ms": 3100.0
    },
    "current_session": {
      "session_id": "abc123",
      "sessions": 4,
      "tokens": 340,
      "avg_duration_ms": 2125.0
    }
  }
}
```

> **Note :** `current_session.sessions` est le nombre de tours (une entrée `usage_log` par tour).
> `current_session` est absent si `session_id` n'est pas fourni.

#### Erreurs

| Code HTTP | Cas                    |
|-----------|------------------------|
| 401       | Token absent ou expiré |
| 500       | Erreur DB              |

---

### 1.3 `GET /api/v1/admin/stats/users`

Liste agrégée de tous les utilisateurs, triée par consommation.

#### Paramètres

| Paramètre   | Type                                | Défaut              | Description         |
|-------------|-------------------------------------|---------------------|---------------------|
| `from_date` | `YYYY-MM-DD`                        | 1er du mois courant | —                   |
| `to_date`   | `YYYY-MM-DD`                        | aujourd'hui         | —                   |
| `dialog_id` | string                              | —                   | Filtre par chat     |
| `sort_by`   | `tokens\|sessions\|avg_duration_ms` | `tokens`            | Tri décroissant     |
| `limit`     | int 1–500                           | `50`                | Nombre de résultats |

#### Implémentation

```python
@manager.route('/api/v1/admin/stats/users', methods=['GET'])
@login_required
async def admin_stats_users():
    if not current_user.is_superuser:
        return get_data_error_result(message="Admin only", code=403)

    today = date.today()
    from_date = request.args.get("from_date", today.replace(day=1).isoformat())
    to_date = request.args.get("to_date", today.isoformat())
    dialog_id = request.args.get("dialog_id") or None
    sort_by = request.args.get("sort_by", "tokens")
    limit = min(int(request.args.get("limit", 50)), 500)

    rows = UsageLogService.stats_all_users(from_date, to_date, dialog_id, sort_by, limit)
    return get_json_result(data=rows)
```

#### Réponse — `200 OK`

```json
{
  "code": 0,
  "data": [
    {
      "user_id": "550e8400e29b41d4a716446655440000",
      "sessions": 42,
      "tokens": 18500,
      "avg_duration_ms": 3200.0
    },
    {
      "user_id": "661f9511f3ac52e5b827557766551111",
      "sessions": 28,
      "tokens": 11200,
      "avg_duration_ms": 2900.0
    }
  ]
}
```

#### Erreurs

| Code HTTP | Cas                                     |
|-----------|-----------------------------------------|
| 401       | Non authentifié                         |
| 403       | Non admin                               |
| 400       | `sort_by` invalide, `limit` hors bornes |

---

### 1.4 `GET /api/v1/admin/stats/users/{user_id}`

Détail complet pour un utilisateur : totaux, breakdown par chat, courbe journalière.

#### Paramètres

| Paramètre   | Type         | Défaut              | Description |
|-------------|--------------|---------------------|-------------|
| `from_date` | `YYYY-MM-DD` | 1er du mois courant | —           |
| `to_date`   | `YYYY-MM-DD` | aujourd'hui         | —           |

#### Implémentation

```python
@manager.route('/api/v1/admin/stats/users/<user_id>', methods=['GET'])
@login_required
async def admin_stats_user_detail(user_id):
    if not current_user.is_superuser:
        return get_data_error_result(message="Admin only", code=403)

    today = date.today()
    from_date = request.args.get("from_date", today.replace(day=1).isoformat())
    to_date = request.args.get("to_date", today.isoformat())

    totals = UsageLogService.stats_for_user(user_id, from_date, to_date)
    by_day = UsageLogService.stats_by_day(user_id, from_date, to_date)
    by_dialog = UsageLogService.stats_by_usage(user_id, from_date, to_date)  # à ajouter

    return get_json_result(data={
        "user_id": user_id,
        "period": {"from": from_date, "to": to_date},
        "totals": totals,
        "by_day": by_day,
        "by_dialog": by_dialog,
    })
```

> **À ajouter dans `UsageLogService`** : méthode `stats_by_usage()` — GROUP BY `dialog_id` sur la période.

#### Réponse — `200 OK`

```json
{
  "code": 0,
  "data": {
    "user_id": "550e8400e29b41d4a716446655440000",
    "period": { "from": "2026-06-01", "to": "2026-06-21" },
    "totals": {
      "sessions": 42,
      "tokens": 18500,
      "avg_duration_ms": 3200.0
    },
    "by_day": [
      { "date": "2026-06-01", "sessions": 3, "tokens": 1200 },
      { "date": "2026-06-02", "sessions": 2, "tokens": 800 }
    ],
    "by_dialog": [
      {
        "dialog_id": "d1a2b3c4",
        "sessions": 20,
        "tokens": 9000,
        "avg_duration_ms": 3100.0
      },
      {
        "dialog_id": "e5f6a7b8",
        "sessions": 22,
        "tokens": 9500,
        "avg_duration_ms": 3300.0
      }
    ]
  }
}
```

> **Note :** `dialog_id` peut valoir un `canvas_id` pour les sessions agent (source `"agent"`).
> Si nécessaire, enrichir avec le `dialog_name` via `DialogService.get_by_id()`.

---

### 1.5 Méthode `stats_by_usage()` à ajouter dans `UsageLogService`

```python
@classmethod
@DB.connection_context()
def stats_by_usage(
    cls,
    user_id: str,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """Breakdown par dialog_id pour un utilisateur."""
    return list(
        cls.model
        .select(
            cls.model.dialog_id,
            peewee.fn.COUNT(cls.model.id).alias("sessions"),
            peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
            peewee.fn.COALESCE(
                peewee.fn.AVG(cls.model.duration), 0.0
            ).alias("avg_duration_ms"),
        )
        .where(
            cls.model.user_id == user_id,
            cls.model.create_date >= from_date,
            cls.model.create_date <= to_date,
        )
        .group_by(cls.model.dialog_id)
        .order_by(peewee.SQL("tokens").desc())
        .dicts()
    )
```

---

### 1.6 `GET /api/v1/admin/stats/timeseries`

Évolution temporelle globale (tous utilisateurs) selon une granularité choisie.
Sert le graphe principal du dashboard overview.

#### Paramètres

| Paramètre     | Type                             | Défaut          | Description                                   |
|---------------|----------------------------------|-----------------|-----------------------------------------------|
| `from_date`   | `YYYY-MM-DD`                     | il y a 30 jours | —                                             |
| `to_date`     | `YYYY-MM-DD`                     | aujourd'hui     | —                                             |
| `granularity` | `day\|week\|month`               | auto            | `day` si ≤31j, `week` si ≤365j, `month` sinon |
| `source`      | `chat\|chatbot\|agent\|agentbot` | —               | Filtre par type d'usage                       |
| `user_id`     | string                           | —               | Filtre sur un utilisateur                     |

#### Réponse — `200 OK`

```json
{
  "code": 0,
  "data": {
    "granularity": "month",
    "series": [
      { "period": "2025-07", "sessions": 120, "tokens": 48000 },
      { "period": "2025-08", "sessions": 145, "tokens": 58000 },
      { "period": "2026-06", "sessions": 198, "tokens": 82000 }
    ]
  }
}
```

#### Méthode `UsageLogService.stats_timeseries()` à créer

```python
@classmethod
@DB.connection_context()
def stats_timeseries(
    cls,
    from_date: str,
    to_date: str,
    granularity: str = "day",
    user_id: str | None = None,
    source: str | None = None,
) -> list[dict]:
    period_fn = GRANULARITY_FN.get(granularity, GRANULARITY_FN["day"])
    q = (
        cls.model
        .select(
            period_fn(cls.model.create_date).alias("period"),
            peewee.fn.COUNT(cls.model.id).alias("sessions"),
            peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
        )
        .where(
            cls.model.create_date >= from_date,
            cls.model.create_date <= to_date,
        )
        .group_by(peewee.SQL("period"))
        .order_by(peewee.SQL("period"))
    )
    if user_id:
        q = q.where(cls.model.user_id == user_id)
    if source:
        q = q.where(cls.model.source == source)
    return list(q.dicts())
```

---

### 1.7 `GET /api/v1/admin/stats/breakdown`

Répartition par axe : source (usage) ou modèle/fournisseur.
Sert les graphes donut/barres du dashboard.

#### Paramètres

| Paramètre   | Type                      | Défaut              | Description                                        |
|-------------|---------------------------|---------------------|----------------------------------------------------|
| `from_date` | `YYYY-MM-DD`              | 1er du mois courant | —                                                  |
| `to_date`   | `YYYY-MM-DD`              | aujourd'hui         | —                                                  |
| `group_by`  | `source\|model\|provider` | `source`            | Axe de regroupement                                |
| `user_id`   | string                    | —                   | Filtre sur un utilisateur                          |
| `source`    | string                    | —                   | Filtre source (disponible si `group_by != source`) |

#### Réponse — `group_by=source`

```json
{
  "code": 0,
  "data": {
    "group_by": "source",
    "items": [
      { "label": "chat",     "sessions": 310, "tokens": 128000, "pct_tokens": 52.3 },
      { "label": "agent",    "sessions": 180, "tokens": 95000,  "pct_tokens": 38.8 },
      { "label": "chatbot",  "sessions": 42,  "tokens": 21700,  "pct_tokens": 8.9  }
    ]
  }
}
```

#### Réponse — `group_by=model`

```json
{
  "code": 0,
  "data": {
    "group_by": "model",
    "items": [
      { "label": "claude-sonnet-4-6", "provider": "Bedrock", "sessions": 280, "tokens": 115000, "pct_tokens": 47.0 },
      { "label": "gpt-4o",            "provider": "OpenAI",  "sessions": 150, "tokens": 72000,  "pct_tokens": 29.4 },
      { "label": "mistral-large",     "provider": "Mistral", "sessions": 102, "tokens": 57700,  "pct_tokens": 23.6 }
    ]
  }
}
```

#### Méthodes `UsageLogService` à créer

```python
@classmethod
@DB.connection_context()
def stats_by_source(
    cls,
    from_date: str,
    to_date: str,
    user_id: str | None = None,
) -> list[dict]:
    q = (
        cls.model
        .select(
            cls.model.source.alias("label"),
            peewee.fn.COUNT(cls.model.id).alias("sessions"),
            peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
        )
        .where(cls.model.create_date >= from_date, cls.model.create_date <= to_date)
        .group_by(cls.model.source)
        .order_by(peewee.SQL("tokens").desc())
    )
    if user_id:
        q = q.where(cls.model.user_id == user_id)
    rows = list(q.dicts())
    total = sum(r["tokens"] for r in rows) or 1
    for r in rows:
        r["pct_tokens"] = round(r["tokens"] / total * 100, 1)
    return rows


@classmethod
@DB.connection_context()
def stats_by_model(
    cls,
    from_date: str,
    to_date: str,
    user_id: str | None = None,
    source: str | None = None,
) -> list[dict]:
    q = (
        cls.model
        .select(
            cls.model.model.alias("label"),
            cls.model.provider,
            peewee.fn.COUNT(cls.model.id).alias("sessions"),
            peewee.fn.COALESCE(peewee.fn.SUM(cls.model.tokens), 0).alias("tokens"),
        )
        .where(cls.model.create_date >= from_date, cls.model.create_date <= to_date)
        .group_by(cls.model.model, cls.model.provider)
        .order_by(peewee.SQL("tokens").desc())
    )
    if user_id:
        q = q.where(cls.model.user_id == user_id)
    if source:
        q = q.where(cls.model.source == source)
    rows = list(q.dicts())
    total = sum(r["tokens"] for r in rows) or 1
    for r in rows:
        r["pct_tokens"] = round(r["tokens"] / total * 100, 1)
    return rows
```

---

## 2. Dashboard admin RAGFlow (Étape 9)

### 2.1 Route

Nouvelle page dans le panneau d'administration RAGFlow. Visible uniquement pour les superusers.

**Chemin frontend :** `web/src/pages/admin/Stats/index.tsx`
**Route :** `/admin/stats` (à ajouter dans le routeur)
**Entrée de menu :** section "Administration" dans la sidebar

### 2.2 Composants

#### Page principale — liste des utilisateurs

```
┌─────────────────────────────────────────────────────────────────┐
│ Statistiques de consommation                                    │
│                                                                 │
│ [Du: 2026-06-01] [Au: 2026-06-21]  [Trier par: Tokens ▾]      │
│ [Chat: tous ▾]                                                  │
│                                                                 │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ Utilisateur        Sessions  Tokens    Durée moy.  Source│   │
│ │ user@example.com   42        18 500    3,2 s       chat  │   │
│ │ other@example.com  28        11 200    2,9 s       mixed │   │
│ └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

- **DateRangePicker** → paramètres `from_date` / `to_date`
- **Select** tri → `sort_by` (tokens / sessions / durée)
- **Select** chat → `dialog_id` optionnel
- **Table** cliquable → ouvre la vue détail

#### Vue détail par utilisateur

```
┌─────────────────────────────────────────────────────────────────┐
│ ← Retour                user@example.com                       │
│                                                                 │
│  42 sessions   18 500 tokens   3,2 s moy.  (juin 2026)        │
│                                                                 │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │   Tokens / jour                                          │   │
│ │   [graphe en barres]                                     │   │
│ └──────────────────────────────────────────────────────────┘   │
│                                                                 │
│ Par chat                                                        │
│ ┌──────────────────────────────────────────────────────────┐   │
│ │ Chat                  Sessions  Tokens    Durée moy.     │   │
│ │ Assistant général     20        9 000     3,1 s          │   │
│ │ Support client        22        9 500     3,3 s          │   │
│ └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 Hooks à créer

```typescript
// web/src/hooks/use-admin-stats-request.ts
export function useAdminUsersStats(params: AdminStatsParams) { ... }
export function useAdminUserDetail(userId: string, params: DateRangeParams) { ... }
```

---

## 3. Dashboard admin — Visualisation (Étape 9)

### 3.1 Bibliothèques disponibles

| Lib                                | Version | Déjà utilisée dans                                 |
|------------------------------------|---------|----------------------------------------------------|
| `recharts`                         | ^2.12.4 | `line-chart/index.tsx`, `task-executor-detail.tsx` |
| shadcn/ui `Card`, `Tabs`, `Select` | —       | pages admin existantes                             |
| `dayjs`                            | —       | formatage des axes                                 |
| shadcn/ui `Table`                  | —       | `users.tsx`, `whitelist.tsx`                       |

Pas de nouvelle dépendance à installer.

---

### 3.2 Architecture globale du dashboard

Le dashboard est composé de **deux pages** et d'une **barre de contrôle partagée**.

```
/admin/stats                    → page overview (vue globale)
/admin/stats/users/:userId      → page détail par utilisateur
```

**Barre de contrôle (partagée)** — filtre tous les graphes simultanément :

```
┌─────────────────────────────────────────────────────────────────────┐
│  [Cette semaine ▾]  [Mois courant ▾]  [12 mois ▾]  [Personnalisé] │
│  [Usage : tous ▾]   [Fournisseur : tous ▾]                         │
└─────────────────────────────────────────────────────────────────────┘
```

| Contrôle    | Type                           | Valeurs                                                    | Action                                        |
|-------------|--------------------------------|------------------------------------------------------------|-----------------------------------------------|
| Période     | `SegmentedControl` ou `Select` | Cette semaine / Ce mois / 12 mois glissants / Personnalisé | Calcule `from_date`, `to_date`, `granularity` |
| Usage       | `Select`                       | Tous · Chat · Chatbot · Agent                              | Paramètre `source`                            |
| Fournisseur | `Select`                       | Tous · Bedrock · OpenAI · Mistral · …                      | Filtre client-side sur `provider`             |

La granularité est **auto-calculée** selon la période :
- ≤ 31 jours → `day` (barres par jour)
- 32 – 365 jours → `week` (barres par semaine)
- > 365 jours → `month` (barres par mois)

---

### 3.3 Page overview — `/admin/stats`

**Fichier :** `web/src/pages/admin/stats.tsx`

#### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  Statistiques de consommation                                       │
│  [Cette semaine ▾]  [Usage: tous ▾]  [Fournisseur: tous ▾]         │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │  Utilisateurs│  │ Sessions     │  │ Tokens       │             │
│  │      12      │  │     51       │  │   24 000     │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│                                                                     │
│  ┌──────────────────────────────┐  ┌──────────────────────────┐   │
│  │  Tokens (par période)        │  │  Répartition par usage   │   │
│  │                              │  │                          │   │
│  │  ▄▄  ▄   ▄▄▄  ▄  ▄   ▄▄    │  │     ██ Chat 52%          │   │
│  │  ██  █   ███  █  █   ██    │  │    ░░ Agent 39%          │   │
│  │  ─────────────────────────  │  │    ░░ Chatbot 9%         │   │
│  └──────────────────────────────┘  └──────────────────────────┘   │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Répartition par modèle / fournisseur                        │  │
│  │  claude-sonnet-4-6 (Bedrock) ████████████████░░  47%        │  │
│  │  gpt-4o (OpenAI)             ████████████░░░░░░  29%        │  │
│  │  mistral-large (Mistral)     ████████░░░░░░░░░░  24%        │  │
│  └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌──────────────────────────────────────────────────────────────┐  │
│  │  Top utilisateurs                    [Trier ▾ Tokens]        │  │
│  │  Utilisateur        Sessions  Tokens  Usage       Durée moy. │  │
│  │  user@example.com   42        18 500  chat/agent  3,2 s  →   │  │
│  │  other@acme.com     28        11 200  chat        2,9 s  →   │  │
│  └──────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

#### KPI cards (3 cartes)

| Métrique            | Source                                                                       | Format                         |
|---------------------|------------------------------------------------------------------------------|--------------------------------|
| Utilisateurs actifs | `COUNT(DISTINCT user_id)` — nouveau champ à ajouter dans `stats_all_users()` | entier                         |
| Sessions            | `SUM(sessions)`                                                              | entier                         |
| Tokens              | `SUM(tokens)`                                                                | `XX XXX` (séparateur milliers) |

#### Graphe 1 — Évolution des tokens (`BarChart`)

**Endpoint :** `GET /api/v1/admin/stats/timeseries`
**Paramètres :** période + granularity auto + filtre source

```tsx
// Axe X : period (YYYY-MM-DD / YYYY-WW / YYYY-MM selon granularité)
// Axe Y : tokens (formatter → "Xk")
// Tooltip : "X tokens · Y sessions"
// Couleur : hsl(var(--colors-blue-500))
<Bar dataKey="tokens" fill="hsl(var(--colors-blue-500))" radius={[4,4,0,0]} />
```

#### Graphe 2 — Répartition par usage (`PieChart` / donut)

**Endpoint :** `GET /api/v1/admin/stats/breakdown?group_by=source`

```tsx
import { Cell, Pie, PieChart, Tooltip, Legend } from 'recharts';

const SOURCE_COLORS = {
  chat:     'hsl(var(--colors-blue-500))',
  agent:    'hsl(var(--colors-purple-500))',
  chatbot:  'hsl(var(--colors-green-500))',
  agentbot: 'hsl(var(--colors-orange-500))',
};

<PieChart>
  <Pie data={sourceData} dataKey="tokens" innerRadius="55%" outerRadius="80%">
    {sourceData.map((entry) => (
      <Cell key={entry.label} fill={SOURCE_COLORS[entry.label] ?? '#ccc'} />
    ))}
  </Pie>
  <Tooltip formatter={(v: number, name) => [`${v.toLocaleString()} tokens`, name]} />
  <Legend />
</PieChart>
```

**Données :** `items[].label` (source), `items[].tokens`, `items[].pct_tokens`

#### Graphe 3 — Répartition par modèle/fournisseur (`BarChart` horizontal)

**Endpoint :** `GET /api/v1/admin/stats/breakdown?group_by=model`

```
claude-sonnet-4-6 (Bedrock) ██████████████████░░ 47%  115 000 tokens
gpt-4o (OpenAI)             ████████████░░░░░░░░ 29%   72 000 tokens
mistral-large (Mistral)     ████████░░░░░░░░░░░░ 24%   57 700 tokens
```

Implémenté avec un `BarChart layout="vertical"` :

```tsx
<BarChart layout="vertical" data={modelData}>
  <XAxis type="number" tickFormatter={(v) => `${(v/1000).toFixed(0)}k`} />
  <YAxis type="category" dataKey="label" width={180}
         tickFormatter={(v, i) => `${v} (${modelData[i]?.provider})`} />
  <Tooltip formatter={(v: number) => [`${v.toLocaleString()} tokens`, '']} />
  <Bar dataKey="tokens" fill="hsl(var(--colors-indigo-500))" radius={[0,4,4,0]}>
    <LabelList dataKey="pct_tokens" position="right" formatter={(v) => `${v}%`} />
  </Bar>
</BarChart>
```

#### Tableau — top utilisateurs

**Endpoint :** `GET /api/v1/admin/stats/users?sort_by=tokens&limit=50`

| Colonne     | Source                                | Tri        | Notes                        |
|-------------|---------------------------------------|------------|------------------------------|
| Utilisateur | `email` (enrichi API)                 | —          | Fallback : `user_id` tronqué |
| Sessions    | `sessions`                            | ✓          | —                            |
| Tokens      | `tokens`                              | ✓ (défaut) | format `XX XXX`              |
| Usages      | `sources` (liste des sources actives) | —          | ex. `chat · agent`           |
| Durée moy.  | `avg_duration_ms / 1000`              | ✓          | `X,X s`                      |
| →           | clic → `/admin/stats/users/:userId`   | —          | —                            |

> **`sources`** : à ajouter dans `stats_all_users()` — `GROUP_CONCAT(DISTINCT source)` ou liste dérivée côté API depuis une seconde query `stats_by_source(user_id=X)`.
> Option recommandée : ajouter `sources: list[str]` dans la réponse via une requête unique avec `GROUP_CONCAT`.

---

### 3.4 Page détail utilisateur — `/admin/stats/users/:userId`

**Fichier :** `web/src/pages/admin/stats-user-detail.tsx`

#### Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  ← Retour   user@example.com                                        │
│  [Cette semaine ▾]  [Usage: tous ▾]                                 │
│                                                                     │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐             │
│  │ Sessions     │  │ Tokens       │  │ Durée moy.   │             │
│  │     42       │  │   18 500     │  │    3,2 s     │             │
│  └──────────────┘  └──────────────┘  └──────────────┘             │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Tokens (par période)        [● Tous ○ Chat ○ Agent]        │   │
│  │  ─╮    ╭─╮  ╭──╮                                           │   │
│  │   ╰─╮ ╭╯  ╰─╯  ╰──                                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────────────────────┐  ┌─────────────────────────────────┐  │
│  │  Par usage              │  │  Par modèle / fournisseur       │  │
│  │  [donut]                │  │  [barres horizontales]          │  │
│  │  Chat 60%               │  │  claude-sonnet ██████ 65%       │  │
│  │  Agent 40%              │  │  gpt-4o       ████   35%       │  │
│  └─────────────────────────┘  └─────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Par chat                                                   │   │
│  │  Chat              Sessions  Tokens    Durée moy.  Usage    │   │
│  │  Assistant général  20       9 000     3,1 s       chat     │   │
│  │  Support client     22       9 500     3,3 s       chatbot  │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

#### Sources de données

| Composant                | Endpoint                                                      | Paramètres clés             |
|--------------------------|---------------------------------------------------------------|-----------------------------|
| KPI cards                | `GET /api/v1/admin/stats/users/{user_id}`                     | `from_date`, `to_date`      |
| LineChart tokens/période | `GET /api/v1/admin/stats/timeseries?user_id=X`                | + `granularity`, `source`   |
| Donut usage              | `GET /api/v1/admin/stats/breakdown?group_by=source&user_id=X` | —                           |
| Barres modèles           | `GET /api/v1/admin/stats/breakdown?group_by=model&user_id=X`  | —                           |
| Tableau par chat         | `by_dialog` dans réponse de `/users/{user_id}`                | + `dialog_name` enrichi API |

#### Graphe — évolution tokens (LineChart multi-séries)

Quand un filtre `source` est sélectionné, une seule série. Sans filtre, 3 séries superposées (`chat`, `chatbot`, `agent`) avec couleurs distinctes.

```tsx
// Données : appel timeseries une fois par source si multi-séries
// OU : endpoint timeseries étendu avec group_by=source (à évaluer en implémentation)
<LineChart data={timeData}>
  <Line dataKey="chat"    stroke={SOURCE_COLORS.chat}    dot={false} strokeWidth={2} />
  <Line dataKey="agent"   stroke={SOURCE_COLORS.agent}   dot={false} strokeWidth={2} />
  <Line dataKey="chatbot" stroke={SOURCE_COLORS.chatbot} dot={false} strokeWidth={2} />
</LineChart>
```

> **Alternative plus simple** : un seul appel timeseries filtré par la sélection `source` — pas de multi-séries. Recommandé pour la v1.

---

### 3.5 Navigation et routing

```tsx
// web/src/router/index.tsx — entrées à ajouter dans la section admin
{ path: '/admin/stats',                  element: <AdminStatsPage /> },
{ path: '/admin/stats/users/:userId',    element: <AdminStatsUserDetailPage /> },
```

Sidebar admin :

```tsx
// Entrée à côté de "Users" et "Monitoring"
{ path: '/admin/stats', label: t('stats.title'), icon: <BarChart2 size={16} /> }
```

---

### 3.6 Hooks React à créer

**Fichier :** `web/src/hooks/use-admin-stats-request.ts`

```typescript
type DateRangeParams = { from_date: string; to_date: string; granularity?: string };
type BreakdownParams = DateRangeParams & { group_by: 'source' | 'model' | 'provider'; user_id?: string; source?: string };

/** Évolution temporelle (graphe principal) */
export function useAdminTimeseries(params: DateRangeParams & { user_id?: string; source?: string }) {
  return useQuery({
    queryKey: ['admin-stats-timeseries', params],
    queryFn: () => fetchAdminTimeseries(params),
    staleTime: 60_000,
  });
}

/** Breakdown par source ou modèle */
export function useAdminBreakdown(params: BreakdownParams) {
  return useQuery({
    queryKey: ['admin-stats-breakdown', params],
    queryFn: () => fetchAdminBreakdown(params),
    staleTime: 60_000,
  });
}

/** Top utilisateurs (tableau) */
export function useAdminUsersStats(params: DateRangeParams & { sort_by?: string; limit?: number }) {
  return useQuery({
    queryKey: ['admin-stats-users', params],
    queryFn: () => fetchAdminUsersStats(params),
    staleTime: 60_000,
  });
}

/** Détail d'un utilisateur */
export function useAdminUserDetail(userId: string, params: DateRangeParams) {
  return useQuery({
    queryKey: ['admin-stats-user', userId, params],
    queryFn: () => fetchAdminUserDetail(userId, params),
    staleTime: 60_000,
    enabled: !!userId,
  });
}
```

---

### 3.7 Résumé des composants à créer

| Fichier                                              | Description                                                                    |
|------------------------------------------------------|--------------------------------------------------------------------------------|
| `web/src/pages/admin/stats.tsx`                      | Page overview : KPI + BarChart tokens + donut usage + barres modèles + tableau |
| `web/src/pages/admin/stats-user-detail.tsx`          | Page détail : KPI + LineChart + donut + barres modèles + tableau par chat      |
| `web/src/components/admin-stats/period-selector.tsx` | Contrôle période (Cette semaine / Mois / 12 mois / Personnalisé)               |
| `web/src/components/admin-stats/source-filter.tsx`   | Filtre usage (Chat / Chatbot / Agent / Tous)                                   |
| `web/src/components/admin-stats/tokens-chart.tsx`    | BarChart/LineChart tokens réutilisable                                         |
| `web/src/components/admin-stats/source-donut.tsx`    | PieChart répartition par usage                                                 |
| `web/src/components/admin-stats/model-bars.tsx`      | BarChart horizontal modèles/fournisseurs                                       |
| `web/src/hooks/use-admin-stats-request.ts`           | Hooks TanStack Query                                                           |
| `web/src/services/admin-stats-service.ts`            | Fonctions fetch vers `/api/v1/admin/stats/*`                                   |

---

## 4. Intégration Shield

### 3.1 Contexte

Le Shield est un proxy FastAPI (Python) devant un ou plusieurs serveurs RAGFlow. Il authentifie les utilisateurs via Keycloak (JWT), puis utilise la clé API de l'utilisateur RAGFlow pour les appels en aval.

Les `session_id` exposés par le Shield sont namespacés : `{server_id}__{ragflow_session_id}`.

Le `user_id` dans `usage_log` correspond à `current_user.id` côté RAGFlow, qui est identique au Keycloak `sub` après auto-provisioning (voir spec 023).

### 3.2 `GET /stats/me`

Stats de l'utilisateur authentifié, agrégées sur tous les serveurs RAGFlow configurés.

**Fichier :** `backend/app/routes/stats.py` (nouveau fichier)

#### Paramètres

| Paramètre    | Type         | Défaut              | Description                                     |
|--------------|--------------|---------------------|-------------------------------------------------|
| `from_date`  | `YYYY-MM-DD` | 1er du mois courant | Début de la période                             |
| `to_date`    | `YYYY-MM-DD` | aujourd'hui         | Fin de la période                               |
| `session_id` | string       | —                   | Namespaced session ID (`server_id__ragflow_id`) |

#### Logique d'agrégation

```python
# backend/app/routes/stats.py
@router.get("/stats/me")
async def stats_me(
    request: Request,
    from_date: str = Query(default=None),
    to_date: str = Query(default=None),
    session_id: str = Query(default=None),
    user: KeycloakUser = Depends(get_current_user),
    config: ShieldConfig = Depends(get_config),
):
    today = date.today()
    from_date = from_date or today.replace(day=1).isoformat()
    to_date = to_date or today.isoformat()

    # Appel parallèle à tous les serveurs RAGFlow
    tasks = []
    for server_id, server in config.ragflow_servers.items():
        params = {"from_date": from_date, "to_date": to_date}
        # Si session_id est namespaced pour ce serveur, le transmettre
        if session_id:
            s_server_id, s_original_id = parse_namespaced_id(session_id)
            if s_server_id == server_id:
                params["session_id"] = s_original_id
        tasks.append(
            _call_ragflow_stats_me(server, user.api_key, params, server_id)
        )

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Agrégation
    agg = _aggregate_stats(results)  # somme sessions/tokens, moyenne duration
    return agg
```

#### Réponse — `200 OK`

```json
{
  "period": { "from": "2026-06-01", "to": "2026-06-21" },
  "today":      { "sessions": 7,  "tokens": 3200, "avg_duration_ms": 3000.0 },
  "this_week":  { "sessions": 22, "tokens": 9800, "avg_duration_ms": 3050.0 },
  "totals":     { "sessions": 51, "tokens": 24000, "avg_duration_ms": 3100.0 },
  "by_server": {
    "common":  {
      "today":     { "sessions": 4, "tokens": 1800 },
      "this_week": { "sessions": 14, "tokens": 6000 },
      "totals":    { "sessions": 32, "tokens": 15000 }
    },
    "dept-rh": {
      "today":     { "sessions": 3, "tokens": 1400 },
      "this_week": { "sessions": 8,  "tokens": 3800 },
      "totals":    { "sessions": 19, "tokens": 9000 }
    }
  },
  "current_session": {
    "session_id": "common__abc123",
    "sessions": 4,
    "tokens": 340,
    "avg_duration_ms": 2125.0
  }
}
```

> `current_session` est absent si `session_id` n'est pas fourni ou introuvable.
> `by_server` : détail optionnel, peut être omis en première itération.

---

### 3.3 `GET /stats/sessions/{session_id}`

Stats d'une conversation spécifique (identifiée par `session_id` namespaced).

**Fichier :** `backend/app/routes/stats.py`

#### Paramètres

`session_id` dans le path — namespaced : `{server_id}__{ragflow_session_id}`

#### Logique

```python
@router.get("/stats/sessions/{session_id}")
async def stats_session(
    session_id: str,
    user: KeycloakUser = Depends(get_current_user),
    config: ShieldConfig = Depends(get_config),
):
    server_id, ragflow_session_id = parse_namespaced_id(session_id)
    server = config.ragflow_servers.get(server_id)
    if not server:
        raise HTTPException(status_code=404, detail=f"Server {server_id!r} not found")

    resp = await _call_ragflow_stats_me(
        server, user.api_key,
        params={"session_id": ragflow_session_id, "from_date": "2000-01-01"},
        server_id=server_id,
    )
    session_data = resp.get("current_session", {})
    session_data["session_id"] = session_id  # re-namespace pour le client
    return session_data
```

#### Réponse — `200 OK`

```json
{
  "session_id": "common__abc123",
  "sessions": 4,
  "tokens": 340,
  "avg_duration_ms": 2125.0
}
```

#### Erreurs

| Code HTTP | Cas                               |
|-----------|-----------------------------------|
| 400       | `session_id` non namespaced       |
| 404       | Serveur inconnu                   |
| 401       | Token Keycloak absent ou invalide |
| 502       | RAGFlow injoignable               |

---

### 3.4 Méthode d'aggrégation Shield

```python
def _aggregate_stats(server_results: list[dict | Exception]) -> dict:
    """Somme sessions/tokens, moyenne pondérée avg_duration_ms."""
    totals = defaultdict(lambda: {"sessions": 0, "tokens": 0, "_duration_sum": 0.0})

    for result in server_results:
        if isinstance(result, Exception):
            continue  # skip les serveurs injoignables
        for period in ("today", "this_week", "totals"):
            src = result.get("data", {}).get(period, {})
            dst = totals[period]
            dst["sessions"] += src.get("sessions", 0)
            dst["tokens"] += src.get("tokens", 0)
            # durée pondérée par le nombre de sessions
            dst["_duration_sum"] += src.get("avg_duration_ms", 0) * src.get("sessions", 0)

    for period, data in totals.items():
        sessions = data.pop("sessions") or 0  # évite division par 0
        data["avg_duration_ms"] = round(
            data.pop("_duration_sum") / max(sessions, 1), 1
        )
        data["sessions"] = sessions

    return dict(totals)
```

---

## 4. UI Shield — widgets de consommation (Étape 8)

### 4.1 Widget compteur de session

Affiché dans le fil de conversation, mis à jour après chaque tour.

**Source de données :** appelé une fois à l'ouverture de session (`GET /stats/sessions/{id}`), puis mis à jour côté client en accumulant les tokens retournés dans les events SSE (`data.usage.total_tokens`).

```
┌─────────────────────────────────────────┐
│  Session courante                       │
│  🔢 340 tokens   ⏱ 4 tours   📊 2,1 s  │
└─────────────────────────────────────────┘
```

**Ne pas poller `GET /stats/sessions/{id}` après chaque tour** — utiliser les données `usage` du stream SSE pour l'accumulation temps réel.

### 4.2 Widgets de consommation — page d'accueil

Appelé une fois à l'authentification (`GET /stats/me`), affiché dans la sidebar ou l'en-tête.

```
┌─────────────────────────────────────────┐
│  Ma consommation                        │
│  Aujourd'hui :     3 200 tokens         │
│  Cette semaine :   9 800 tokens         │
│  Ce mois :        24 000 tokens         │
└─────────────────────────────────────────┘
```

**Rafraîchissement :** toutes les 5 min via `useQuery` avec `staleTime: 300_000`.

---

## 5. Plan d'implémentation

L'implémentation démarre par le **dashboard admin RAGFlow** — c'est la surface la plus complète et elle valide l'ensemble de la stack (backend → API → frontend) avant d'attaquer le Shield.

---

### Phase 1 — `UsageLogService` : méthodes analytiques

**Fichier :** `api/db/services/usage_log_service.py`
**Durée estimée :** 45 min

Toutes les phases suivantes en dépendent. Doit être complète et testée avant de passer à la suite.

| Tâche                                       | Méthode                                                              | Statut |
|---------------------------------------------|----------------------------------------------------------------------|--------|
| Évolution temporelle (granularité variable) | `stats_timeseries(from_date, to_date, granularity, user_id, source)` | ☐      |
| Répartition par source                      | `stats_by_source(from_date, to_date, user_id)`                       | ☐      |
| Répartition par modèle/fournisseur          | `stats_by_model(from_date, to_date, user_id, source)`                | ☐      |
| Breakdown par chat                          | `stats_by_usage(from_date, to_date, user_id)`                       | ☐      |
| Enrichir `stats_all_users`                  | Ajouter `active_users` (COUNT DISTINCT) + `sources` (GROUP_CONCAT)   | ☐      |

**Validation :** tester en Python shell ou pytest avec des données de fixture avant de passer à la phase 2.

---

### Phase 2 — Endpoints API RAGFlow (admin)

**Fichier :** `api/apps/restful_apis/stats_api.py`
**Durée estimée :** 1 h 30

| Tâche                    | Endpoint                                  | Dépend de                                                 |
|--------------------------|-------------------------------------------|-----------------------------------------------------------|
| Top utilisateurs (liste) | `GET /api/v1/admin/stats/users`           | `stats_all_users()` enrichi                               |
| Détail utilisateur       | `GET /api/v1/admin/stats/users/{user_id}` | `stats_for_user()`, `stats_by_day()`, `stats_by_usage()` |
| Évolution temporelle     | `GET /api/v1/admin/stats/timeseries`      | `stats_timeseries()`                                      |
| Répartition par axe      | `GET /api/v1/admin/stats/breakdown`       | `stats_by_source()`, `stats_by_model()`                   |

**Ordre de développement :** timeseries → breakdown → users → users/{user_id}
(du plus simple au plus composite)

**Validation :** tester manuellement avec `curl` ou HTTPie sur l'instance locale avant de passer à la phase 3.

---

### Phase 3 — Dashboard admin RAGFlow (frontend)

**Durée estimée :** 3 – 4 h

Décomposé en 4 sous-étapes indépendantes una fois les endpoints de phase 2 disponibles.

#### 3a — Infrastructure partagée (à faire en premier)

| Fichier                                              | Contenu                                                                                                      |
|------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| `web/src/services/admin-stats-service.ts`            | Fonctions `fetch` vers tous les endpoints `/api/v1/admin/stats/*`                                            |
| `web/src/hooks/use-admin-stats-request.ts`           | Hooks TanStack Query (`useAdminTimeseries`, `useAdminBreakdown`, `useAdminUsersStats`, `useAdminUserDetail`) |
| `web/src/components/admin-stats/period-selector.tsx` | Contrôle "Cette semaine / Ce mois / 12 mois / Personnalisé" + calcul auto de `granularity`                   |
| `web/src/components/admin-stats/source-filter.tsx`   | Select "Tous / Chat / Chatbot / Agent"                                                                       |

#### 3b — Composants graphiques réutilisables

| Fichier                                           | Graphe                           | Type recharts                                |
|---------------------------------------------------|----------------------------------|----------------------------------------------|
| `web/src/components/admin-stats/tokens-chart.tsx` | Évolution tokens par période     | `BarChart` (overview) / `LineChart` (détail) |
| `web/src/components/admin-stats/source-donut.tsx` | Répartition par usage            | `PieChart` innerRadius (donut)               |
| `web/src/components/admin-stats/model-bars.tsx`   | Répartition modèles/fournisseurs | `BarChart layout="vertical"`                 |

Chaque composant reçoit ses données en props — pas de fetch interne. Testable avec des données statiques.

#### 3c — Page overview `/admin/stats`

**Fichier :** `web/src/pages/admin/stats.tsx`

Assemble les composants 3a et 3b :
1. Barre de contrôle (period-selector + source-filter)
2. KPI cards × 3
3. `TokensChart` (BarChart, granularité auto)
4. `SourceDonut` + `ModelBars` côte à côte
5. Tableau top utilisateurs (shadcn/ui `Table`, cliquable)

#### 3d — Page détail `/admin/stats/users/:userId`

**Fichier :** `web/src/pages/admin/stats-user-detail.tsx`

1. Breadcrumb ← Retour + email utilisateur
2. Barre de contrôle (period-selector + source-filter)
3. KPI cards × 3
4. `TokensChart` (LineChart)
5. `SourceDonut` + `ModelBars` côte à côte
6. Tableau par chat

#### 3e — Routing et navigation

| Fichier                                    | Modification                                           |
|--------------------------------------------|--------------------------------------------------------|
| `web/src/router/index.tsx` (ou équivalent) | Ajouter `/admin/stats` et `/admin/stats/users/:userId` |
| Sidebar admin                              | Ajouter entrée "Statistiques" avec icône `BarChart2`   |

---

### Phase 4 — Endpoint `/api/v1/stats/me` (utilisateur)

**Fichier :** `api/apps/restful_apis/stats_api.py`
**Durée estimée :** 30 min

Étape 4 du roadmap. Non bloquant pour le dashboard admin — peut être développé en parallèle de la phase 3 ou après.

| Tâche                  | Description                                                          |
|------------------------|----------------------------------------------------------------------|
| Endpoint               | `GET /api/v1/stats/me?from_date&to_date&session_id`                  |
| Périodes pré-calculées | today, this_week, period (paramétrable), current_session (optionnel) |

---

### Phase 5 — Shield : endpoints stats

**Fichier :** `backend/app/routes/stats.py` (nouveau)
**Durée estimée :** 1 h 30

Dépend de la phase 4 (`/api/v1/stats/me` opérationnel).

| Tâche                            | Endpoint                              | Description                          |
|----------------------------------|---------------------------------------|--------------------------------------|
| Stats utilisateur multi-serveurs | `GET /stats/me`                       | Appels parallèles + agrégation       |
| Stats session                    | `GET /stats/sessions/{namespaced_id}` | Dé-namespacage + appel RAGFlow ciblé |

---

### Phase 6 — Shield : UI widgets

**Durée estimée :** 1 – 2 h

Dépend de la phase 5.

| Tâche                       | Composant             | Localisation                             |
|-----------------------------|-----------------------|------------------------------------------|
| Widgets consommation (home) | `ConsumptionWidget`   | Sidebar ou header de `chatbot_ui`        |
| Compteur session            | `SessionTokenCounter` | Fil de conversation (mis à jour via SSE) |

---

### Récapitulatif

| Phase     | Livrable                                          | Durée        | Bloque           |
|-----------|---------------------------------------------------|--------------|------------------|
| **1**     | `UsageLogService` méthodes analytiques            | 45 min       | 2, 3             |
| **2**     | Endpoints admin RAGFlow                           | 1 h 30       | 3                |
| **3a**    | Infrastructure front (services, hooks, contrôles) | 45 min       | 3b, 3c, 3d       |
| **3b**    | Composants graphiques                             | 45 min       | 3c, 3d           |
| **3c**    | Page overview `/admin/stats`                      | 45 min       | 3d (indépendant) |
| **3d**    | Page détail utilisateur                           | 45 min       | —                |
| **3e**    | Routing + sidebar                                 | 15 min       | —                |
| **4**     | `GET /api/v1/stats/me`                            | 30 min       | 5                |
| **5**     | Shield endpoints stats                            | 1 h 30       | 6                |
| **6**     | Shield UI widgets                                 | 1 – 2 h      | —                |
| **Total** |                                                   | **~8 – 9 h** |                  |

---

### Décisions d'architecture arrêtées

| Décision                                                           | Raison                                                            |
|--------------------------------------------------------------------|-------------------------------------------------------------------|
| Source unique : `usage_log` (pas `api_4_conversation`)             | Couvre toutes les surfaces, survit aux suppressions               |
| Résolution `user_id → email` côté API (pas frontend)               | Évite N+1 ; enrichissement dans `stats_all_users()`               |
| Granularité auto selon la période                                  | UX — l'utilisateur choisit la fenêtre, pas le niveau de détail    |
| Filtres source/fournisseur dans la barre de contrôle partagée      | Un seul état de filtre appliqué à tous les graphes simultanément  |
| Shield appelle `/api/v1/stats/me` avec la clé API de l'utilisateur | Pas de compte de service — isolation des données par utilisateur  |
| Accumulation tokens côté client dans le fil de conversation        | Évite le polling API après chaque tour SSE                        |
| `avg_duration_ms` = durée moyenne par tour (pas totale session)    | Cohérent avec le modèle d'entrée `usage_log` (une ligne par tour) |

---

### Points ouverts

| Question                                                  | Impact            | Décision proposée                                              |
|-----------------------------------------------------------|-------------------|----------------------------------------------------------------|
| Multi-séries par source dans le `LineChart` utilisateur ? | Complexité UI     | V1 : une seule série (filtrée par source) — multi-séries en v2 |
| Inclure `by_server` dans `/stats/me` Shield ?             | UX multi-serveurs | Omettre en v1, ajouter en v2                                   |
| Enrichir `by_dialog` avec le nom du chat ?                | Lisibilité admin  | Oui — `DialogService.get_by_id(dialog_id)` côté API            |
| Quota enforcement Shield ?                                | Fonctionnel       | Hors scope — spec dédiée quand le besoin se concrétise         |
