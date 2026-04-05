# Fix : PDF parser — fallback IMAGE2TEXT → CHAT manquant

## Problème

Lors de l'utilisation d'un modèle LLM comme PDF parser (section **General** → **PDF Parser** d'une knowledge base), l'ingestion échoue avec :

```
Tenant Model with name <model>@<factory> and type image2text not found
```

Cela se produit pour les modèles déclarés avec `model_type: "chat"` dans `llm_factories.json` même lorsqu'ils ont le tag `IMAGE2TEXT` (ex : `eu.amazon.nova-2-lite-v1:0@Bedrock`).

## Cause racine

La fonction `get_model_config_by_type_and_name` (`api/db/joint_services/tenant_model_service.py:35`) résout les modèles en cherchant dans `tenant_llm` par `(llm_name, model_type)`. Le champ `model_type` dans `tenant_llm` est copié depuis `llm_factories.json` à la création du compte.

Il existe déjà un fallback **CHAT → IMAGE2TEXT** (ligne 62-64) : quand un modèle `chat` est demandé et non trouvé, le code réessaie avec `image2text`. Mais le fallback symétrique **IMAGE2TEXT → CHAT** est absent : un modèle `chat` ne peut pas être résolu quand `image2text` est demandé, même s'il a le tag `IMAGE2TEXT`.

Le tag `IMAGE2TEXT` dans `llm_factories.json` est une convention **frontend uniquement** — il contrôle l'affichage dans le sélecteur de PDF parser mais n'est jamais consulté par le backend à l'exécution.

## Analyse de compatibilité avec la philosophie upstream

Le fallback CHAT→IMAGE2TEXT existant est **motivé par la capacité** : un modèle `image2text` est par définition multimodal, il peut *toujours* faire du chat. La substitution est sémantiquement sûre dans tous les cas.

Un fallback naïf IMAGE2TEXT→CHAT (essayer n'importe quel modèle `chat`) ne respecterait pas cette philosophie : un modèle `chat` sans capacité vision répondrait à la résolution mais échouerait silencieusement à l'usage.

**Le fix doit vérifier la capacité vision avant de substituer**, en consultant le champ `tags` de la table `llm` — la même source que le frontend utilise pour peupler le sélecteur PDF parser. Un modèle `chat` n'est accepté en fallback que s'il porte le tag `IMAGE2TEXT`.

Aucun fix équivalent n'existe dans l'upstream à la date de rédaction (post-v0.25.1, vérifié sur `main` le 2026-05-08).

## Fix

**Fichier** : `api/db/joint_services/tenant_model_service.py`

### 1. Ajouter le fallback IMAGE2TEXT → CHAT avec vérification du tag

```python
# Avant (lignes 60-72)
elif model_type_val == LLMType.CHAT.value:
    model_config = TenantLLMService.get_api_key(tenant_id, pure_model_name, LLMType.CHAT.value)
    if not model_config:
        model_config = TenantLLMService.get_api_key(tenant_id, pure_model_name, LLMType.IMAGE2TEXT.value)
    if not model_config:
        raise LookupError(f"Tenant Model with name {model_name} and type {model_type_val} not found")
    config_dict = model_config.to_dict()
else:
    model_config = TenantLLMService.get_api_key(tenant_id, pure_model_name, model_type_val)
    if not model_config:
        raise LookupError(f"Tenant Model with name {model_name} and type {model_type_val} not found")
    config_dict = model_config.to_dict()
```

```python
# Après
elif model_type_val == LLMType.CHAT.value:
    model_config = TenantLLMService.get_api_key(tenant_id, pure_model_name, LLMType.CHAT.value)
    if not model_config:
        model_config = TenantLLMService.get_api_key(tenant_id, pure_model_name, LLMType.IMAGE2TEXT.value)
    if not model_config:
        raise LookupError(f"Tenant Model with name {model_name} and type {model_type_val} not found")
    config_dict = model_config.to_dict()
elif model_type_val == LLMType.IMAGE2TEXT.value:
    model_config = TenantLLMService.get_api_key(tenant_id, pure_model_name, LLMType.IMAGE2TEXT.value)
    if not model_config:
        # Fall back to a chat model only if it has declared IMAGE2TEXT capability (tag check via llm table)
        chat_config = TenantLLMService.get_api_key(tenant_id, pure_model_name, LLMType.CHAT.value)
        if chat_config:
            llm_entry = LLMService.query(llm_name=chat_config.to_dict()["llm_name"])
            if llm_entry and "IMAGE2TEXT" in (llm_entry[0].tags or ""):
                model_config = chat_config
    if not model_config:
        raise LookupError(f"Tenant Model with name {model_name} and type {model_type_val} not found")
    config_dict = model_config.to_dict()
else:
    model_config = TenantLLMService.get_api_key(tenant_id, pure_model_name, model_type_val)
    if not model_config:
        raise LookupError(f"Tenant Model with name {model_name} and type {model_type_val} not found")
    config_dict = model_config.to_dict()
```

### 2. Étendre la vérification de type pour autoriser CHAT résolu en IMAGE2TEXT

```python
# Avant (lignes 78-84)
if config_model_type != model_type_val and not (
        model_type_val == LLMType.CHAT.value
        and config_model_type == LLMType.IMAGE2TEXT.value
):
    raise LookupError(
        f"Tenant Model with name {model_name} has type {config_model_type}, expected {model_type_val}"
    )
```

```python
# Après
if config_model_type != model_type_val and not (
        model_type_val == LLMType.CHAT.value
        and config_model_type == LLMType.IMAGE2TEXT.value
) and not (
        model_type_val == LLMType.IMAGE2TEXT.value
        and config_model_type == LLMType.CHAT.value
):
    raise LookupError(
        f"Tenant Model with name {model_name} has type {config_model_type}, expected {model_type_val}"
    )
```

## Résultat attendu

Avec ce fix, un modèle déclaré `model_type: "chat"` avec le tag `IMAGE2TEXT` dans `llm_factories.json` :

| Contexte                            | Sans fix             | Avec fix                                       |
|-------------------------------------|----------------------|------------------------------------------------|
| Sélecteur chat (UI)                 | ✓ apparaît           | ✓ apparaît                                     |
| PDF parser (UI)                     | ✓ apparaît (via tag) | ✓ apparaît (via tag)                           |
| Ingestion PDF parser                | ✗ erreur `not found` | ✓ fonctionne                                   |
| Utilisation en chat                 | ✓ fonctionne         | ✓ fonctionne                                   |
| Modèle `chat` sans tag `IMAGE2TEXT` | —                    | ✗ non substitué (garanti par vérification tag) |

## Aucune migration BDD requise

Les entrées `tenant_llm` existantes avec `model_type = "chat"` n'ont pas besoin d'être modifiées.

## Contexte

Constaté sur `eu.amazon.nova-2-lite-v1:0@Bedrock`. Gemini contourne le problème car ses modèles ont été créés en base avec `model_type = "image2text"` (valeur d'origine dans `llm_factories.json` upstream), ce qui les rend invisibles dans le sélecteur chat de l'UI — comportement non souhaité.
