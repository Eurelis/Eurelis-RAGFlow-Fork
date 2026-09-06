---
title: "Configuration des modèles LLM par tenant"
type: knowledge
status: reference
date: 2026-06-29
---

# Configuration des modèles LLM par tenant

Comment les modèles LLM sont déclarés, configurés par tenant et résolus à l'exécution dans RAGFlow.

> **Deux générations de configuration coexistent dans le code.** Ce document décrit le **système actuel** (`tenant_model_*` : provider / instance), qui est celui que peuple l'UI et que consomme la résolution runtime. L'ancien système `tenant_llm` / tables DB `llm_factories` & `llm` est **obsolète** : il n'est plus écrit à la création de compte ni lu pour la résolution. Il est traité en [annexe legacy](#annexe--système-legacy-tenant_llm). Le détail des constats de validation se trouve dans [`admin-model-supervision.md`](../features/done/admin-model-supervision.md).

---

## Vue d'ensemble

Un modèle utilisable dans RAGFlow résulte de la combinaison de **deux briques** :

1. **Le catalogue en mémoire `FACTORY_LLM_INFOS`** — la liste des providers et des modèles connus, chargée au démarrage depuis `conf/llm_factories.json`. C'est ce catalogue (et non une table DB) qui alimente les sélecteurs de l'UI.
2. **La configuration par tenant `tenant_model_*`** — provider + instance (porteuse de l'`api_key`) déclarés par l'utilisateur via l'UI. Sans instance configurée, un modèle du catalogue n'est pas utilisable.

La résolution à l'exécution combine les défauts du tenant (`Tenant.llm_id`, `embd_id`…) et la hiérarchie `tenant_model_*`.

---

## 1. Le catalogue `FACTORY_LLM_INFOS`

**Source :** `conf/llm_factories.json` (clé `factory_llm_infos`), surchargé par `conf/llm_factories.patch.json` s'il existe.
**Chargement :** une fois au démarrage, en mémoire — `common/settings.py:243-276` (`FACTORY_LLM_INFOS`).

```
conf/llm_factories.json
        │  (+ conf/llm_factories.patch.json en overlay)
        │  chargé au boot — common/settings.py:243
        ▼
settings.FACTORY_LLM_INFOS   (liste en mémoire : providers → modèles)
        │
        ├──► énumération des modèles d'un provider dans l'UI
        │    (models_api_service.py:145, provider_api_service.py:74…)
        └──► whitelist des providers proposés (ALLOWED_LLM_FACTORIES)
             api/utils/api_utils.py:709
```

> **Important.** Le catalogue est **en mémoire**. Les tables DB `llm_factories` et `llm` ne sont **plus peuplées** : la fonction `init_llm_factory()` qui les remplissait est marquée `# todo deprecated` et son appel est **commenté** (`api/db/init_data.py:193`). Ne pas s'y référer pour raisonner sur les modèles disponibles.

La gestion du fichier `llm_factories.json` / `.patch.json` est documentée dans [`guidelines/llm-factories-patch.md`](../guidelines/llm-factories-patch.md).

Les migrations de données à appliquer sur une base antérieure à `v0.27.0` (types de colonnes `tenant_*_id` et `model_type`, resynchronisation du catalogue) sont consignées dans [`migration-0.27-model-registration.md`](migration-0.27-model-registration.md).

### Valeurs de `model_type`

Chaque modèle du catalogue porte un `model_type` qui détermine dans quels contextes il peut être utilisé, et à quel champ de défaut du `Tenant` il se rattache :

| `model_type` | Champ défaut dans `tenant` | Usages |
| --- | --- | --- |
| `chat` | `llm_id` | Conversations (dialog), agents, génération de texte, résumés, Q&A |
| `embedding` | `embd_id` | Vectorisation des documents à l'indexation et des requêtes à la recherche |
| `image2text` | `img2txt_id` | Extraction de texte depuis des images (figures, captures d'écran dans les PDFs) |
| `speech2text` | `asr_id` | Transcription audio (ASR — Automatic Speech Recognition) |
| `rerank` | `rerank_id` | Reranking des chunks candidats après la recherche vectorielle |
| `tts` | `tts_id` | Synthèse vocale des réponses (Text-to-Speech) |
| `ocr` | `ocr_id` | OCR dédié (pipelines de parsing) |

> **Note** : `reranker` est un alias de `rerank` présent dans certaines entrées du JSON ; les deux valeurs sont traitées de façon identique par le code.

Un modèle dont le `model_type` ne correspond pas au contexte d'usage ne sera jamais proposé dans le sélecteur UI correspondant (un modèle `chat` ne peut pas être choisi comme embedding, et inversement).

---

## 2. La configuration par tenant (`tenant_model_*`)

Un utilisateur déclare ses modèles via l'UI moderne, qui appelle les endpoints RESTful `/api/v1/providers/*` et `/api/v1/models/*` (`api/apps/restful_apis/provider_api.py`, `models_api.py`), eux-mêmes adossés à `api/apps/services/provider_api_service.py` et `models_api_service.py`.

```
   ┌──────────────────────────────┐
   │   TenantModelProvider        │  le provider, scopé tenant
   │   UNIQUE(tenant_id,           │  (OpenAI, Bedrock, Gemini…)
   │          provider_name)       │
   └──────────────┬───────────────┘
                  │ provider_id
                  ▼
   ┌──────────────────────────────┐
   │   TenantModelInstance        │  🔑 porte l'api_key
   │   instance_name (saisi user)  │  (1 compte/clé du provider)
   │   api_key, status, extra(JSON)│  extra = base_url, etc.
   └──────────────┬───────────────┘
                  │ instance_id
                  ▼
   ┌──────────────────────────────┐
   │   TenantModel  (optionnel)   │  surcharge d'un modèle du catalogue
   │   model_name, model_type      │  → VIDE en pratique : les modèles
   │   status, extra(JSON)         │    viennent de FACTORY_LLM_INFOS
   └──────────────────────────────┘
```

Référence modèles DB : `api/db/db_models.py` (`TenantModelProvider`/`Instance`/`Model`, ~lignes 1403-1458).

Points essentiels :

- **L'`api_key` est portée par l'instance** (`TenantModelInstance`), pas par le modèle. Une instance = un compte/clé chez le provider. Pour les factories complexes (Bedrock, Azure-OpenAI, VolcEngine…), `api_key` est un **payload JSON**.
- **Le nom d'instance est saisi par l'utilisateur** (`default`, `Admin`, …) — il n'est pas fixe.
- **`tenant_model` est vide en pratique** : les modèles ne sont pas matérialisés par tenant ; ils sont énumérés depuis le catalogue `FACTORY_LLM_INFOS` (filtré aux providers du tenant). `tenant_model` ne sert qu'à *surcharger* (statut/extra) un modèle du catalogue, s'il existe.
- **Pas de FK réelle** : les liens sont logiques (`provider_id`, `instance_id`). Une requête cross-tenant est un simple filtre `WHERE tenant_id = …`.

> Un embedding **builtin TEI** (profil `tei-`) est une exception : il est résolu par un bypass dédié sans provider/instance (`tenant_model_service.py:195`).

---

## 3. Les modèles par défaut du tenant et leur résolution

Le `Tenant` (où `id == user_id` du propriétaire) stocke un défaut par type — `llm_id`, `embd_id`, `asr_id`, `img2txt_id`, `rerank_id`, `tts_id`, `ocr_id` — au format **`model@instance@provider`** (3 parties).

La résolution runtime passe par `get_model_config_from_provider_instance()` (`api/db/joint_services/tenant_model_service.py`), qui éclate la chaîne via `split_model_name()` puis reconstruit le `model_config` à partir de `Provider → Instance` (+ catalogue). Ce chemin est utilisé partout où un modèle est consommé : `dialog_service.py`, `chat_api.py`, `bot_api.py`, `openai_api.py`, `chunk_api.py`, `api_utils.py`…

> **Défaut « pendant ».** Un défaut au format `model@factory` (2 parties, tel que pré-rempli par `user_default_llm`, cf. §4) **n'est pas résoluble** tant qu'aucun provider/instance correspondant n'existe chez le tenant. C'est le cas typique d'un nouvel utilisateur sans configuration : ses défauts pointent dans le vide et l'UI lui demande d'« ajouter d'abord un embedding + un LLM » avant de pouvoir créer un chat.

> **Consommateur de chats partagés.** Un utilisateur qui n'utilise que des chats `permission=team` d'un autre tenant n'a **aucune** config modèle propre : la résolution se fait contre le tenant **propriétaire** du chat (`dialog_service.py` → `get_model_config_from_provider_instance(dialog.tenant_id, …)`).

---

## 4. `user_default_llm` (`docker/service_conf.yaml.template`)

`user_default_llm` est chargé au démarrage (`common/settings.py`) en `LLM_FACTORY`, `API_KEY`, `CHAT_MDL`/`EMBEDDING_MDL` (format `model@factory`), `ALLOWED_LLM_FACTORIES`, `PARSERS`. À la création d'un tenant, il pose `Tenant.llm_id`/`embd_id`/… depuis ces valeurs.

⚠️ **Pour les providers externes (OpenAI, Bedrock, Gemini…), la partie `default_models` est largement vestigiale** : elle pose des **pointeurs pendants** sur `Tenant.*_id` sans créer ni provider ni instance. Le nouvel utilisateur ne peut donc pas chatter tant qu'il n'a pas configuré un provider lui-même.

| Élément de `user_default_llm` | Statut |
| --- | --- |
| `default_models` (chat/embedding) — provider externe | ❌ **vestigial** : pointeur pendant, ne rend pas l'utilisateur autonome |
| Embedding **builtin TEI** (profil `tei-`) | ✅ vivant : résolu par le bypass dédié, fonctionnel sans config manuelle |
| `parsers` (`PARSERS` → `parser_ids` par défaut) | ✅ vivant |
| `allowed_factories` (`ALLOWED_LLM_FACTORIES`, whitelist) | ✅ vivant (`api_utils.py:709`) |

> Pour rendre un nouvel utilisateur autonome avec un provider externe, copier le défaut ne suffit pas — il faut **créer le Provider + l'Instance**. C'est ce qu'apporte la **supervision admin des modèles** (cf. §6), pas `user_default_llm`.

> **Gotcha — deux process.** `service_conf.yaml` est lue **au démarrage** par **deux process distincts** : l'API (`9380`) et l'admin (`9381`), chacun avec son propre snapshot `settings`. Tout changement impose de **redémarrer les deux** (sinon un utilisateur créé via l'admin reflète l'ancienne config).

### Exemples de configuration provider

Ces blocs restent la référence pour amorcer `user_default_llm` (whitelist, parsers, et — avec la réserve ci-dessus — pré-remplissage des défauts).

#### OpenAI

```yaml
user_default_llm:
  factory: "OpenAI"
  api_key: "${OPENAI_API_KEY:-}"
  base_url: "https://api.openai.com/v1"
  default_models:
    chat_model:
      name: "gpt-4o"
    embedding_model:
      name: "text-embedding-3-small"
```

```env
# docker/.env
OPENAI_API_KEY=sk-proj-...
```

Les modèles OpenAI sont déjà présents dans `llm_factories.json`.

#### Bedrock

```yaml
user_default_llm:
  factory: "Bedrock"
  api_key: '{"auth_mode": "access_key_secret", "bedrock_ak": "${AWS_ACCESS_KEY_ID:-}",
    "bedrock_sk": "${AWS_SECRET_ACCESS_KEY:-}", "bedrock_region":
    "${AWS_DEFAULT_REGION:-eu-west-1}"}'
  default_models:
    chat_model:
      name: "eu.amazon.nova-pro-v1:0"
    embedding_model:
      name: "amazon.titan-embed-text-v2:0"
```

```env
# docker/.env
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=eu-west-1
```

> Le champ `api_key` est un JSON encodé en YAML single-quoted string. `auth_mode` doit valoir `"access_key_secret"` pour l'authentification par clé explicite.

Les modèles Bedrock doivent être déclarés explicitement dans `conf/llm_factories.json` (contrairement à OpenAI) :

```json
{
  "name": "Bedrock",
  "logo": "",
  "tags": "LLM,TEXT EMBEDDING",
  "status": "1",
  "rank": "860",
  "llm": [
    { "llm_name": "eu.amazon.nova-2-lite-v1:0", "tags": "LLM,CHAT,300k", "max_tokens": 300000, "model_type": "chat", "is_tools": true },
    { "llm_name": "eu.amazon.nova-pro-v1:0", "tags": "LLM,CHAT,300k", "max_tokens": 300000, "model_type": "chat", "is_tools": true },
    { "llm_name": "eu.anthropic.claude-opus-4-6-v1", "tags": "LLM,CHAT,200k", "max_tokens": 200000, "model_type": "chat", "is_tools": true },
    { "llm_name": "eu.anthropic.claude-sonnet-4-6", "tags": "LLM,CHAT,200k", "max_tokens": 200000, "model_type": "chat", "is_tools": true },
    { "llm_name": "mistral.mistral-large-2402-v1:0", "tags": "LLM,CHAT,32k", "max_tokens": 32000, "model_type": "chat", "is_tools": true },
    { "llm_name": "amazon.titan-embed-text-v2:0", "tags": "TEXT EMBEDDING,8k", "max_tokens": 8192, "model_type": "embedding", "is_tools": false }
  ]
}
```

#### Gemini

```yaml
user_default_llm:
  factory: "Gemini"
  api_key: "${GEMINI_API_KEY:-}"
  default_models:
    chat_model:
      name: "gemini-3.1-pro-preview"
    embedding_model:
      name: "gemini-embedding-001"
```

```env
# docker/.env
GEMINI_API_KEY=AIza...
```

La clé est obtenue depuis [Google AI Studio](https://aistudio.google.com/app/apikey). Modèles disponibles :

| `llm_name` | Type | Contexte |
| --- | --- | --- |
| `gemini-3.1-pro-preview` | chat | 1 M tokens |
| `gemini-3-flash-preview` | chat | 1 M tokens |
| `gemini-3.1-flash-lite-preview` | chat | 1 M tokens |
| `gemini-embedding-001` | embedding | 2 048 tokens |

### Modes d'authentification Bedrock

| `auth_mode` | Description | Champs requis |
| --- | --- | --- |
| `access_key_secret` | Clé AWS explicite | `bedrock_ak`, `bedrock_sk`, `bedrock_region` |
| `iam_role` | Assume Role via STS | `aws_role_arn`, `bedrock_region` |
| autre | Credential chain AWS par défaut (instance profile, etc.) | `bedrock_region` |

---

## 5. Partage et propagation aux tenants

Rappel du scoping : chaque utilisateur est son propre tenant (`tenant_id == user_id`), et **tous les membres d'un tenant partagent la même configuration de modèles** (providers/instances) configurée une fois par l'owner. Il n'existe pas de modèle « global » partagé entre tenants. Pour la gestion des membres et des rôles, voir [`user-and-admin-management.md`](./user-and-admin-management.md).

- Ajouter un modèle dans `conf/llm_factories.json` (ou son patch) enrichit le **catalogue** au prochain redémarrage, mais ne crée aucune instance chez les tenants existants.
- Modifier `user_default_llm` n'affecte que les **nouveaux comptes** créés après le redémarrage (et de façon vestigiale pour les providers externes, cf. §4).
- Pour **propager une configuration de modèle (provider + instance + défauts) vers des tenants existants**, utiliser la **supervision admin des modèles** : copie d'instance / copie des défauts vers une liste de tenants cibles. Voir [`admin-model-supervision.md`](../features/done/admin-model-supervision.md).

| Besoin | Possible | Méthode |
|---|---|---|
| Partager une config modèle entre membres d'un même tenant | ✅ | Natif — l'owner configure une instance une fois (Settings → Model providers) |
| Amorcer les défauts de tous les **nouveaux** utilisateurs | ⚠️ | `user_default_llm` (défauts seulement ; vestigial pour providers externes — cf. §4) |
| Propager une config (provider + instance + défauts) aux tenants **existants** | ✅ | Supervision admin des modèles (copie d'instance / des défauts) |
| Partager un modèle entre tenants en temps réel | ❌ | Non supporté nativement |

> ⚠️ **Ne pas tenter `UPDATE tenant_llm SET api_key …`** pour mettre à jour une clé : `tenant_llm` est legacy et **n'est pas lue** pour la résolution — sans effet runtime. La clé vit dans `tenant_model_instance.api_key` ; la voie supportée est la supervision admin (ou, en dernier recours, un SQL ciblant `tenant_model_instance`).

---

## 6. Dépannage

### `hint : 102 'llm_id' <modèle>@<factory> doesn't exist`

Le modèle référencé (base de connaissances, agent, dialogue, pipeline de parsing) n'est pas résoluble pour ce tenant.

Causes fréquentes :
- Aucun **provider/instance** correspondant n'a été configuré chez le tenant (défaut « pendant » au format `model@factory` — cf. §3).
- Le provider correspondant n'est pas autorisé (`ALLOWED_LLM_FACTORIES`) ou absent du catalogue (`llm_factories.json`).
- Le modèle a été saisi avec un nom incorrect, ou retiré du catalogue sans mettre à jour les configurations qui le référencent.

→ Voir la [FAQ dédiée sur Confluence](https://eurelis.atlassian.net/wiki/spaces/AILAB/pages/1359839246).

### Après modification de la configuration

Redémarrer le conteneur RAGFlow (et donc **les deux process**, cf. §4) :

```bash
cd docker
docker compose down
docker compose up -d
```

---

## Annexe — Système legacy `tenant_llm`

> Conservé à titre documentaire. **Ne pas s'appuyer dessus pour la configuration des modèles.**

L'ancienne génération reposait sur la chaîne `conf/llm_factories.json` → `init_llm_factory()` → tables DB `llm_factories` & `llm` → `get_init_tenant_llm()` → table `tenant_llm` → défauts du `Tenant`. Elle est aujourd'hui désactivée :

| Élément legacy | État actuel |
| --- | --- |
| `init_llm_factory()` (peuple les tables DB `llm_factories` / `llm`) | `# todo deprecated` ; **appel commenté** (`api/db/init_data.py:193`) |
| `get_init_tenant_llm()` à la création de compte | **commenté** dans `user_account_service.py:91` et `restful_apis/user_api.py:455` — un nouveau compte n'écrit plus `tenant_llm` |
| Écriture de `tenant_llm` | Seulement au **boot superuser** (`init_data.py:79-90`) et par les vieux endpoints `/v1/llm/*` (`api/apps/llm_app.py`), non appelés par l'UI moderne |
| Lecture pour la **résolution** de modèle | ❌ aucune — la résolution passe par `get_model_config_from_provider_instance` (système `tenant_model_*`) |
| `tenant_llm.used_tokens` (tracking conso) | ❌ **code mort** : `TenantLLMService.increase_usage` n'a aucun appelant ; les compteurs sont figés. La consommation réelle relève de [`specs/usage-stats/`](../specs/usage-stats/usage-log-table.md) |
| Résidu en base (ex. Synerga : 136 lignes) | résidu pré-migration, sans rôle fonctionnel |

Lecture résiduelle restante : `tenant_utils.ensure_tenant_model_id_for_params` (via `chat_api.py`) remplit les colonnes vestigiales `tenant_*_id` du chat, que la résolution n'utilise pas.
