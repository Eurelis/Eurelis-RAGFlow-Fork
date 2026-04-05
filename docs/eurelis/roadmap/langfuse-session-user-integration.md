# Intégration sessions et utilisateurs dans le tracking Langfuse

## Contexte

RAGFlow intègre Langfuse pour le tracing des appels LLM, mais sans support des sessions ni des utilisateurs. Cette analyse détaille les modifications nécessaires.

## État actuel

Il y a **deux endroits** où Langfuse initialise une trace sans session ni utilisateur :

1. **`LLM4Tenant.__init__`** (`tenant_llm_service.py:406-417`) — utilisé par `LLMBundle` pour les embeddings/rerank/TTS
2. **`async_chat`** (`dialog_service.py:474-486`) — pour le chat principal

Le `trace_context` actuel ne contient que `{"trace_id": trace_id}`.

## Features Langfuse supportées

| Feature Langfuse            | Supporté |
|-----------------------------|----------|
| Tracing des générations LLM | ✅        |
| Token usage                 | ✅        |
| Métriques de performance    | ✅        |
| Sessions (`session_id`)     | ❌        |
| Utilisateurs (`user_id`)    | ❌        |
| Scores / feedback           | ❌        |

---

## Modifications requises

### Modification 1 — `api/db/services/tenant_llm_service.py`

Passer `session_id` et `user_id` dans le `trace_context` de `LLM4Tenant`.

`LLM4Tenant.__init__` reçoit déjà `**kwargs`, aucune signature à changer.

```python
# AVANT (ligne ~413)
trace_id = self.langfuse.create_trace_id()
self.trace_context = {"trace_id": trace_id}

# APRÈS
trace_id = self.langfuse.create_trace_id()
self.trace_context = {
    "trace_id": trace_id,
    "session_id": kwargs.get("session_id"),
    "user_id": kwargs.get("user_id"),
}
```

---

### Modification 2 — `api/db/services/dialog_service.py` (trace du chat)

Enrichir le `trace_context` dans `async_chat`.

```python
# AVANT (ligne ~482)
trace_id = langfuse_tracer.create_trace_id()
trace_context = {"trace_id": trace_id}

# APRÈS
trace_id = langfuse_tracer.create_trace_id()
trace_context = {
    "trace_id": trace_id,
    "session_id": kwargs.get("session_id"),
    "user_id": kwargs.get("user_id"),
}
```

---

### Modification 3 — `api/db/services/dialog_service.py` (propagation aux LLMBundle)

Après la création des modèles via `get_models()`, injecter session/user dans les `LLMBundle` déjà instanciés (qui ont leur propre `trace_context` créé indépendamment).

```python
# Ajouter après la ligne ~489 (après get_models(dialog))
kbs, embd_mdl, rerank_mdl, chat_mdl, tts_mdl = get_models(dialog)

# Propager session/user aux LLMBundle
if langfuse_tracer:
    for mdl in [embd_mdl, rerank_mdl, chat_mdl, tts_mdl]:
        if mdl and mdl.langfuse and mdl.trace_context:
            mdl.trace_context["session_id"] = kwargs.get("session_id")
            mdl.trace_context["user_id"] = kwargs.get("user_id")
```

---

### Modification 4 — `api/db/services/conversation_service.py`

`session_id` est un paramètre nommé dans `async_completion` et **n'est pas dans `**kwargs`**, donc il ne transite pas jusqu'à `async_chat`. Il faut l'y injecter explicitement.

```python
# AVANT (ligne ~112 et ~185)
async def async_completion(tenant_id, chat_id, question, name="New session", session_id=None, stream=True, **kwargs):
    ...
    async for ans in async_chat(dia, msg, True, **kwargs):

# APRÈS
async def async_completion(tenant_id, chat_id, question, name="New session", session_id=None, stream=True, **kwargs):
    ...
    kwargs["session_id"] = session_id  # injecter avant l'appel
    async for ans in async_chat(dia, msg, True, **kwargs):
```

Appliquer la même correction pour :
- Le chemin non-stream (~ligne 197)
- `async_iframe_completion` (~lignes 258, 272) — `user_id` est déjà dans kwargs pour ce chemin, mais `session_id` doit y être ajouté de même

---

## Résumé des fichiers touchés

| Fichier                                   | Ligne approximative    | Changement                                                  |
|-------------------------------------------|------------------------|-------------------------------------------------------------|
| `api/db/services/tenant_llm_service.py`   | ~413                   | Ajouter `session_id`/`user_id` dans `trace_context`         |
| `api/db/services/dialog_service.py`       | ~482                   | Ajouter `session_id`/`user_id` dans `trace_context` du chat |
| `api/db/services/dialog_service.py`       | ~489                   | Propager `session_id`/`user_id` vers les LLMBundle          |
| `api/db/services/conversation_service.py` | ~185, ~197, ~258, ~272 | Injecter `session_id` dans `kwargs` avant `async_chat`      |

## Notes

- Aucune modification de schéma DB, de frontend ou d'API externe n'est nécessaire.
- Langfuse supporte nativement `session_id` et `user_id` dans le `trace_context`.
- Le `user_id` est déjà disponible dans kwargs pour le chemin `async_iframe_completion` (embedded chat).
- Pour le chemin API standard (`async_completion`), `session_id` doit être explicitement propagé.
