# Fix : add_llm — clé API Bedrock écrasée par la logique "existing key"

## Problème

Lors de l'ajout d'un modèle Bedrock depuis le frontend (page *Model Providers*), la requête échoue avec :

```
Fail to access model(Bedrock/<model_name>).Expecting value: line 1 column 1 (char 0)
```

L'erreur est un `json.JSONDecodeError` déclenché dans `LiteLLMBase._do_completion` quand il tente `json.loads(self.api_key)` sur une chaîne invalide (`"x"`).

## Cause racine

**Commit upstream introduisant la régression** : `050113482` — *Fix: support tool call config (#14616)*, intégré lors du sync `nightly` du 2026-05-08.

Ce commit a ajouté dans `add_llm()` (`api/apps/llm_app.py`) un bloc destiné à réutiliser la clé API existante en base quand le frontend ne renvoie pas de champ `api_key` :

```python
if req.get("api_key") is None:
    existing_llms = TenantLLMService.query(...)
    if existing_llms:
        existing_api_key = ...

if req.get("api_key") is None:
    api_key = existing_api_key if existing_api_key is not None else "x"
```

Pour Bedrock, les credentials sont envoyés par le frontend en champs séparés (`auth_mode`, `bedrock_ak`, `bedrock_sk`, `bedrock_region`, `aws_role_arn`), pas en `api_key`. La fonction assemble correctement le JSON :

```python
elif factory == "Bedrock":
    api_key = apikey_json(["auth_mode", "bedrock_ak", "bedrock_sk", "bedrock_region", "aws_role_arn"])
```

Mais comme `req.get("api_key")` est `None` pour Bedrock, le bloc ajouté par `050113482` écrase `api_key` avec `"x"` (ou la clé existante en base). `ChatModel["Bedrock"]` reçoit `"x"`, et `json.loads("x")` produit l'erreur.

Le même problème affecte potentiellement d'autres providers assemblant leur clé depuis des champs séparés (`VolcEngine`, `Google Cloud`, `Azure-OpenAI`...) si `req.get("api_key")` est `None` pour eux.

## Fix

**Fichier** : `api/apps/llm_app.py`

Écrire dans `req["api_key"]` au lieu d'une variable locale pour Bedrock, afin que la vérification `req.get("api_key") is None` soit `False` et que l'assemblage ne soit pas écrasé.

```python
# Avant
elif factory == "Bedrock":
    api_key = apikey_json(["auth_mode", "bedrock_ak", "bedrock_sk", "bedrock_region", "aws_role_arn"])

# Après
elif factory == "Bedrock":
    req["api_key"] = apikey_json(["auth_mode", "bedrock_ak", "bedrock_sk", "bedrock_region", "aws_role_arn"])
    api_key = req["api_key"]
```

## Compatibilité upstream

Le commit `050113482` est un fix upstream légitime (réutilisation de la clé en base lors d'une mise à jour partielle). Notre correctif est minimal et non-invasif : il ne modifie pas la logique générale, il positionne simplement `req["api_key"]` pour Bedrock de la même façon que Tencent Cloud le fait déjà (`req["api_key"] = apikey_json(...)`).

Ce fix pourra être proposé en PR upstream si d'autres providers sont affectés.

## Aucune migration BDD requise

Les entrées `tenant_llm` existantes ne sont pas affectées.
