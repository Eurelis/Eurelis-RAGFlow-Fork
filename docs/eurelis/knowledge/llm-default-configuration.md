# LLM Default Configuration

Configuration du LLM par défaut dans `docker/service_conf.yaml.template`.

Deux fichiers sont concernés :
- `docker/service_conf.yaml.template` — credentials et modèle par défaut
- `conf/llm_factories.json` — liste des modèles disponibles dans l'UI

## Fonctionnement

Au démarrage, RAGFlow génère `conf/service_conf.yaml` depuis le template en substituant les variables d'environnement. À l'initialisation de la base de données, les modèles définis dans `conf/llm_factories.json` sont chargés en base. Lors de la création d'un compte utilisateur, tous les modèles du factory configuré lui sont automatiquement assignés.

## Cycle de mise à jour détaillé

```
conf/llm_factories.json
        │
        │  init_llm_factory()          api/db/init_data.py:111
        ▼  (au démarrage, 1 fois)
┌─────────────────┐    ┌──────────────────────────────────────┐
│  llm_factories  │    │  llm                                 │
│  (providers)    │    │  (catalogue global des modèles)      │
│  name (PK)      │───▶│  fid + llm_name (PK composite)       │
│  tags, rank…    │    │  model_type, max_tokens, is_tools…   │
└─────────────────┘    └──────────────┬───────────────────────┘
                                       │
        service_conf.yaml              │  get_init_tenant_llm()
        user_default_llm.factory ──────┤  api/db/services/llm_service.py:64
                                       │  (à chaque création de compte)
                                       ▼
                        ┌──────────────────────────────────────┐
                        │  tenant_llm                          │
                        │  (modèles instanciés par tenant)     │
                        │  tenant_id + llm_factory + llm_name  │
                        │  api_key, api_base, model_type…      │
                        └──────────────┬───────────────────────┘
                                       │
                                       │  user_account_service.py:67
                                       ▼
                        ┌──────────────────────────────────────┐
                        │  tenant                              │
                        │  llm_id, embd_id, rerank_id…         │
                        │  (pointeurs vers les modèles défaut) │
                        └──────────────────────────────────────┘
```

### Tables impliquées

| Table | Rôle | Clé |
| --- | --- | --- |
| `llm_factories` | Catalogue des providers (OpenAI, Bedrock, Gemini…) | `name` (PK) |
| `llm` | Catalogue global de tous les modèles disponibles | `fid` + `llm_name` (PK composite) |
| `tenant_llm` | Modèles instanciés pour un tenant, avec clé API | `tenant_id` + `llm_factory` + `llm_name` (index unique) |
| `tenant` | Configuration par défaut du tenant | `id` (UUID) |

### Valeurs de `model_type` et usages

Le champ `model_type` dans `conf/llm_factories.json` (et dans la table `llm`) détermine dans quels contextes un modèle peut être utilisé. Il est copié tel quel dans `tenant_llm` à l'instanciation.

| `model_type` | Champ défaut dans `tenant` | Usages |
| --- | --- | --- |
| `chat` | `llm_id` | Conversations (dialog), agents, génération de texte, résumés, Q&A |
| `embedding` | `embd_id` | Vectorisation des documents à l'indexation et des requêtes à la recherche |
| `image2text` | `img2txt_id` | Extraction de texte depuis des images (figures, captures d'écran dans les PDFs) |
| `speech2text` | `asr_id` | Transcription audio (ASR — Automatic Speech Recognition) |
| `rerank` | `rerank_id` | Reranking des chunks candidats après la recherche vectorielle |
| `tts` | `tts_id` | Synthèse vocale des réponses (Text-to-Speech) |

> **Note** : `reranker` est un alias de `rerank` présent dans certaines entrées du JSON ; les deux valeurs sont traitées de façon identique par le code.

Un modèle dont le `model_type` ne correspond pas au contexte d'usage ne sera jamais proposé dans le sélecteur UI correspondant, même s'il est présent dans `tenant_llm`. Par exemple, un modèle `chat` ne peut pas être sélectionné comme modèle d'embedding, et vice-versa.

Le champ `default_models` de `service_conf.yaml.template` utilise les clés `chat_model` et `embedding_model` pour définir le modèle par défaut de chaque type à la création du tenant :

```yaml
default_models:
  chat_model:         # → tenant.llm_id
    name: "..."
  embedding_model:    # → tenant.embd_id
    name: "..."
```

Les autres types (`speech2text`, `image2text`, `rerank`, `tts`) reçoivent une valeur par défaut codée en dur dans `api/db/init_data.py` si aucun modèle correspondant n'est trouvé dans la factory configurée.

### Conséquences opérationnelles

- `llm_factories` et `llm` sont peuplés **une seule fois** à l'init de la base. Ajouter un modèle dans `conf/llm_factories.json` **ne met pas à jour automatiquement** les tenants existants — seuls les nouveaux comptes créés après le redémarrage en bénéficient.
- Modifier `user_default_llm` dans `service_conf.yaml.template` n'affecte que les **nouveaux comptes** créés après le redémarrage.
- La validation à l'usage (erreur 102) interroge `tenant_llm` : si le triplet `(tenant_id, llm_name, llm_factory)` est absent, la requête échoue quel que soit l'état des tables `llm` et `llm_factories`.

## OpenAI

### `docker/service_conf.yaml.template`

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

### Variables d'environnement (`docker/.env`)

```env
OPENAI_API_KEY=sk-proj-...
```

### `conf/llm_factories.json`

Les modèles OpenAI sont déjà pré-configurés dans `llm_factories.json`. Aucune modification nécessaire.

---

## Bedrock

### `docker/service_conf.yaml.template`

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

> **Note** : le champ `api_key` est un JSON encodé en YAML single-quoted string.
> La valeur `auth_mode` doit être `"access_key_secret"` pour l'authentification par clé explicite.
> Les retours à la ligne dans la valeur YAML sont gérés correctement par le script de génération.

### Variables d'environnement (`docker/.env`)

```env
AWS_ACCESS_KEY_ID=AKIA...
AWS_SECRET_ACCESS_KEY=...
AWS_DEFAULT_REGION=eu-west-1
```

### `conf/llm_factories.json` — entrée Bedrock

Les modèles Bedrock doivent être déclarés explicitement (contrairement à OpenAI) :

```json
{
  "name": "Bedrock",
  "logo": "",
  "tags": "LLM,TEXT EMBEDDING",
  "status": "1",
  "rank": "860",
  "llm": [
    {
      "llm_name": "eu.amazon.nova-2-lite-v1:0",
      "tags": "LLM,CHAT,300k",
      "max_tokens": 300000,
      "model_type": "chat",
      "is_tools": true
    },
    {
      "llm_name": "eu.amazon.nova-pro-v1:0",
      "tags": "LLM,CHAT,300k",
      "max_tokens": 300000,
      "model_type": "chat",
      "is_tools": true
    },
    {
      "llm_name": "eu.anthropic.claude-opus-4-6-v1",
      "tags": "LLM,CHAT,200k",
      "max_tokens": 200000,
      "model_type": "chat",
      "is_tools": true
    },
    {
      "llm_name": "eu.anthropic.claude-sonnet-4-6",
      "tags": "LLM,CHAT,200k",
      "max_tokens": 200000,
      "model_type": "chat",
      "is_tools": true
    },
    {
      "llm_name": "mistral.mistral-large-2402-v1:0",
      "tags": "LLM,CHAT,32k",
      "max_tokens": 32000,
      "model_type": "chat",
      "is_tools": true
    },
    {
      "llm_name": "amazon.titan-embed-text-v2:0",
      "tags": "TEXT EMBEDDING,8k",
      "max_tokens": 8192,
      "model_type": "embedding",
      "is_tools": false
    }
  ]
}
```

---

## Gemini

### `docker/service_conf.yaml.template`

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

### Variables d'environnement (`docker/.env`)

```env
GEMINI_API_KEY=AIza...
```

La clé API est obtenue depuis [Google AI Studio](https://aistudio.google.com/app/apikey).

### `conf/llm_factories.json`

Les modèles Gemini sont déjà pré-configurés dans `llm_factories.json`. Aucune modification nécessaire.

Modèles disponibles :

| `llm_name` | Type | Contexte |
| --- | --- | --- |
| `gemini-3.1-pro-preview` | chat | 1 M tokens |
| `gemini-3-flash-preview` | chat | 1 M tokens |
| `gemini-3.1-flash-lite-preview` | chat | 1 M tokens |
| `gemini-embedding-001` | embedding | 2 048 tokens |

---

## Modes d'authentification Bedrock

| `auth_mode` | Description | Champs requis |
| --- | --- | --- |
| `access_key_secret` | Clé AWS explicite | `bedrock_ak`, `bedrock_sk`, `bedrock_region` |
| `iam_role` | Assume Role via STS | `aws_role_arn`, `bedrock_region` |
| autre | Credential chain AWS par défaut (instance profile, etc.) | `bedrock_region` |

---

## Dépannage

### `hint : 102 'llm_id' <modèle>@<factory> doesn't exist`

Ce message indique qu'un modèle référencé dans une configuration (base de connaissances, agent, dialogue ou pipeline de parsing) n'est pas enregistré dans l'instance RAGFlow.

Causes fréquentes :
- Le factory correspondant n'est pas configuré dans `service_conf.yaml.template` (clé API absente).
- Le modèle a été saisi manuellement avec un nom incorrect.
- Le modèle a été retiré de `conf/llm_factories.json` sans mise à jour des configurations qui y font référence.

→ Voir la [FAQ dédiée sur Confluence](https://eurelis.atlassian.net/wiki/spaces/AILAB/pages/1359839246) pour la conduite à tenir.

---

## Après modification

Un redémarrage du conteneur RAGFlow est nécessaire pour que les changements soient pris en compte :

```bash
cd docker
docker compose down
docker compose up -d
```

Les comptes utilisateurs créés **après** le redémarrage bénéficient automatiquement de la nouvelle configuration.
