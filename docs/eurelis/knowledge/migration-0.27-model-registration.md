---
title: "Note de migration RAGFlow 0.27.x — enregistrement des modèles"
type: knowledge
status: reference
date: 2026-09-06
---

# Note de migration RAGFlow 0.27.x — enregistrement des modèles

Migrations de données nécessaires sur une base existante après passage du fork sur RAGFlow `v0.27.x`, pour le sous-système d'enregistrement des modèles (`tenant_model_*`). Toutes sont implémentées dans `api/db/db_models.py` et exécutées automatiquement par `migrate_db()` au démarrage du serveur API. Cette note explique pourquoi elles existent, ce qu'elles font, et comment vérifier leur effet.

> Contexte général du système de modèles : [`llm-default-configuration.md`](llm-default-configuration.md). Gestion du catalogue patché : [`../guidelines/llm-factories-patch.md`](../guidelines/llm-factories-patch.md).

---

## 1. Pourquoi des migrations de données

Peewee crée les tables et **ajoute** les colonnes manquantes, mais ne modifie **jamais** une colonne existante. Deux refontes upstream successives ont changé le type ou la sémantique de colonnes déjà présentes, sans migration associée :

| Version upstream | Commit | Changement de schéma |
|---|---|---|
| `v0.25.0` | `62cb29263` — *Feat/tenant model (#13072)* | Ajout des colonnes `tenant_llm_id`, `tenant_embd_id`, … en `IntegerField`, clés vers l'ancienne table `tenant_llm`. |
| `v0.27.0` | `0ae5961e1` — *Feat: v0.27.0 model provider (#16604)* | Ces colonnes deviennent `CharField(32)` et référencent `tenant_model.id` (UUID). `tenant_model.model_type` passe de `varchar` (nom du type) à `int` (masque de bits). |

Une base créée avant `v0.27.0` conserve donc l'ancien type physique des colonnes, tandis que le code lit et écrit selon le nouveau. Un troisième écart est propre au fork : les modèles ajoutés au catalogue par `conf/llm_factories.patch.json` ne sont dépliés en base qu'à la création d'une instance de provider, jamais rétroactivement.

### Symptômes observés avant migration

- Sélecteurs « Modèles par défaut » affichant un nombre avec un triangle d'alerte (`⚠ 9`, `⚠ 5`, `⚠ 6`) à la place du label du modèle. Comportement différent d'un utilisateur à l'autre selon les champs réenregistrés depuis la refonte.
- Log serveur : `TypeError` sur `model_type & bit` (colonne `model_type` encore en `varchar`).
- Modèles chat Bedrock absents des listes de sélection alors que le provider est configuré ; erreurs `Model eu.anthropic.claude-sonnet-4-6@Default@Bedrock not found for model chat` sur les dialogs qui les référencent.
- Log serveur : `tenant_model id=9 not found, falling back to model_name lookup` à chaque résolution de modèle.

---

## 2. Les migrations, dans l'ordre d'exécution

L'ordre est imposé dans `migrate_db()` : la conversion de `model_type` doit précéder tout code qui lit `tenant_model`, et la resynchronisation catalogue doit s'exécuter après `settings.init_settings()` (le catalogue patché doit être chargé). L'ordre de démarrage de `api/ragflow_server.py` garantit ce dernier point.

### 2.1 `migrate_tenant_model_model_type_to_int()`

| | |
|---|---|
| Cible | `tenant_model.model_type` |
| Condition | la colonne est de type caractère (`information_schema`) |
| Action | `UPDATE` des noms vers leur bit (`chat`→1, `embedding`→2, `asr`/`speech2text`→4, `vision`/`image2text`→8, `rerank`→16, `tts`→32, `ocr`→64), valeurs inconnues forcées à 1, puis `ALTER` de la colonne en `INT NOT NULL DEFAULT 1` |
| Idempotence | ne fait rien si la colonne est déjà entière |

Limite : une ligne qui portait plusieurs types sous forme de chaîne n'est pas reconstituée, elle prend la valeur 1 (chat). La resynchronisation 2.3 ne la corrige pas non plus, puisque la ligne existe.

### 2.2 `migrate_tenant_model_id_columns_to_varchar()`

| | |
|---|---|
| Cibles | tout `CharField` nommé `tenant_<x>_id` des modèles `Tenant`, `Knowledgebase`, `Dialog`, `Memory` (dérivé des modèles Peewee, `tenant_id` exclu). Soit : `tenant.tenant_llm_id`, `tenant_embd_id`, `tenant_asr_id`, `tenant_img2txt_id`, `tenant_rerank_id`, `tenant_tts_id`, `tenant_ocr_id` ; `knowledgebase.tenant_embd_id` ; `dialog.tenant_llm_id`, `tenant_rerank_id` ; `memory.tenant_llm_id`, `tenant_embd_id` |
| Condition | la colonne est de type entier (`int`, `bigint`, …) |
| Action | `UPDATE … SET col = NULL`, puis `ALTER TABLE … MODIFY col VARCHAR(32) NULL` (MySQL) ou `ALTER COLUMN col TYPE VARCHAR(32) USING col::VARCHAR(32)` (PostgreSQL) |
| Idempotence | ne fait rien si la colonne est déjà en caractères |

Pourquoi remettre à NULL : sur une colonne `int`, MySQL tronque l'UUID écrit par le code à son préfixe numérique (`09f0276e…` → `9`, `5b92fa0a…` → `5`, `f90068ae…` → `0`). Les valeurs stockées ne portent aucune information et ne correspondent à aucune ligne `tenant_model`. Le code de résolution retombe sur le nom composite `modele@instance@provider` quand l'id est NULL, donc aucune perte fonctionnelle. Le prochain enregistrement via l'UI stocke l'UUID complet.

### 2.3 `sync_tenant_model_instances_with_catalogue()`

| | |
|---|---|
| Cible | `tenant_model`, pour chaque instance active de `tenant_model_instance` |
| Condition | une entrée du catalogue `FACTORY_LLM_INFOS` du provider de l'instance (patch inclus, variante `siliconflow_intl` selon la région de l'instance) n'a pas de ligne `tenant_model` |
| Action | insertion d'une ligne `active`, avec le masque de types et un `extra` identique à celui produit à la création d'instance (`max_tokens`, `is_tools`, `thinking`, `verify: unknown`) |
| Idempotence | les lignes existantes ne sont jamais modifiées, quel que soit leur statut ou leur `extra` |

Cette fonction remplace la migration antérieure `migrate_tenant_default_rerank_models`, limitée aux rerank par défaut des tenants. Elle couvre aussi les futurs ajouts au patch : un modèle ajouté à `llm_factories.patch.json` apparaît dans toutes les instances existantes au redémarrage suivant, sans recréer d'instance.

Limite : un provider dont le catalogue est vide (cas de Bedrock dans le `llm_factories.json` upstream, sans patch) n'est pas touché. Les instances inactives sont ignorées.

---

## 3. Vérification après migration

Types de colonnes (MySQL) :

```sql
SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'rag_flow'
  AND (COLUMN_NAME REGEXP '^tenant_[a-z0-9]+_id$'
       OR (TABLE_NAME = 'tenant_model' AND COLUMN_NAME = 'model_type'))
ORDER BY 1, 2;
-- attendu : varchar(32) partout, int pour tenant_model.model_type
```

Absence d'ids tronqués :

```sql
SELECT 'tenant', COUNT(*) FROM tenant
 WHERE LENGTH(tenant_llm_id) < 32 OR LENGTH(tenant_embd_id) < 32 OR LENGTH(tenant_rerank_id) < 32
UNION ALL SELECT 'dialog', COUNT(*) FROM dialog WHERE LENGTH(tenant_llm_id) < 32
UNION ALL SELECT 'knowledgebase', COUNT(*) FROM knowledgebase WHERE LENGTH(tenant_embd_id) < 32;
-- attendu : 0 partout (NULL n'est pas compté)
```

Couverture des instances par le catalogue :

```sql
SELECT p.tenant_id, p.provider_name, i.instance_name, COUNT(m.id) AS models
FROM tenant_model_instance i
JOIN tenant_model_provider p ON p.id = i.provider_id
LEFT JOIN tenant_model m ON m.instance_id = i.id
GROUP BY 1, 2, 3;
-- attendu : au moins le nombre d'entrées du catalogue du provider (13 pour Bedrock avec le patch actuel)
```

Log serveur au démarrage : lignes `Migrated tenant_model.model_type …`, `Migrated <table>.<col> from int to varchar(32)`, `Synced N missing tenant_model rows from the model catalogue`. Un second démarrage ne doit plus produire aucune de ces lignes.

Tests unitaires, sans stack :

```bash
PYTHONPATH=. .venv/bin/python -m pytest test/eurelis/unit/test_migrate_tenant_model_id_columns.py test/eurelis/unit/test_sync_tenant_model_catalogue.py -q
```

---

## 4. Actions manuelles restantes

Les migrations ne reconstruisent pas ce que la base ne contient plus.

- **Instances supprimées encore référencées.** La suppression d'une instance ne met pas à jour `knowledgebase.embd_id`, `dialog.llm_id` ni les défauts `tenant.*_id`. Une référence `modele@Admin@OpenAI` vers une instance « Admin » disparue échoue avec `Instance Admin not found for model …`. Recréer une instance du même nom dans le même tenant rétablit toutes les références sans réindexation ; changer le modèle d'embedding d'une KB impose au contraire de reparser ses documents.
- **Modèles par défaut.** Après 2.2, les `tenant_*_id` sont NULL : la résolution passe par le nom composite, ce qui suffit. Resélectionner les modèles dans « Modèles par défaut » stocke les UUID et rend la résolution directe.
- **Références vers un autre tenant.** Un dialog peut pointer un `tenant_model.id` d'un autre tenant ; c'est accepté si le tenant du dialog est membre du tenant propriétaire (`get_model_config_by_id`), sinon `Tenant … has no access to provider owned by tenant …`.

---

## 5. Points de code à connaître

| Fichier | Rôle |
|---|---|
| `api/db/db_models.py` — `migrate_db()` | Point d'appel des trois migrations, après les migrations upstream |
| `api/db/db_models.py` — `_tenant_model_id_columns()` | Dérivation des colonnes cibles depuis les modèles Peewee |
| `api/db/joint_services/tenant_model_service.py` — `resolve_model_config`, `get_tenant_default_model_by_type` | Résolution par id puis repli sur le nom composite |
| `api/apps/services/models_api_service.py` — `_get_model_info` | Alimente les sélecteurs de défauts ; renvoie `tenant_*_id` tel quel, sans vérifier qu'il existe dans `tenant_model` (garde encore à ajouter) |
| `api/apps/services/provider_api_service.py` — `create_provider_instance` | Dépliage du catalogue à la création d'instance, modèle de la resynchronisation 2.3 |
| `web/src/components/model-tree-select.tsx` | Sélecteur : les feuilles ont pour id les UUID `tenant_model`, avec table de correspondance depuis le nom composite ; une valeur inconnue s'affiche brute avec un triangle d'alerte |
