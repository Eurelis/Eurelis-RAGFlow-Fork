---
title: "Gestion de `conf/llm_factories.patch.json`"
type: guideline
status: reference
---

# Gestion de `conf/llm_factories.patch.json`

## Principe

`conf/llm_factories.json` est un fichier upstream — il ne doit **jamais** être modifié dans le fork. Toutes les surcharges Eurelis (rangs des providers, nouveaux modèles, nouveaux providers) vivent dans `conf/llm_factories.patch.json`, appliqué au démarrage par `common/settings.py`.

## Règles de sécurité

| Fichier                         | Règle                                                                                                          |
|---------------------------------|----------------------------------------------------------------------------------------------------------------|
| `conf/llm_factories.json`       | Jamais modifié — iso upstream, vérifiable via `git diff upstream/main eurelis/main -- conf/llm_factories.json` |
| `conf/llm_factories.patch.json` | Commité sur `eurelis/main`, squashé dans le groupe `feat(eurelis/config):`                                     |

## Mécanisme d'application (`common/settings.py`)

Le patch est appliqué à chaque démarrage du serveur, après chargement de `llm_factories.json` :

1. **Provider existant** — les clés autres que `name` et `llm` écrasent la valeur de base (`null` supprime la clé) :
   ```json
   { "name": "Ollama", "rank": "830" }
   ```
   → remplace le `rank` d'Ollama dans la base.

2. **Nouveaux modèles** — les entrées `llm` sont **ajoutées** si `llm_name` est absent de la base (pas de doublon) :
   ```json
   { "name": "Gemini", "llm": [{ "llm_name": "gemini-3.5-flash::pii", ... }] }
   ```
   → ajoute le modèle à la liste Gemini existante.

3. **Nouveau provider** — si `name` n'existe pas dans la base, l'entrée entière est ajoutée :
   ```json
   { "name": "MonProvider", "rank": "500", "llm": [...] }
   ```

## Structure du fichier

```json
{
  "factory_llm_infos": [
    {
      "name": "<NomDuProvider>",
      "rank": "<entier entre 0 et 999>",
      "llm": [
        {
          "llm_name": "<nom-du-modèle>",
          "tags": "LLM,CHAT,<context>,<caps>",
          "max_tokens": <int>,
          "model_type": "chat",
          "is_tools": true
        }
      ]
    }
  ]
}
```

**Champs `llm` obligatoires** : `llm_name`, `tags`, `max_tokens`, `model_type`, `is_tools`.

**`model_type`** : `"chat"` pour les modèles texte seul, `["chat", "image2text"]` pour les modèles multimodaux.

**Suffixe `::pii`** : ajouter un modèle avec ce suffixe active le masquage PII automatique via Presidio (voir `rag/llm/pii_masking.py`).

## Cas d'usage courants

### Changer le rang d'un provider

```json
{ "name": "Ollama", "rank": "830" }
```

### Ajouter un modèle à un provider existant

```json
{
  "name": "Bedrock",
  "llm": [
    {
      "llm_name": "eu.anthropic.claude-opus-4-6-v1",
      "tags": "LLM,CHAT,200k,IMAGE2TEXT",
      "max_tokens": 200000,
      "model_type": "chat",
      "is_tools": true
    }
  ]
}
```

### Supprimer une clé d'un provider

```json
{ "name": "Replicate", "rank": null }
```
→ supprime la clé `rank` du provider Replicate (il n'apparaît plus trié par rang).

### Variante PII d'un modèle existant

```json
{
  "name": "Gemini",
  "llm": [
    {
      "llm_name": "gemini-3.5-flash::pii",
      "tags": "LLM,CHAT,1M,IMAGE2TEXT",
      "max_tokens": 1048576,
      "model_type": ["chat", "image2text"],
      "is_tools": true
    }
  ]
}
```

## Vérification après modification

```bash
# Vérifier que llm_factories.json est iso upstream
UPSTREAM_URL="https://raw.githubusercontent.com/infiniflow/ragflow/main/conf/llm_factories.json"
LOCAL_FILE="${LOCAL_FILE:-conf/llm_factories.json}"
diff <(curl -s "$UPSTREAM_URL") "$LOCAL_FILE" && echo "Identique à l'upstream" || echo "DIFFÉRENCES DÉTECTÉES"

# Vérifier la syntaxe du patch
python3 -c "import json; json.load(open('conf/llm_factories.patch.json')); print('OK')"
```
