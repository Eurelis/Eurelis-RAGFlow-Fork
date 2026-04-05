---
description: Génère ou vérifie un fichier conf/llm_factories.patch.json selon les guidelines Eurelis
allowed-tools: Bash(python3:*), Bash(curl:*), Bash(cat:*), Bash(ls:*), Read, Write
---

# /eurelis-ragflow-llm-factories-patch — Gestion des fichiers patch LLM

Génère ou vérifie un fichier `llm_factories.patch.json` selon les guidelines définies dans `docs/eurelis/guidelines/llm-factories-patch.md`.

## Paramètres

`$ARGUMENTS` = `<create|verify> <filepath>`

- `create <filepath>` — génère un fichier patch squelette à l'emplacement indiqué
- `verify <filepath>` — vérifie la conformité d'un fichier patch existant

Exemples :
- `/eurelis-ragflow-llm-factories-patch verify conf/llm_factories.patch.json`
- `/eurelis-ragflow-llm-factories-patch verify /chemin/absolu/llm_factories.patch.json`
- `/eurelis-ragflow-llm-factories-patch create docker/llm_factories.patch.json`

## Contexte courant (injecté au lancement)

- Répertoire courant : !`pwd`
- Arguments reçus : $ARGUMENTS

---

## ÉTAPE 0 — Parsing des arguments

Extraire `COMMAND` (premier mot) et `FILEPATH` (second mot) depuis `$ARGUMENTS`.

Si `COMMAND` n'est ni `create` ni `verify`, **arrêter** :
> ERREUR : commande inconnue. Usage : `/eurelis-ragflow-llm-factories-patch <create|verify> <filepath>`

Si `FILEPATH` est absent, **arrêter** :
> ERREUR : chemin manquant. Usage : `/eurelis-ragflow-llm-factories-patch <create|verify> <filepath>`

---

## MODE `verify`

### ÉTAPE V1 — Existence et syntaxe JSON

Vérifier que le fichier existe :
```bash
ls "<FILEPATH>"
```
Si absent, **arrêter** :
> ERREUR : fichier introuvable : `<FILEPATH>`

Vérifier la syntaxe JSON :
```bash
python3 -c "import json, sys; json.load(open('<FILEPATH>')); print('JSON valide')"
```
Si erreur, **arrêter** et afficher le message d'erreur Python.

### ÉTAPE V2 — Structure racine

Vérifier la présence de la clé `factory_llm_infos` :
```bash
python3 -c "import json; d=json.load(open('<FILEPATH>')); assert 'factory_llm_infos' in d, 'Clé factory_llm_infos manquante'"
```

### ÉTAPE V3 — Vérification de chaque entrée

Pour chaque provider dans `factory_llm_infos`, effectuer les contrôles suivants via un script Python inline :

```bash
python3 - << 'EOF'
import json, sys

REQUIRED_LLM_FIELDS = {"llm_name", "tags", "max_tokens", "model_type", "is_tools"}
TAG_ALIASES = {"1024K": "1M", "1024k": "1M"}

errors = []
warnings = []

with open("<FILEPATH>") as f:
    data = json.load(f)

for entry in data.get("factory_llm_infos", []):
    name = entry.get("name", "<sans nom>")

    if "name" not in entry:
        errors.append(f"[{name}] Champ 'name' manquant")

    for model in entry.get("llm", []):
        llm_name = model.get("llm_name", "<sans llm_name>")
        label = f"[{name}] {llm_name}"

        # Champs obligatoires
        missing = REQUIRED_LLM_FIELDS - set(model.keys())
        if missing:
            errors.append(f"{label} — champs manquants : {sorted(missing)}")

        tags = model.get("tags", "")
        model_type = model.get("model_type", "")
        tag_list = [t.strip() for t in tags.split(",")]

        # Cohérence model_type / tags IMAGE2TEXT
        has_image2text_tag = "IMAGE2TEXT" in tag_list
        is_multimodal_type = model_type == ["chat", "image2text"]
        if has_image2text_tag and not is_multimodal_type:
            errors.append(
                f"{label} — IMAGE2TEXT dans tags mais model_type={repr(model_type)} "
                f"(attendu: [\"chat\", \"image2text\"])"
            )
        if is_multimodal_type and not has_image2text_tag:
            warnings.append(
                f"{label} — model_type multimodal mais IMAGE2TEXT absent des tags"
            )

        # Cohérence model_type / tag EMBEDDING
        has_embedding_tag = any(t in tag_list for t in ("EMBEDDING", "TEXT EMBEDDING"))
        is_embedding_type = model_type == "embedding"
        if has_embedding_tag and not is_embedding_type:
            errors.append(
                f"{label} — tag embedding présent mais model_type={repr(model_type)} "
                f"(attendu: \"embedding\")"
            )

        # Normalisation du tag de contexte
        for alias, canonical in TAG_ALIASES.items():
            if alias in tag_list:
                warnings.append(
                    f"{label} — tag '{alias}' non normalisé, utiliser '{canonical}'"
                )

if errors:
    print("ERREURS :")
    for e in errors:
        print(f"  ✗ {e}")
if warnings:
    print("AVERTISSEMENTS :")
    for w in warnings:
        print(f"  ⚠ {w}")
if not errors and not warnings:
    print("✓ Fichier conforme aux guidelines.")
elif not errors:
    print("✓ Pas d'erreurs bloquantes.")

sys.exit(1 if errors else 0)
EOF
```

### ÉTAPE V4 — Vérification iso upstream (optionnel)

Si le fichier `conf/llm_factories.json` est présent dans le répertoire courant, proposer de vérifier qu'il est iso upstream :

```bash
UPSTREAM_URL="https://raw.githubusercontent.com/infiniflow/ragflow/main/conf/llm_factories.json"
LOCAL_FILE="${LOCAL_FILE:-conf/llm_factories.json}"
diff <(curl -s "$UPSTREAM_URL") "$LOCAL_FILE" && echo "✓ llm_factories.json iso upstream" || echo "⚠ llm_factories.json diverge de l'upstream"
```

### RAPPORT FINAL (verify)

```
Fichier : <FILEPATH>
─────────────────────────────────
<résultats V1 à V4>
─────────────────────────────────
<CONFORME | NON CONFORME — N erreur(s), M avertissement(s)>
```

---

## MODE `create`

### ÉTAPE C1 — Vérification que le fichier n'existe pas déjà

```bash
ls "<FILEPATH>" 2>/dev/null && echo "EXISTS" || echo "OK"
```

Si le fichier existe déjà, **arrêter** :
> ERREUR : `<FILEPATH>` existe déjà. Utilisez `verify` pour le vérifier ou supprimez-le manuellement avant de recréer.

### ÉTAPE C2 — Génération du squelette

Créer le fichier avec la structure minimale conforme :

```json
{
    "factory_llm_infos": [
        {
            "name": "<NomDuProvider>",
            "rank": "<entier 0-999>",
            "llm": [
                {
                    "llm_name": "<nom-du-modèle>",
                    "tags": "LLM,CHAT,<contexte>,<caps>",
                    "max_tokens": 0,
                    "model_type": "chat",
                    "is_tools": true
                }
            ]
        }
    ]
}
```

Afficher les rappels de la guideline :
- `model_type` : `"chat"` pour texte seul, `["chat", "image2text"]` pour multimodal, `"embedding"` pour embedding
- `tags` contexte normalisé : `32k`, `128k`, `200k`, `1M` (pas de `1024K`)
- Suffixe `::pii` sur `llm_name` pour activer le masquage PII
- `rank` : entier entre 0 et 999 sous forme de string
- `null` comme valeur supprime la clé du provider de base

Afficher la commande de vérification :
```
/eurelis-ragflow-llm-factories-patch verify <FILEPATH>
```

### RAPPORT FINAL (create)

```
✓ Fichier créé : <FILEPATH>
Éditez le fichier puis lancez :
/eurelis-ragflow-llm-factories-patch verify <FILEPATH>
```
