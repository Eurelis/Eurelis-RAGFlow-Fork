# API — Statistiques de consommation (utilisateur)

Ces endpoints permettent à un utilisateur authentifié d'accéder à ses propres statistiques de consommation (sessions, tokens, durée) sur la période de son choix.

Tous les endpoints sont protégés par `login_required` : l'utilisateur doit être connecté. Il ne peut accéder qu'à ses propres données — aucune donnée d'un autre utilisateur n'est jamais exposée.

---

## Modèle de données

Les statistiques sont calculées sur la table append-only `usage_log`. Deux dimensions orthogonales décrivent chaque entrée :

| Dimension | Colonne | Valeurs |
|---|---|---|
| **Flux** | `source` | `chat`, `search`, `agent`, `ingestion` |
| **Nature du token** | `token_type` | `llm`, `embedding` |

- `source=chat` couvre le chat applicatif **et** le widget chatbot embarqué.
- `source=search` couvre la recherche IA (`/searches/.../completions`) **et** les retrievals dataset déclenchés par une app Search.
- `source=agent` couvre les workflows d'agent (retrieval inclus).
- `source=ingestion` couvre l'indexation de documents (voir `usage-stats-ingestion.md`).

> Voir `docs/eurelis/specs/usage-log-table.md` pour le schéma complet (`resource_id`, `object_id`, `tokens`, `duration`, `model`, `provider`).

### Filtres communs

Les endpoints `/me`, `/me/timeseries` et `/me/breakdown` acceptent deux filtres multi-valeurs (liste séparée par des virgules) :

| Paramètre | Exemple | Description |
|---|---|---|
| `source` | `chat,search` | Restreint aux flux indiqués |
| `type` | `embedding` | Restreint à la nature de token (`llm` / `embedding`) |

---

## `GET /api/v1/usage-stats/me`

Retourne les statistiques agrégées de l'utilisateur courant pour une période donnée.

### Paramètres de requête

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `from_date` | `YYYY-MM-DD` | 1er jour du mois courant | Début de période (inclus) |
| `to_date` | `YYYY-MM-DD` | Aujourd'hui | Fin de période (inclus) |
| `source` | liste CSV | _(toutes)_ | Filtre par flux |
| `type` | liste CSV | _(tous)_ | Filtre par nature de token |

### Exemple

```http
GET /api/v1/usage-stats/me?from_date=2026-06-01&to_date=2026-06-22&source=chat,search&type=llm
Authorization: Bearer <token>
```

### Réponse

```json
{
  "code": 0,
  "data": {
    "user_id": "a1b2c3d4e5f6...",
    "email": "user@example.com",
    "period": { "from": "2026-06-01", "to": "2026-06-22" },
    "totals": { "sessions": 42, "tokens": 158000, "avg_duration_ms": 1230.5 },
    "by_day": [
      { "date": "2026-06-01", "sessions": 3, "tokens": 8200 },
      { "date": "2026-06-02", "sessions": 1, "tokens": 2100 }
    ],
    "by_usage": [
      {
        "resource_id": "abc123de...",
        "label": "Mon chatbot (abc123de)",
        "sessions": 15,
        "tokens": 62000,
        "avg_duration_ms": 980.0,
        "pct_tokens": 39.2,
        "pct_sessions": 35.7
      }
    ]
  }
}
```

### Champs

**`totals`**

| Champ | Type | Description |
|---|---|---|
| `sessions` | `int` | Nombre total d'entrées `usage_log` sur la période |
| `tokens` | `int` | Nombre total de tokens consommés |
| `avg_duration_ms` | `float` | Durée moyenne (en ms) — moyenne sur les entrées de durée non nulle (`AVG(NULLIF(duration,0))`), les embeddings à durée 0 sont exclus |

**`by_day`** — trié par date croissante : `{ date, sessions, tokens }`.

**`by_usage`** — trié par tokens décroissants, regroupé par ressource :

| Champ | Type | Description |
|---|---|---|
| `resource_id` | `string` | Identifiant de la ressource (dialog, agent, search ou KB) |
| `label` | `string` | Nom de la ressource suivi de l'ID court (`nom (id8chars)`), ou « Autre ressource » |
| `sessions` | `int` | Nombre de sessions sur cette ressource |
| `tokens` | `int` | Tokens consommés sur cette ressource |
| `avg_duration_ms` | `float` | Durée moyenne par session (ms, durées non nulles) |
| `pct_tokens` | `float` | Part des tokens de cette ressource sur le total (%) |
| `pct_sessions` | `float` | Part des sessions de cette ressource sur le total (%) |

---

## `GET /api/v1/usage-stats/me/sources`

Retourne les valeurs distinctes présentes en base pour alimenter les filtres.

```json
{
  "code": 0,
  "data": {
    "sources": ["chat", "search", "agent", "ingestion"],
    "types": ["llm", "embedding"]
  }
}
```

---

## `GET /api/v1/usage-stats/me/timeseries`

Série temporelle des tokens avec granularité automatique selon la largeur de la fenêtre. Préférable à `by_day` pour les longues périodes.

### Paramètres de requête

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `from_date` / `to_date` | `YYYY-MM-DD` | mois courant / aujourd'hui | Période |
| `granularity` | `day` \| `week` \| `month` | auto | Force la granularité |
| `source` / `type` | liste CSV | _(tous)_ | Filtres |
| `by_source` | `true` \| `false` | `false` | Décompose la série par flux |
| `by_type` | `true` \| `false` | `false` | Décompose la série par nature de token (prioritaire sur `by_source`) |

**Granularité automatique :** ≤ 31 j → `day` (`YYYY-MM-DD`) ; ≤ 365 j → `week` (`YYYY-WW`) ; > 365 j → `month` (`YYYY-MM`).

### Réponses

`by_source=false` & `by_type=false` :

```json
{ "code": 0, "data": { "granularity": "day", "series": [
  { "period": "2026-06-01", "sessions": 3, "tokens": 8200 }
] } }
```

`by_source=true` — une ligne par (période, flux) :

```json
{ "code": 0, "data": { "granularity": "day", "series": [
  { "period": "2026-06-01", "source": "chat",   "tokens": 6100 },
  { "period": "2026-06-01", "source": "search", "tokens": 2100 }
] } }
```

`by_type=true` — une ligne par (période, nature) : `{ "period", "token_type", "tokens" }`.

---

## `GET /api/v1/usage-stats/me/breakdown`

Répartition de la consommation selon un axe au choix.

### Paramètres de requête

| Paramètre | Type | Défaut | Description |
|---|---|---|---|
| `from_date` / `to_date` | `YYYY-MM-DD` | mois courant / aujourd'hui | Période |
| `group_by` | `model` \| `source` \| `type` \| `dialog` \| `provider` | `model` | Axe de regroupement |
| `source` / `type` | liste CSV | _(tous)_ | Filtres |

### Réponse — `group_by=source`

```json
{ "code": 0, "data": { "group_by": "source", "items": [
  { "label": "chat",   "sessions": 20, "tokens": 80000, "pct_tokens": 50.6 },
  { "label": "search", "sessions": 12, "tokens": 60000, "pct_tokens": 38.0 },
  { "label": "agent",  "sessions":  5, "tokens": 15000, "pct_tokens":  9.5 }
] } }
```

### Réponse — `group_by=type`

```json
{ "code": 0, "data": { "group_by": "type", "items": [
  { "label": "llm",       "sessions": 30, "tokens": 150000, "pct_tokens": 94.9 },
  { "label": "embedding", "sessions": 60, "tokens":   8000, "pct_tokens":  5.1 }
] } }
```

### Réponse — `group_by=model`

Regroupé par (modèle, provider, `token_type`), trié par tokens décroissants. Chaque item porte `token_type`, ce qui permet de colorer les barres « Top modèles » selon la nature (LLM vs embedding).

```json
{ "code": 0, "data": { "group_by": "model", "items": [
  { "label": "gpt-4o",            "provider": "OpenAI", "token_type": "llm",       "sessions": 18, "tokens": 95000, "pct_tokens": 60.1 },
  { "label": "gemini-embedding-001","provider": "Gemini","token_type": "embedding","sessions": 40, "tokens":  6000, "pct_tokens":  3.8 }
] } }
```

### Champs de `items`

| Champ | `source`/`type` | `model` | `dialog` | Description |
|---|---|---|---|---|
| `label` | ✓ | ✓ | ✓ | Valeur du groupe |
| `provider` | — | ✓ | — | Provider LLM/embedding |
| `token_type` | — | ✓ | — | Nature du modèle |
| `sessions` | ✓ | ✓ | ✓ | Nombre de sessions |
| `tokens` | ✓ | ✓ | ✓ | Tokens consommés |
| `pct_tokens` | ✓ | ✓ | ✓ | Part sur le total de la période (%) |

---

## `GET /api/v1/usage-stats/me/session/{session_id}`

Retourne le détail tour par tour d'une conversation spécifique. Seul l'utilisateur propriétaire peut y accéder — le filtre `user_id` est appliqué côté service, une session d'un autre utilisateur renvoie la même erreur qu'une session inexistante.

### Réponse — succès

```json
{
  "code": 0,
  "data": {
    "object_id": "abc123def456789012345678901234ab",
    "resource_id": "d1a2b3c4e5f6789012345678901234cd",
    "dialog_name": "Support client (d1a2b3c4)",
    "source": "chat",
    "first_turn_at": "2026-06-22T09:15:32",
    "last_turn_at": "2026-06-22T09:18:04",
    "totals": { "turns": 3, "tokens": 4200, "total_duration_ms": 5840.0, "avg_duration_ms": 1946.7 },
    "by_turn": [
      { "turn": 1, "tokens": 980,  "duration_ms": 1120.0, "model": "gpt-4o", "provider": "OpenAI", "at": "2026-06-22T09:15:32" }
    ]
  }
}
```

### Réponse — session introuvable ou accès refusé

```json
{ "code": 102, "message": "Session not found or access denied" }
```

`source` vaut `chat`, `search`, `agent` ou `ingestion`.

> **Note `duration_ms`** : temps de traitement LLM mesuré côté serveur (génération, hors retrieval). Pour une session multi-modèles (agents), `model` peut varier d'un tour à l'autre.

---

## `GET /api/v1/usage-stats/me/ingestion`

Retourne les tokens d'embedding consommés lors de l'ingestion de documents par l'utilisateur courant (`source='ingestion'`, `token_type='embedding'`). Voir `usage-stats-ingestion.md`.

### Réponse

```json
{
  "code": 0,
  "data": {
    "period": { "from": "2026-06-01", "to": "2026-06-22" },
    "totals": { "tasks": 12, "tokens": 84000, "total_duration_ms": 43200.0 },
    "by_kb": [
      { "kb_id": "abc123", "kb_name": "Documentation produit", "tasks": 8, "tokens": 62000, "pct_tokens": 73.8 }
    ]
  }
}
```

> **Convention ingestion** : les entrées `source='ingestion'` utilisent `resource_id=kb_id` et `object_id=doc_id`. Ne jamais joindre `resource_id`/`object_id` entre flux différents sans filtrer sur `source`/`token_type`.

---

## Implémentation

| Élément | Fichier |
|---|---|
| Endpoints HTTP | `api/apps/restful_apis/usage_stats_api.py` |
| Service de données | `api/db/services/usage_log_service.py` |
| Helpers de logging | `api/db/services/eurelis_usage_log.py` |
| URLs frontend | `web/src/utils/eurelis-api.ts` |
| Service frontend | `web/src/services/user-stats-service.ts` |
| Page utilisateur | `web/src/pages/user-setting/stats/index.tsx` |
