# Chat — Endpoints API et gestion des pièces jointes

Analyse des endpoints utilisés par le chat RAGFlow, avec focus sur la gestion des pièces jointes.

---

## Architecture générale

- **Frontend** : React/TypeScript avec TanStack Query
- **Backend** : Flask/Quart asynchrone (Python)
- **Streaming** : Server-Sent Events (SSE)

---

## 1. Gestion des chats et sessions

### Chats

| Méthode  | Endpoint                 | Rôle                   |
|----------|--------------------------|------------------------|
| `POST`   | `/api/v1/chats`          | Créer un chat          |
| `GET`    | `/api/v1/chats`          | Lister les chats       |
| `GET`    | `/api/v1/chats/{chatId}` | Récupérer un chat      |
| `PUT`    | `/api/v1/chats/{chatId}` | Remplacer complètement |
| `PATCH`  | `/api/v1/chats/{chatId}` | Mise à jour partielle  |
| `DELETE` | `/api/v1/chats/{chatId}` | Supprimer              |

**Payload création** : `{name, description, dataset_ids, llm_id, prompt_config, llm_setting, …}`

### Sessions (conversations)

| Méthode  | Endpoint                                      | Rôle                  |
|----------|-----------------------------------------------|-----------------------|
| `POST`   | `/api/v1/chats/{chatId}/sessions`             | Créer une session     |
| `GET`    | `/api/v1/chats/{chatId}/sessions`             | Lister les sessions   |
| `GET`    | `/api/v1/chats/{chatId}/sessions/{sessionId}` | Récupérer une session |
| `PATCH`  | `/api/v1/chats/{chatId}/sessions/{sessionId}` | Renommer              |
| `DELETE` | `/api/v1/chats/{chatId}/sessions`             | Supprimer (batch)     |

**Fichiers backend** :
- `api/apps/restful_apis/chat_api.py` (lignes 254–809)
- `api/db/services/dialog_service.py`

---

## 2. Envoi de messages et streaming

### Endpoint principal

```
POST /api/v1/chat/completions
```

**Payload** :
```json
{
  "chat_id": "string",
  "session_id": "string",
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "texte du message",
      "files": [{ "id": "uuid", "name": "fichier.pdf", "size": 12345 }]
    }
  ],
  "stream": true,
  "reasoning": false,
  "internet": false
}
```

**Réponse SSE** (flux toutes les ~100 ms) :
```json
data: {
  "code": 0,
  "data": {
    "answer": "texte progressif…",
    "reference": { "chunks": […], "doc_aggs": […] },
    "chat_id": "…",
    "conversationId": "…",
    "start_to_think": false,
    "end_to_think": false
  }
}
```

**Fichiers backend** :
- `api/apps/restful_apis/chat_api.py` (lignes 1045–1149, `session_completion`)
- `api/db/services/dialog_service.py` — `async_chat()`

### Endpoints auxiliaires

| Méthode  | Endpoint                                                       | Rôle                   |
|----------|----------------------------------------------------------------|------------------------|
| `DELETE` | `/api/v1/chats/{chatId}/sessions/{sessionId}/messages/{msgId}` | Supprimer un message   |
| `PUT`    | `…/messages/{msgId}/feedback`                                  | Thumbup / feedback     |
| `POST`   | `/api/v1/chat/audio/speech`                                    | Text-to-Speech         |
| `POST`   | `/api/v1/chat/audio/transcription`                             | Speech-to-Text         |
| `POST`   | `/api/v1/chat/mindmap`                                         | Générer un mindmap     |
| `POST`   | `/api/v1/chat/recommendation`                                  | Questions recommandées |

---

## 3. Pièces jointes — flux complet

### Étape 1 — Création de session (si nécessaire)

Avant tout upload dans une nouvelle conversation, une session doit exister :

```
POST /api/v1/chats/{chatId}/sessions
Body: { "name": "nom de la conversation" }
→ Réponse: { "id": "session-uuid", … }
```

Le `session_id` obtenu est utilisé dans les étapes suivantes.

### Étape 2 — Upload du fichier

```
POST /api/v1/documents/upload
Content-Type: multipart/form-data

Champs :
  file  : File  (obligatoire)
```

**Alternative par URL** :
```
POST /api/v1/documents/upload?url=https://example.com/document.pdf
```
Les formes `multipart` et `?url=` sont mutuellement exclusives.

**Réponse** :
```json
{
  "id": "uuid-location",
  "name": "rapport.pdf",
  "size": 204800,
  "extension": "pdf",
  "mime_type": "application/pdf",
  "created_at": 1715000000,
  "created_by": "user-uuid",
  "preview_url": null
}
```

**Comportement backend** : le fichier est stocké dans le bucket objet `{user_id}-downloads` sous une clé UUID. Il n'est enregistré dans aucune table de base de données. La paire `(created_by, id)` est le seul moyen de le retrouver.

> ⚠ **Le champ `conversation_id` n'existe pas dans cet endpoint.** Le frontend l'envoie dans le FormData, mais le backend l'ignore. Aucun lien session/fichier n'est créé au moment de l'upload.

### Étape 3 — Envoi du message avec pièce jointe

L'objet retourné à l'étape 2 est référencé dans le tableau `files` du message :

```
POST /api/v1/chat/completions
Body:
{
  "chat_id": "…",
  "session_id": "…",
  "messages": [
    {
      "role": "user",
      "content": "Analyse ce document",
      "files": [
        {
          "id": "uuid-location",
          "name": "rapport.pdf",
          "size": 204800,
          "extension": "pdf",
          "mime_type": "application/pdf",
          "created_by": "user-uuid"
        }
      ]
    }
  ],
  "stream": true
}
```

C'est **ici** que l'association fichier ↔ conversation est matérialisée. Le backend relit le blob depuis le stockage objet à la volée via `(created_by, id)`. Les fichiers ne sont jamais indexés dans un knowledge base.

### Étape 4 — Téléchargement de fichiers générés (réponse assistant)

Certaines réponses (ex. exécution de code) produisent des fichiers téléchargeables :

```
GET /api/v1/documents/{doc_id}/download
```

Ces fichiers figurent dans la structure `downloads` du message assistant, distincte des `files` utilisateur.

---

## 4. Structures de données

### Fichier uploadé (retour de l'upload, référencé dans `files`)

| Champ        | Type     | Description                               |
|--------------|----------|-------------------------------------------|
| `id`         | string   | Clé de localisation dans le stockage objet |
| `name`       | string   | Nom du fichier                            |
| `size`       | number   | Taille en octets                          |
| `extension`  | string   | Extension (ex. `pdf`)                     |
| `mime_type`  | string   | Type MIME                                 |
| `created_at` | number   | Timestamp Unix                            |
| `created_by` | string   | UUID du tenant propriétaire               |
| `preview_url`| null     | Toujours `null` (voir Points d'attention) |

### Fichier téléchargeable dans la réponse assistant (`downloads`)

| Champ       | Type   | Description      |
|-------------|--------|------------------|
| `doc_id`    | string | ID du document   |
| `filename`  | string | Nom du fichier   |
| `mime_type` | string | Type MIME        |
| `size`      | number | Taille en octets |

---

## 5. Authentification

Tous les endpoints requièrent :
- **Header** : `Authorization: Bearer {token}`
- **Isolation tenant** : les données sont filtrées par `current_user.id`

---

## 6. Points d'attention

### `preview_url` toujours `null`

Il n'existe pas d'endpoint de prévisualisation pour les fichiers uploadés dans le contexte du chat. Ouvrir une pièce jointe depuis l'historique (ex. PDF) est un manque à implémenter.

### Persistance des pièces jointes

Les fichiers uploadés ne sont liés à une conversation que via le tableau `files` du message historisé. Il n'existe aucune table dédiée ni index. Si l'historique est perdu, les fichiers deviennent orphelins dans le bucket de stockage.

### Fichiers utilisateur vs fichiers assistant

- `files` (message utilisateur) → uploadés avant l'envoi, référencés par `(created_by, id)`
- `downloads` (message assistant) → générés côté backend, téléchargeables via `/api/v1/documents/{doc_id}/download`

Ces deux structures sont distinctes et ne partagent pas le même cycle de vie.
