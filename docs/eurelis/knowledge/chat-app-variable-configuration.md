# Chat App — Configuration des Variables (section "Variable")

## Vue d'ensemble

Dans l'interface de configuration d'une chat app, la section **Variable** permet de déclarer des clés (`parameters`) qui seront injectées comme placeholders dans le system prompt. Chaque paramètre a la forme :

```json
{ "key": "string", "optional": boolean }
```

La clé `knowledge` est proposée par défaut et occupe une place particulière dans le pipeline RAG.

---

## Flux technique

### Stockage

La configuration est persistée dans `prompt_config.parameters` (champ JSON du dialog/chat app).

### Envoi à l'API

Les valeurs des variables sont passées dans le **body JSON** de chaque requête de complétion :

```
POST /chats/{chat_id}/sessions/{session_id}/messages
```

Le corps de la requête (hors champ `messages`) est transmis comme `**kwargs` à la fonction `async_chat()` dans `api/db/services/dialog_service.py`.

### Validation et injection (`dialog_service.py:563–691`)

```python
# Extraction des clés déclarées
param_keys = [p["key"] for p in prompt_config.get("parameters", [])]

for p in prompt_config.get("parameters", []):
    if p["key"] == "knowledge":
        continue  # traité séparément (voir ci-dessous)
    if p["key"] not in kwargs and not p["optional"]:
        raise KeyError("Miss parameter: " + p["key"])   # Required absent → échec
    if p["key"] not in kwargs:
        prompt_config["system"] = prompt_config["system"].replace("{%s}" % p["key"], " ")  # Optional absent → espace

# Injection dans le system prompt
msg = [{"role": "system", "content": prompt_config["system"].format(**kwargs)}]
```

---

## Comportement selon le statut Optional / Required

| Statut | Variable absente de la requête | Comportement |
|--------|-------------------------------|--------------|
| **Required** (`optional: false`) | Oui | `KeyError("Miss parameter: <key>")` → requête échoue |
| **Optional** (`optional: true`) | Oui | `{variable}` remplacé par un espace dans le prompt → dégradation gracieuse |
| Tout statut | Non (valeur fournie) | `{variable}` remplacé par la valeur fournie |

---

## Cas particulier : la clé `knowledge`

La clé `knowledge` **n'est pas validée** comme les autres (elle est sautée dans la boucle). Elle déclenche à la place le **pipeline RAG complet** :

1. Si `"knowledge" in param_keys` → récupération des chunks depuis les knowledge bases configurées (`dialog_service.py:604–678`).
2. Le résultat est injecté automatiquement par le backend dans `kwargs["knowledge"]` :

```python
kwargs["knowledge"] = "\n------\n" + "\n\n------\n\n".join(knowledges)
```

L'utilisateur **n'a pas besoin** de passer `knowledge` dans sa requête API — c'est toujours le backend qui la produit.

### Auto-fix

Si `{knowledge}` est présent dans le system prompt et que `knowledge` est absent des paramètres, le backend l'ajoute automatiquement en `optional: false` :

- `dialog_service.py:564–567` (à l'exécution)
- `chat_api.py:247–248` (à la création/mise à jour du dialog)

### Configuration par défaut (`chat_api.py:54–70`)

```json
{
  "system": "...{knowledge}...",
  "parameters": [{ "key": "knowledge", "optional": false }]
}
```

Pour les chat apps **sans knowledge base**, les paramètres sont vides par défaut (`chat_api.py:71–79`).

---

## Impact selon les choix de configuration

| Action | Impact |
|--------|--------|
| Retirer `knowledge` des variables | Pipeline RAG désactivé — le LLM répond sans contexte extrait des KB |
| Passer `knowledge` en Optional | Si absent de la requête API, `{knowledge}` est remplacé par un espace — pas de contexte RAG |
| Ajouter une variable custom Required | Tout appel API sans ce paramètre retourne une erreur — utile pour forcer le passage de contexte métier |
| Ajouter une variable custom Optional | Enrichit le prompt si fournie, sans bloquer les appels qui ne la passent pas |

---

## Fichiers de référence

| Fichier | Rôle |
|---------|------|
| `web/src/pages/next-chats/chat/app-settings/dynamic-variable.tsx` | Composant UI de configuration des variables |
| `web/src/pages/next-chats/chat/app-settings/use-chat-setting-schema.tsx` | Validation Zod (`prompt_config.parameters`) |
| `api/apps/restful_apis/chat_api.py:54–79` | Configurations par défaut (avec/sans KB) |
| `api/apps/restful_apis/chat_api.py:247–248` | Auto-fix à la création/mise à jour |
| `api/db/services/dialog_service.py:563–691` | Validation, récupération RAG et injection dans le prompt |
