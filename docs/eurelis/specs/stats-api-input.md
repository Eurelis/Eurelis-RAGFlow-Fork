# Spécifications Fork RAGFlow — API Statistiques de consommation

**Date :** 2026-05-24
**Référence :** `docs/eurelis/roadmap/user-statistics-and-consumption.md`

---

## Contexte

RAGFlow stocke dans `api_4_conversation` les métriques de consommation par session (`tokens`, `duration`, `round`, `thumb_up`, `user_id`). Ces données ne sont pas exposées de manière exploitable :

- `GET /system/stats` agrège par tenant uniquement, sans filtre par utilisateur
- Le champ `usage` (tokens, durée) n'est pas retourné dans les réponses API de completion
- `API4Conversation.tokens` et `duration` restent à 0 en DB (`append_message` n'incrémente que `round`)

Les évolutions ci-dessous créent les endpoints nécessaires au Shield et à l'interface admin.

---

## 1. Correction : persistance des tokens et de la durée en DB

**Fichier :** `api/db/services/api_service.py`

`API4ConversationService.append_message` n'incrémente actuellement que `round`. Étendre pour persister les tokens et la durée après chaque échange.

```python
@classmethod
@DB.connection_context()
def append_message(cls, id, conversation, tokens: int = 0, duration: float = 0.0):
    return (
        cls.model.update(
            round=cls.model.round + 1,
            tokens=cls.model.tokens + tokens,
            duration=cls.model.duration + duration,
        )
        .where(cls.model.id == id)
        .execute()
    )
```

Les appelants (`conversation_service.py`) passent les valeurs extraites du dict retourné par `async_chat`.

---

## 2. Champ `usage` dans la réponse de completion

**Fichier :** `api/db/services/dialog_service.py`

Les variables `tk_num`, `used_token_count`, `total_time_cost` et `generate_result_time_cost` sont déjà calculées (lignes ~841-855). Elles sont aujourd'hui encodées en texte dans le champ `prompt`. Ajouter un champ structuré `usage` dans le dict de retour :

```python
# Modifier le return final de async_chat (ligne ~872)
return {
    "answer": think + answer,
    "reference": refs,
    "prompt": re.sub(r"\n", "  \n", prompt),
    "created_at": time.time(),
    "usage": {
        "prompt_tokens": used_token_count,
        "completion_tokens": tk_num,
        "total_tokens": used_token_count + tk_num,
        "duration_ms": round(total_time_cost, 1),
        "tokens_per_second": int(tk_num / (generate_result_time_cost / 1000.0 + 0.001)),
    },
}
```

`structure_answer()` propage le dict sans modification — `usage` apparaît automatiquement dans la réponse API.

Les appelants dans `conversation_service.py` extraient `usage` pour alimenter `append_message`.

**Note upstream :** correspond à [issue #9146](https://github.com/infiniflow/ragflow/issues/9146). Ce correctif sera proposé en PR upstream.

---

## 3. Endpoint utilisateur : `GET /api/v1/stats/me`

**Fichier :** `api/apps/restful_apis/stats_api.py`

Endpoint authentifié (API key ou JWT RAGFlow), retournant la consommation de l'utilisateur courant.

### Résolution du `user_id` — point critique

Il existe deux modes d'authentification avec des sources de `user_id` différentes :

| Mode d'auth | `g.auth_via_api_token` | Source du `user_id` à filtrer |
|---|---|---|
| Session UI / JWT RAGFlow | `False` | `current_user.id` (UUID interne RAGFlow) |
| API key (Shield service account) | `True` | `?user_id=` query param (sub Keycloak propagé par le Shield) |

**Pourquoi :** le Shield appelle RAGFlow avec sa clé de service (`Authorization: Bearer <api_key>`) mais les sessions sont enregistrées dans `API4Conversation.user_id` avec le `sub` Keycloak de l'utilisateur final (`sub.replace("-", "")`). Ces deux valeurs sont différentes — filtrer par `current_user.id` ne retournerait rien.

```python
@manager.route("/api/v1/stats/me", methods=["GET"])
@login_required
def stats_me():
    if g.auth_via_api_token:
        # Appelé par le Shield avec un compte de service :
        # user_id = sub Keycloak de l'utilisateur final, propagé en query param
        user_id = request.args.get("user_id")
        if not user_id:
            return get_data_error_result(message="user_id is required when authenticating via API key")
    else:
        # Appelé directement par un utilisateur authentifié via l'UI ou JWT RAGFlow
        user_id = current_user.id
    ...
```

**Sécurité :** quand `auth_via_api_token` est `True`, tout `user_id` peut être passé — c'est intentionnel, le Shield est un composant de confiance qui contrôle la valeur. Un utilisateur authentifié via session UI ne peut accéder qu'à ses propres stats (`current_user.id` non overridable).

### Route

```
GET /api/v1/stats/me
    ?user_id=<sub_keycloak>   (requis si auth via API key / Shield)
    ?session_id=<id>          (optionnel)
    ?from_date=...            (optionnel, défaut : 1er du mois courant)
    ?to_date=...              (optionnel, défaut : maintenant)
```

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

### Implémentation

- Requêtes sur `API4Conversation` filtrées par `user_id` + fenêtres temporelles
- `user_id` dérivé de `current_user.id` si authentifié par session/JWT RAGFlow, ou du paramètre `user_id` si authentifié par API key (propagé par le Shield)
- Fenêtres calculées côté serveur : aujourd'hui = depuis minuit UTC, cette semaine = lundi 00:00 UTC, ce mois = 1er 00:00 UTC

---

## 4. Endpoints admin : stats par utilisateur

**Fichiers :** `admin/server/routes.py` + `admin/server/services.py`

### 4.1 `GET /api/v1/admin/stats/users`

Liste agrégée de tous les utilisateurs avec leurs métriques sur une période.

```
GET /api/v1/admin/stats/users
    ?from_date=2026-05-01
    ?to_date=2026-05-31
    ?chat_id=<dialog_id>    (optionnel — filtrer par chat)
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

### 4.2 `GET /api/v1/admin/stats/users/{user_id}`

Détail complet pour un utilisateur : métriques globales, breakdown par chat, évolution temporelle.

```
GET /api/v1/admin/stats/users/{user_id}
    ?from_date=...&to_date=...
```

```json
{
  "user_id": "550e8400e29b41d4a716446655440000",
  "period": { "from": "2026-05-01", "to": "2026-05-31" },
  "totals": {
    "sessions": 42,
    "tokens": 18500,
    "avg_duration_ms": 3200,
    "avg_round": 4.1,
    "thumb_up": 12
  },
  "by_chat": [
    {
      "dialog_id": "...",
      "dialog_name": "Assistant général",
      "sessions": 20,
      "tokens": 9000,
      "avg_round": 3.8
    }
  ],
  "by_day": [
    { "date": "2026-05-01", "sessions": 3, "tokens": 1200 }
  ]
}
```

### Implémentation

Nouveau `UserStatsMgr` dans `admin/server/services.py` :
- `get_stats_all_users(from_date, to_date, chat_id, sort_by, limit)` — agrégation `GROUP BY user_id`
- `get_stats_user(user_id, from_date, to_date)` — agrégation multi-axes pour un utilisateur

Les deux utilisent `API4ConversationService` avec jointure `Dialog` pour récupérer les noms de chats.

---

## 5. Agents — token usage (partiel)

**Fichier :** à identifier dans `api/apps/restful_apis/agent_api.py`

Ajouter le total tokens + durée totale dans la réponse des agents, sur le même modèle que la correction de `dialog_service.py`.

Le breakdown par nœud (durée par composant du canvas) est **hors périmètre** de ce spec — à laisser à l'upstream ([issue #11576](https://github.com/infiniflow/ragflow/issues/11576), assigné à Wang Qi).

---

## Ordre d'implémentation recommandé

| Étape | Fichier(s) | Dépendances |
|---|---|---|
| 1 | `dialog_service.py` — champ `usage` dans la réponse | — |
| 2 | `api_service.py` — persistance tokens/duration | Étape 1 |
| 3 | `conversation_service.py` — passer usage à append_message | Étapes 1 & 2 |
| 4 | `stats_api.py` — `GET /api/v1/stats/me` | Étape 2 |
| 5 | `admin/server/services.py` — `UserStatsMgr` | Étape 2 |
| 6 | `admin/server/routes.py` — routes stats admin | Étape 5 |
| 7 | `agent_api.py` — usage total agents | — |

---

## Hors périmètre (ce spec)

- Interface admin RAGFlow (UI) — dépend de l'existence d'un frontend admin Eurelis
- Breakdown par nœud pour les agents — upstream #11576
- Stats Langfuse par `user_id` / `session_id` — couvert par `docs/eurelis/roadmap/langfuse-session-user-integration.md`
