# Spec — Shield : intégration token usage & visibilité stats RAGFlow

> **Note refactoring `source`/`token_type`.** Les références à `chatbot` ci-dessous désignent l'**endpoint** `/api/v1/chatbots/{id}/completions` (toujours valide), pas une valeur de `source` dans `usage_log`. Côté `usage_log`, ces sessions sont désormais loggées sous **`source="chat"`** (la valeur `chatbot` a été fusionnée dans `chat`), avec une dimension `token_type` (`llm`/`embedding`). Référence à jour : `docs/eurelis/specs/usage-log-table.md`.

## Contexte

Le Shield appelle `/api/v1/chat/completions` (AUTH_JWT) → sessions stockées dans la table
`conversation` → invisibles dans les stats RAGFlow (qui ne lisent que `api_4_conversation`).
Le champ `usage` est déjà présent dans les réponses RAGFlow mais non extrait par le Shield.

Deux objectifs indépendants :

| Objectif | Effort | Impact |
|---|---|---|
| **A** — Exposer `usage` dans les réponses Shield | Faible | Les clients Shield voient les tokens |
| **B** — Rendre les sessions Shield visibles dans les stats RAGFlow | Moyen | Dashboard RAGFlow cohérent |

---

## Objectif A — Extraction du `usage` (sans changement d'endpoint)

RAGFlow renvoie déjà `usage` dans la réponse finale (`prompt_tokens`, `completion_tokens`,
`total_tokens`, `duration_ms`). Il faut l'extraire et l'exposer.

### `app/models/completion.py`

Ajouter un modèle `UsageData` et l'intégrer à `CompletionData` :

```python
class UsageData(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_ms: float = 0.0


class CompletionData(BaseModel):
    answer: str
    audio_binary: Any = None
    created_at: float | None = None
    id: str | None = None
    reference: ReferenceData = Field(default_factory=ReferenceData)
    session_id: str
    usage: UsageData = Field(default_factory=UsageData)
    # `prompt` est intentionnellement exclu
```

### `app/services/ragflow_client.py` — non-streaming

`chat_completion()` retourne `payload.get("data", {})` qui contient déjà `usage` si RAGFlow l'a
inclus. Aucune modification nécessaire — `CompletionData.model_validate(raw)` l'extraira
automatiquement avec le nouveau modèle.

### `app/services/ragflow_client.py` — streaming

La méthode `chat_completion_stream()` transmet les chunks SSE bruts. Le chunk final contient
`usage`. Deux options :

**Option A1 — Pass-through transparent** (minimal)
Continuer à transmettre les SSE bruts. Le client Shield reçoit le `usage` dans le dernier chunk
SSE tel que RAGFlow l'envoie. Aucune modification nécessaire côté streaming si le client sait
parser les SSE.

**Option A2 — Injection dans le chunk final** (si le Shield reformate les SSE)
Si `chat_completion_stream()` reconstruit les événements SSE, intercepter le chunk avec `usage`
et s'assurer qu'il est inclus dans l'événement forwardé au client.

---

## Objectif B — Visibilité dans les stats RAGFlow (migration endpoint chatbot)

Passer de `/api/v1/chat/completions` à `/api/v1/chatbots/{dialog_id}/completions` pour écrire
dans `api_4_conversation`.

### Architecture de la double table

RAGFlow maintient deux tables de sessions distinctes :

| Table | Chemin | Colonnes métriques |
|---|---|---|
| `conversation` | `/api/v1/chat/completions` (AUTH_JWT) | aucune |
| `api_4_conversation` | `/api/v1/chatbots/{id}/completions` (AUTH_BETA) | `tokens`, `duration`, `round`, `thumb_up` |

Les stats Go (`/api/v1/system/stats`) n'agrègent que `api_4_conversation`. Les sessions Shield
sont donc invisibles du dashboard.

### Prérequis : Beta token

Le chatbot endpoint n'accepte que `AUTH_BETA` (token de type `beta` dans la table `api_token`,
différent des clés API standards). Le Shield doit disposer d'un Beta token RAGFlow par serveur,
généré dans l'UI RAGFlow → Settings → API Keys.

### `app/config.py` / `shield.yaml`

Ajouter un champ `beta_token` par serveur dans la config :

```yaml
# shield.yaml (multi-server)
origins:
  my-server:
    base_url: https://ragflow.example.com
    api_key: ragflow-...       # clé standard (sessions, chats, etc.)
    beta_token: ragflow-...    # nouveau — pour chatbot endpoint
```

```python
# app/config.py
class ServerConfig(BaseModel):
    base_url: str
    api_key: str | None = None
    beta_token: str | None = None  # nouveau
```

### `app/services/ragflow_client.py`

Ajouter `chatbot_completion()` et `chatbot_completion_stream()` qui :

- Utilisent l'URL `/api/v1/chatbots/{dialog_id}/completions`
- S'authentifient avec `beta_token` au lieu du token utilisateur
- Laissent le chatbot endpoint créer la session dans `api_4_conversation` si `session_id` absent
- Passent `user_id` dans le body pour identifier l'utilisateur dans `api_4_conversation.user_id`

```python
async def chatbot_completion(
    self,
    dialog_id: str,
    beta_token: str,
    session_id: str | None,
    question: str,
    user_id: str,
    request_id: str,
    messages: list | None = None,
    web_search: bool = False,
) -> dict:
    url = f"{self._base_url}/api/v1/chatbots/{dialog_id}/completions"
    headers = {"Authorization": f"Bearer {beta_token}"}
    body = {
        "stream": False,
        "internet": web_search,
        "user_id": user_id,
        "messages": messages or [{"role": "user", "content": question}],
    }
    if session_id:
        body["session_id"] = session_id
    # ... gestion HTTP identique à chat_completion()
```

### Gestion de session avec chatbot endpoint

Le chatbot endpoint crée lui-même la session et renvoie le prologue en premier SSE event.
Flow remplacé :

| Étape | Actuel | Après migration |
|---|---|---|
| Nouvelle session | `POST /api/v1/chats/{id}/sessions` → `conversation` | Premier appel à `/chatbots/{id}/completions` sans `session_id` → `api_4_conversation`, prologue dans SSE |
| Session existante | `GET /api/v1/chats/{id}/sessions/{id}` + completion | Idem — `session_id` passé dans le body |
| Historique | GET session → `messages[]` | Inchangé — GET session reste sur `conversation` (AUTH_JWT) |

> **Note** : les endpoints de gestion de sessions (`GET`, `DELETE`, rename) restent en AUTH_JWT
> et continuent de pointer vers `conversation`. Seul le chemin de completion change.

### `app/api/routes/completions.py`

Dans `post_completion()`, si `beta_token` est configuré pour le serveur, utiliser les nouvelles
méthodes `chatbot_completion()` / `chatbot_completion_stream()` à la place des méthodes actuelles.

```python
if server_beta_token:
    # chatbot path → api_4_conversation (visible dans les stats)
    raw = await client.chatbot_completion(
        dialog_id=chat_id,
        beta_token=server_beta_token,
        session_id=session_id,
        question=body.question,
        user_id=user_id,
        request_id=request_id,
        messages=messages,
    )
else:
    # legacy path → conversation (inchangé)
    raw = await client.chat_completion(...)
```

---

## Ordre de mise en œuvre recommandé

1. **Objectif A** (extraction `usage`) — ~2h — aucun risque, ne change pas le comportement
2. **Objectif B** en option selon si la visibilité dans les stats RAGFlow est nécessaire

## Fichiers impactés

| Fichier (Shield backend) | Objectif A | Objectif B |
|---|---|---|
| `app/models/completion.py` | `UsageData` + champ `usage` dans `CompletionData` | — |
| `app/services/ragflow_client.py` | Vérif pass-through streaming | `chatbot_completion()` + stream |
| `app/config.py` | — | Champ `beta_token` dans `ServerConfig` |
| `app/api/routes/completions.py` | — | Branchement conditionnel beta/legacy |
| `shield.yaml` | — | `beta_token` par serveur |

## Limites connues

- **Objectif B — historique incohérent** : `GET /api/v1/chats/{id}/sessions/{id}` lit la table
  `conversation`, mais les nouvelles sessions chatbot sont dans `api_4_conversation`. Si on
  mélange les deux chemins (ex : session créée en legacy puis poursuivie en chatbot), le GET
  session échouera. La migration doit être atomique par déploiement.

- **Objectif B — `user_id`** : dans `api_4_conversation`, `user_id` est la valeur passée dans
  le body (identifiant métier du client Shield), pas l'ID RAGFlow du tenant. Les stats Go
  comptent `COUNT(DISTINCT user_id)` pour le UV — c'est cohérent si le Shield passe toujours un
  `user_id` stable par utilisateur final.
