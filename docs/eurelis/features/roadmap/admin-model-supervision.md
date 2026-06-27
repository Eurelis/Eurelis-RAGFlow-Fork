# Note d'implémentation : Supervision admin des modèles par tenant

> **Branche :** `eurelis/feature/admin-model-supervision` (depuis `eurelis/main`)
> **Statut global :** 🛠️ Backend en place — Phases 1 & 2 (lecture, comparaison, copie) implémentées et validées ; frontend à venir
> **Nature :** fonctionnalité **locale Eurelis** — jamais poussée upstream. Contrainte : **empreinte minimale sur le code upstream** (cf. section dédiée).

## TODO (vue d'ensemble)

> Suivi détaillé : section [Plan de suivi](#plan-de-suivi).

- [x] **Phase 0 — Préparation** : branche, analyse, stratégie, spec ✅
- [x] **Phase 1 — Backend lecture & comparaison** : `TenantModelMgr.list_tenant_models()` + `compare_tenants()` + routes GET (validé base locale + HTTP)
- [x] **Phase 2 — Backend copie** : `copy_models()` (Provider + Instance + défauts `Tenant`, overwrite idempotent) + route POST (validé : test_b/test_c rendus résolubles)
- [ ] **Phase 3 — Frontend service & types** : endpoints, service, types
- [ ] **Phase 4 — Frontend page** : `model-supervision.tsx` (comparatif + copie) + route + nav + i18n
- [ ] **Phase 5 — Finalisation** : tests e2e, en-têtes Eurelis, revue sécurité, PR

**Cible confirmée :** système `tenant_model_*` (legacy `tenant_llm` hors périmètre) · **Routing/Groups :** hors périmètre V1 (non câblé).

---

## Objectif

Ajouter, dans l'espace d'administration, une **supervision des modèles LLM configurés sur les tenants** des utilisateurs, permettant de :

1. **Visualiser** les configurations de modèles de n'importe quel tenant (cross-tenant).
2. **Comparer** les configurations de plusieurs tenants côte à côte.
3. **Copier** la configuration d'un tenant vers un autre.

Cette fonctionnalité est **admin-only** (superuser) et distincte du partage de modèles entre membres d'équipe analysé dans [`model-sharing-analysis.md`](./model-sharing-analysis.md), qui est orienté utilisateur final.

---

## Décisions gelées

| Décision                                              | Choix retenu                                |
|-------------------------------------------------------|---------------------------------------------|
| Périmètre V1                                          | **Comparer + copier** (complet)             |
| Conflit sur copie (modèle déjà présent chez la cible) | **Écraser (overwrite)**                     |
| Copie des clés API (secrets)                          | **Oui** — copie complète incluant `api_key` |

> Conséquence sécurité : la copie reste une opération **backend** (les `api_key` ne transitent pas en clair vers le frontend). L'affichage/comparaison masque les clés (`sk-…1234`).

### Alternative écartée : partage utilisateur → équipe

L'option « permettre à un utilisateur de partager ses modèles avec son équipe » (cf. [`model-sharing-analysis.md`](./model-sharing-analysis.md)) a été comparée puis **écartée pour la V1**.

| Critère                          | Supervision admin + copie (retenu) | Partage équipe (écarté V1)                       |
|----------------------------------|------------------------------------|--------------------------------------------------|
| Migration DB                     | aucune                             | requise (`permission`, `created_by`)             |
| Pipeline RAG / résolution modèle | **inchangé**                       | doit résoudre l'`api_key` via le tenant créateur |
| Processus impactés               | API server admin                   | API server **+ task executors** (chemin chaud)   |
| Risque de régression             | faible                             | moyen-élevé                                      |

**Raison du choix :** la copie produit de simples lignes `TenantLLM` normales sous le `tenant_id` cible → résolues par le code existant sans toucher au chemin d'exécution runtime. Le partage équipe reste une **piste V2** possible si le besoin de mutualisation durable (clé unique, pas de divergence) se confirme.

---

## Architecture analysée

### ⚠️ Deux systèmes coexistent — cibler le récent

L'historique upstream montre **deux générations** de configuration de modèles :

|                    | **Legacy `tenant_llm`**                                                         | **Système « model provider »** (cible)                                                                            |
|--------------------|---------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| Introduit          | origine                                                                         | PR #14595 (2026-05-29), suivi par #16028 / #16073                                                                 |
| Structure          | table plate                                                                     | hiérarchie `Provider → Instance → Model` + `Group` (routing)                                                      |
| Écrit par          | anciens endpoints `/v1/llm/*` (`llm_app.py`) — **non appelés par l'UI moderne** | endpoints RESTful `/api/v1/providers/*` & `/api/v1/models/*` — **utilisés par le frontend actuel**                |
| Résolution runtime | —                                                                               | `get_model_config_from_provider_instance()` ; les défauts du `Tenant` (`llm_id`…) sont résolus **via ce système** |
| Secrets            | `api_key` par ligne                                                             | `api_key` centralisée sur l'**instance**                                                                          |
| Migration          | source                                                                          | **backfillé** depuis `tenant_llm` (`tools/scripts/mysql_migration.py`, one-shot)                                  |

**Décision : la supervision cible le système `tenant_model_*`.** `tenant_llm` est **obsolète et hors périmètre** :
- ❌ **non lu** pour la résolution de modèle (c'est `tenant_model_*` via `get_model_config_from_provider_instance`) ni par `list_tenant_added_models` ;
- ❌ **non mis à jour** pour l'usage : `increase_usage`/`increase_usage_by_id` n'ont **aucun appelant** (code mort) → les `used_tokens` (1M+ sur Synerga) sont **historiques/figés**, pas une source de conso fiable ;
- ⚠️ encore **écrit** par les vieux endpoints `/v1/llm/*` (`llm_app.py`), non appelés par l'UI moderne ;
- ⚠️ encore **lu à un seul endroit résiduel** : `tenant_utils.ensure_tenant_model_id_for_params` (via `chat_api.py`) pour remplir les colonnes vestigiales `tenant_*_id` du chat — colonnes que la résolution n'utilise pas.

Il reste 136 lignes sur Synerga, mais c'est du **résidu pré-migration**, sans rôle fonctionnel.

> **Validé sur Synerga Sandbox** — voir la section [Validation base de données](#validation-base-de-données-synerga-sandbox) pour le détail des constats.

### Modèle de données (système cible)

Référence : `api/db/db_models.py` (`lignes 1403–1458`). **Aucune FK réelle** — liens logiques par `*_id`.

```
   ┌──────────────────────────────┐
   │   TenantModelProvider        │  le fournisseur, scopé tenant
   │   id (PK)                     │  UNIQUE(tenant_id, provider_name)
   │   tenant_id, provider_name    │
   └──────────────────────────────┘
            │ provider_id
            ▼
   ┌──────────────────────────────┐
   │   TenantModelInstance        │  🔑 porte l'api_key (1 compte/clé du provider)
   │   id (PK)                     │
   │   provider_id, instance_name  │
   │   api_key, status, extra(JSON)│
   └──────────────────────────────┘
            │ instance_id
            ▼
   ┌──────────────────────────────┐
   │   TenantModel                │  un modèle concret exposé par l'instance
   │   id (PK)                     │
   │   provider_id, instance_id    │
   │   model_name, model_type      │
   │   status, extra(JSON)         │
   └──────────────────────────────┘

   ┌──────────────────────────────┐        ┌───────────────────────────────────────┐
   │   TenantModelGroup           │ 1    N │   TenantModelGroupMapping             │
   │   id (PK)                     │────────│   PK(group_id, provider_id,           │
   │   group_type, model_name      │ group  │      instance_id, model_id)           │
   │   strategy (= "weighted")     │  _id   │   weight (routing), status            │
   └──────────────────────────────┘        └───────────────────────────────────────┘
```

> Rappel clé : `Tenant.id == user_id` du propriétaire. Les défauts (`Tenant.llm_id` = `model@instance@provider`) se résolvent dans cette hiérarchie via `split_model_name()`.

#### `TenantModelProvider` (`ligne 1403`)

Le fournisseur déclaré pour un tenant. **Unique `(tenant_id, provider_name)`**.

| Champ           | Type            | Rôle                       |
|-----------------|-----------------|----------------------------|
| `id`            | Char(32) **PK** | UUID                       |
| `provider_name` | Char(128)       | OpenAI, Anthropic, MinerU… |
| `tenant_id`     | Char(32) idx    | Tenant propriétaire        |

#### `TenantModelInstance` (`ligne 1414`) — 🔑 porte les secrets

Une **instance configurée** d'un provider (permet plusieurs comptes/clés pour un même provider).

| Champ           | Type            | Rôle                                                     |
|-----------------|-----------------|----------------------------------------------------------|
| `id`            | Char(32) **PK** | UUID                                                     |
| `instance_name` | Char(128)       | ex. `default`                                            |
| `provider_id`   | Char(32)        | → `TenantModelProvider.id`                               |
| **`api_key`**   | Char(512)       | 🔑 **Secret** (ou payload JSON pour factories complexes) |
| `status`        | Char(32)        | `active` / `inactive`                                    |
| `extra`         | Char(512) JSON  | `base_url`, etc.                                         |

#### `TenantModel` (`ligne 1426`)

Un **modèle concret** rattaché à une instance.

| Champ                         | Type            | Rôle                                                                     |
|-------------------------------|-----------------|--------------------------------------------------------------------------|
| `id`                          | Char(32) **PK** | UUID                                                                     |
| `model_name`                  | Char(128)       | Nom du modèle                                                            |
| `provider_id` / `instance_id` | Char(32)        | rattachement                                                             |
| `model_type`                  | Char(32)        | `chat`, `embedding`, `image2text`, `rerank`, `tts`, `speech2text`, `ocr` |
| `status`                      | Char(32)        | `active` / `inactive` / `unsupported`                                    |
| `extra`                       | Char(1024) JSON | `is_tools`, `max_tokens`…                                                |

> ⚠️ **Vide sur Synerga (0 ligne).** Les modèles **ne sont pas matérialisés par tenant** : `list_tenant_added_models()` énumère les modèles depuis le **catalogue global `FACTORY_LLM_INFOS`** (filtré aux factories des providers du tenant). `tenant_model` ne sert qu'à *surcharger* (statut/extra) un modèle du catalogue, s'il existe.
> → **Conséquence pour la copie : pas de couche `Model` à copier.** Copier `Provider` + `Instance` (+ défauts `Tenant`) suffit ; ne copier des `tenant_model` que s'il en existe chez la source.

#### `TenantModelGroup` (`ligne 1439`) & `TenantModelGroupMapping` (`ligne 1448`)

Couche de **routing/load-balancing** : un groupe agrège plusieurs modèles derrière un point logique avec une `strategy` (`weighted`) ; le mapping liste les membres pondérés (`weight`). PK composite `(group_id, provider_id, instance_id, model_id)`.

> **Hors périmètre V1 (confirmé).** Ces deux tables sont **vides** (instance locale **et** Synerga) — la couche routing n'est pas exploitée. La copie ne traite donc que `Provider` + `Instance` (+ défauts). À reconsidérer seulement si des groupes apparaissent un jour.
>
> **Vérification code (le routing n'est pas câblé) :**
> 1. `TenantModelGroupService` / `TenantModelGroupMappingService` ne sont **importés/appelés nulle part** hors de leur propre définition (grep vide sur `api/`, `rag/`, `agent/`, `admin/`) → CRUD orphelins.
> 2. La résolution `get_model_config_from_provider_instance()` construit le `model_config` uniquement via `Provider → Instance → Model` (ou le fallback catalogue `FACTORY_LLM_INFOS`) — aucune lecture de `group_id`, `strategy` ni `weight`.
>
> → Le système résout et utilise les modèles **intégralement sans routing**. La couche `tenant_model_group*` est une ébauche (portage de la suite « model_provider ») prévue pour un futur load-balancing, non active aujourd'hui.

#### `Tenant` — modèles **par défaut** (`ligne 750`, legacy mais toujours utilisé)

`id` = `user_id`. Un défaut par type, stocké au format `model@instance@provider` : `llm_id`, `embd_id`, `asr_id`, `img2txt_id`, `rerank_id`, `tts_id`, `ocr_id`. Résolus via le système cible.

#### `UserTenant` — liaison user ↔ tenant (`ligne 775`)

Appartenance aux équipes. Table interrogée par l'admin (`TenantMgr`) pour le cross-tenant.

#### Implications pour la feature

1. **Cibler `tenant_model_*`** (provider/instance) : c'est ce que l'UI peuple et ce que la résolution runtime consomme.
2. **La copie traite `Provider` + `Instance` (+ `api_key`) + défauts du `Tenant`** — la couche `Model` est vide en pratique (modèles issus du catalogue), à copier seulement si présente.
3. **Secrets centralisés** sur `TenantModelInstance.api_key` → plus propre à copier (1 clé par instance).
4. **Pas de FK** : requêtes cross-tenant = simples filtres `WHERE tenant_id = …` (au niveau provider).

### Validation base de données (Synerga Sandbox)

Vérifié le **2026-06-27** sur la base `rag_flow` (`docker-mysql-1`, serveur `frstr-slc-ragflow01`, RAGFlow `v0.26.1-eurelis.3-exp.4`).

**Volumétrie des tables (global) :**

| Table | Lignes | Note |
|---|---:|---|
| `tenant_llm` | 136 | **obsolète** : résidu pré-migration, `used_tokens` figés (tracking mort), non lu pour la résolution |
| `tenant_model_provider` | 23 | système cible |
| `tenant_model_instance` | 23 | porte les `api_key` |
| `tenant_model` | **0** | modèles servis par le catalogue `FACTORY_LLM_INFOS` |
| `tenant_model_group` / `…_mapping` | **0** | routing non utilisé |

**Cas `v.lambert@eurelis.com`** (admin, `tenant_id 9d066918…`) — *gère ses connexions* :
- 2 providers / 2 instances : **Bedrock** (`api_key` = payload JSON, 181 c) et **Gemini** (clé simple, 39 c), instance `default`, `active`.
- 10 lignes `tenant_llm` (Bedrock + Gemini, chat & embedding) avec `used_tokens` réels.
- Défaut chat : `eu.amazon.nova-2-lite-v1:0@default@Bedrock` (format 3 parties).
- Chats partagés `permission=team` actifs : `SynerBot`, `UC1 - Agent Assistant documentaire interne`, `DEMO - Facturation Electronique`.

**Cas `test_user_a@eurelis.com`** (`tenant_id 0f5ceace…`) — *consomme les chats partagés* :
- **0** `tenant_llm`, **0** provider, **0** instance, **0** dialog propre.
- Défauts `Tenant` pré-remplis (`…@Bedrock`, format 2 parties) mais **non résolvables** chez lui (pas de provider Bedrock).
- → Sa config modèle effective est celle de **v.lambert** (propriétaire des chats `team`). Confirme que la config est portée par le tenant propriétaire et qu'un pur consommateur n'a aucune config locale.

**Hypothèses confirmées :** système cible `tenant_model_*`, `api_key` sur l'instance, défauts `model@[instance@]provider`, groupes vides.
**Hypothèses corrigées :** `tenant_llm` **n'est pas vide mais obsolète** (résidu pré-migration ; non lu pour la résolution, `increase_usage` sans appelant → `used_tokens` figés) · `tenant_model` **est vide** → pas de couche `Model` à copier.

#### Contre-validation sur fresh install local

Pour lever le doute « Synerga = résidu de migration », vérifié sur un **install neuf** (code courant `usage-stats`, base `rag_flow` locale) en isolant chaque action :

| Étape | Constat |
|---|---|
| **Init (état zéro)** | 1 seul compte `admin@ragflow.io` ; **toutes** les tables modèles à **0** (y compris `tenant_llm`). Défaut `embd_id = bge-m3@xxxx` issu de `user_default_llm`. |
| **Config provider OpenAI + clé (UI moderne)** | écrit **uniquement** `tenant_model_provider` (1) + `tenant_model_instance` (1, `api_key` + `extra.base_url`). **`tenant_llm` reste à 0**, `tenant_model` à 0. |
| **2ᵉ user créé sans config** | 0 provider / 0 `tenant_llm` / colonnes `tenant_*_id` NULL ; défaut `embd_id = bge-m3@xxxx` (2 parties) **pendant** → reproduit le cas `test_user_a`. |
| **Chat créé + 1 message** | `llm_id` admin = `gpt-5.5@Admin@OpenAI` (3 parties) ; après usage : `tenant_llm` toujours **0 / 0 token**, `tenant_model` 0, **aucun compteur d'usage** sur l'instance. |
| **Chat `team` d'admin utilisé par v.lambert (sans config)** | ✅ fonctionne. Le `dialog` est `permission=team`, `tenant_id=admin` ; v.lambert est `role=normal` dans l'équipe admin et garde **0 config**. La résolution se fait contre le **tenant propriétaire** (`dialog_service.py:360` → `get_model_config_from_provider_instance(dialog.tenant_id, …)`), pas l'utilisateur courant. |

**Conclusions renforcées :**
1. **`tenant_llm` n'est jamais écrit par le code moderne** (0 sur install neuf, même après config) → obsolète confirmé, pas un simple résidu Synerga.
2. **`tenant_model` jamais matérialisé** (vide après config *et* usage) → modèles servis par le catalogue.
3. **Format des défauts** : `model@factory` au pré-remplissage `user_default_llm`, puis `model@instance@provider` une fois sélectionné via le système moderne.
4. **Aucun tracking d'usage** dans les tables de config modèle (pas de `used_tokens` sur l'instance) → la conso de tokens **n'est pas récupérable** depuis ce système (relève de `usage-stats`).
5. Le **nom d'instance est saisi par l'utilisateur** à l'ajout du provider (`default`, `Admin`, … variables) → ne pas le supposer fixe dans la copie.

#### Rôle de `user_default_llm` (`conf/service_conf.yaml`)

Testé en isolant la variable (config `xxxx`/bge-m3 → `OpenAI`+modèles réels → création d'users → tentative de chat).

`user_default_llm` est chargé au démarrage (`common/settings.py`) en `LLM_FACTORY`, `API_KEY`, `CHAT_MDL`/`EMBEDDING_MDL` (format `model@factory`), `ALLOWED_LLM_FACTORIES`, `PARSERS`. À la création d'un tenant, les 3 chemins posent `Tenant.llm_id/embd_id/…` depuis ces valeurs.

| Effet | Statut |
|---|---|
| Défauts modèle par user (`Tenant.*_id`) | ❌ **vestigial** : pose des **pointeurs pendants** ; **aucun provider/instance créé** (vérifié : `test_b`/`test_c` → 0 provider, 0 instance, 0 `tenant_llm`). Un nouvel user **ne peut pas créer de chat** (UI : « ajouter d'abord un embedding + un LLM »). Seul un **chat partagé** marche (résolu contre le propriétaire). |
| `parser_ids` par défaut (`PARSERS`) | ✅ vivant (3 chemins de création) |
| Whitelist factories (`ALLOWED_LLM_FACTORIES`) | ✅ vivant (`api_utils.py:709`) |
| Embedding **builtin TEI** (`EMBEDDING_CFG`) | ✅ vivant en profil `tei-` (`tenant_model_service.py:195`) |
| Seeding `tenant_llm` via `get_init_tenant_llm` | ⚠️ boot superuser uniquement → écrit une table **obsolète** |

**Conséquences pour la feature :**
- La supervision doit afficher un défaut `model@factory` (2 parties) **comme potentiellement pendant** tant qu'aucun provider correspondant n'existe chez le tenant.
- **Piste produit** liée à la copie de config : pour rendre un user autonome, il ne suffit pas de copier le défaut `Tenant` — il faut **créer le `Provider` + `Instance`**. C'est précisément ce que `copy_models()` apporte (le manque que `user_default_llm` ne comble pas).

**Grille de décision — faut-il utiliser `user_default_llm` ?**

| Contexte | Verdict |
|---|---|
| Bootstrap modèle via **provider externe** (OpenAI, Bedrock, Gemini… — cas Synerga) | ❌ **Inutile** : pointeur pendant, l'user doit configurer un provider de toute façon ; crée une fausse impression de config. |
| **Embedding builtin / TEI** (profil `tei-`) | ✅ **Intérêt réel** : configuré sans factory pour matcher `TEI_MODEL`, le défaut embedding est résolu par le bypass dédié → fonctionnel sans config manuelle. |
| `parsers` (parser_ids par défaut) | ✅ Utile, indépendant des modèles. |
| `allowed_factories` (whitelist providers) | ✅ Utile, indépendant des modèles. |

→ **Sur Synerga (Bedrock externe)** : la partie `default_models` est inutile ; ne conserver `user_default_llm` que pour `parsers`/`allowed_factories` (ou la vider sans rien casser côté modèles). Le vrai besoin « user autonome sans saisie » relève de `copy_models()`, pas de `user_default_llm`.

> **Gotcha opérationnel** : `user_default_llm` (et toute `service_conf.yaml`) est lu **au démarrage** par **deux process distincts** — l'API (`9380`) et l'admin (`9381`), chacun avec son propre snapshot `settings`. Un changement impose de **redémarrer les deux** (sinon un user créé via l'admin reflète l'ancienne config).

### Services réutilisables (système cible)

- `api/apps/services/models_api_service.py` — `list_tenant_added_models(tenant_id, model_type_filter=None)`, `list_tenant_default_models(tenant_id)`, `set_tenant_default_models(...)`.
- `api/apps/services/provider_api_service.py` — `list_providers`, `add_provider`, `create_provider_instance`, `add_model_to_instance`, `list_instance_models`, `update_model_status`…
- `api/db/joint_services/tenant_model_service.py` — `split_model_name()`, `get_model_config_from_provider_instance()`, `get_tenant_default_model_by_type()`.
- Services CRUD bas niveau : `TenantModelProviderService`, `TenantModelInstanceService`, `TenantModelService`, `TenantModelGroup(Mapping)Service`.

### Espace admin (pattern à dupliquer)

- Backend séparé (port 9381) : `admin/server/{routes,services}.py`. Pattern cross-tenant déjà en place avec la classe **`TenantMgr`** + routes `/api/v1/admin/tenants...`, protégées par `@login_required @check_admin_auth`.
- Frontend : `web/src/services/admin-service.ts` → `web/src/utils/api.ts` → `web/src/pages/admin/*.tsx` → `web/src/routes.tsx` → `layouts/navigation-layout.tsx`. i18n : `web/src/locales/eurelis/{en,fr}.ts`.

---

## Contrainte : empreinte minimale sur l'upstream

Fonctionnalité **locale Eurelis**, jamais mergée upstream. Tout fichier upstream modifié devient un point de friction à chaque rebase de synchronisation. **Principe : tout le code dans des fichiers Eurelis dédiés ; les fichiers upstream ne reçoivent que le minimum d'insertions, clairement délimitées.**

**Stratégie backend — blueprint Eurelis isolé.** L'admin enregistre un blueprint unique via `app.register_blueprint(admin_bp)` (`admin/server/admin_server.py:53`). On crée un **second blueprint Eurelis** dans un nouveau fichier, avec le même `url_prefix="/api/v1/admin"`, et on l'enregistre par **une seule ligne** ajoutée à `admin_server.py`.

| Type | Fichier | Action |
|------|---------|--------|
| 🆕 Nouveau (Eurelis) | `admin/server/admin_model_supervision.py` | Blueprint + handlers + classe `TenantModelMgr` (service) |
| ✏️ Upstream (1 ligne) | `admin/server/admin_server.py` | `import` + `register_blueprint(...)` du blueprint Eurelis |
| ♻️ Réutilisé (0 edit) | `api/apps/services/models_api_service.py`, `provider_api_service.py` | appelés tels quels |

> Aucune modification de `admin/server/routes.py` ni `services.py`.

**Stratégie frontend.** Le gros (page) est un fichier neuf ; les points de contact upstream sont additifs et minimes (1 route, 1 entrée de menu, qq lignes de service). i18n dans `locales/eurelis/` (déjà Eurelis).

| Type | Fichier | Action |
|------|---------|--------|
| 🆕 Nouveau (Eurelis) | `web/src/pages/admin/model-supervision.tsx` | la page |
| ✏️ Upstream (additif) | `web/src/utils/api.ts` | + endpoints (bloc délimité) |
| ✏️ Upstream (additif) | `web/src/services/admin-service.ts`, `admin.service.d.ts` | + fonctions/types |
| ✏️ Upstream (1 route) | `web/src/routes.tsx` | + `AdminModelSupervision` |
| ✏️ Upstream (1 item) | `navigation-layout.tsx` | + entrée de menu |
| ♻️ Eurelis | `web/src/locales/eurelis/{en,fr}.ts` | + libellés |

**Règles transverses :** en-têtes de commentaires Eurelis sur les nouveaux fichiers ; chaque insertion dans un fichier upstream encadrée d'un commentaire repère (ex. `// --- Eurelis: model supervision ---`) pour faciliter la relecture et les rebases.

---

## Plan d'implémentation

### Backend

**`admin/server/admin_model_supervision.py`** (nouveau) — classe `TenantModelMgr` + handlers du blueprint Eurelis, opérant sur le système `tenant_model_*` :

| Méthode                             | Rôle                                                                                                                                                                                                                                                                                                    |
|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `list_tenant_models(tenant_id)`     | Réutilise `models_api_service.list_tenant_added_models()` + `list_tenant_default_models()`. `api_key` (sur l'instance) **masquée** dans la réponse.                                                                                                                                                     |
| `compare_tenants(tenant_ids)`       | Matrice : pour chaque `(provider, instance, model_name, model_type)`, statut par tenant + `base_url`/`max_tokens` + flag « défaut ».                                                                                                                                                                    |
| `copy_models(source_id, target_id)` | Copie **Provider + Instance (api_key)** via `provider_api_service` (`add_provider`, `create_provider_instance`) en **overwrite** + défauts du `Tenant` source. `tenant_model` : copié **seulement s'il en existe** chez la source (vide sur Synerga → no-op). Groups : hors périmètre V1. |

**Blueprint Eurelis** (même fichier, `url_prefix="/api/v1/admin"`, routes `@login_required @check_admin_auth`) — enregistré par 1 ligne dans `admin/server/admin_server.py` :

- `GET  /tenants/<id>/models`
- `GET  /tenants/models/compare?tenant_ids=a,b,c`
- `POST /tenants/<dst>/models/copy` — body `{ "source_tenant_id": "..." }`

### Frontend

- `web/src/utils/api.ts` : endpoints `adminListTenantModels`, `adminCompareTenantModels`, `adminCopyTenantModels`.
- `web/src/services/admin-service.ts` + `admin.service.d.ts` : fonctions + types (`TenantModelConfig`, `ModelComparisonRow`).
- `web/src/pages/admin/model-supervision.tsx` : sélection multi-tenants → tableau comparatif (colonnes = tenants, lignes = modèles, code couleur présence/écart) → bouton « Copier vers… » + dialog de confirmation overwrite.
- `web/src/routes.tsx` : route `AdminModelSupervision` (`/admin/model-supervision`).
- `layouts/navigation-layout.tsx` : entrée de menu.
- `locales/eurelis/{en,fr}.ts` : libellés.

---

## Points de vigilance

- **Cibler le bon système** : `tenant_model_*` (pas `tenant_llm`, legacy/hors périmètre).
- **Secrets** : `api_key` (sur `TenantModelInstance`) jamais renvoyée en clair au frontend (comparaison sur présence/empreinte). La copie reste backend.
- **Factories complexes** : `api_key` JSON (Bedrock, VolcEngine, Azure-OpenAI, OpenRouter…) copiée telle quelle, sans réinterprétation.
- **Copie = Provider + Instance (+ défauts), pas une ligne plate** : créer le `Provider` cible s'il manque, puis l'`Instance` (avec `api_key`). La couche `Model` (`tenant_model`) est **vide sur Synerga** (modèles issus du catalogue) → ne la copier que si elle existe. Réutiliser `provider_api_service` plutôt que des inserts bruts.
- **Consommateur de chats partagés** : un utilisateur qui n'utilise que des chats `team` d'un autre tenant n'a **aucune** config modèle propre (cf. `test_user_a`) — la résolution se fait contre le tenant **propriétaire** du chat. La supervision doit donc afficher « 0 config » sans la traiter comme une anomalie.
- **Unicité provider** `(tenant_id, provider_name)` + instance par `(provider_id, instance_name)` : overwrite = mettre à jour l'existant.
- **Nom d'instance saisi par l'utilisateur** (`default`, `Admin`, …) : ne pas le supposer fixe ; le copier tel quel et matcher sur `(provider_name, instance_name)`.
- **Défauts du `Tenant`** : copier un défaut au format `model@instance@provider` ; un défaut `model@factory` (2 parties, pré-rempli par `user_default_llm`) peut être **pendant** chez la source — ne le propager que si la chaîne existe chez la cible.
- **Pas de conso/usage** : aucun `used_tokens` exploitable dans le système de modèles → la supervision n'affiche pas de consommation (relève de `usage-stats`).
- **Groups de routing** : hors périmètre V1 (tables `tenant_model_group*` vides en local et sur Synerga).

---

## Plan de suivi

### Phase 0 — Préparation
- [x] Créer la feature branch `eurelis/feature/admin-model-supervision`
- [x] Analyser la gestion des configs de modèles par tenant
- [x] Définir la stratégie + geler les décisions
- [x] Rédiger la note d'implémentation

### Phase 1 — Backend : lecture & comparaison ✅
- [x] Créer `admin/server/admin_model_supervision.py` (blueprint Eurelis + `TenantModelMgr`)
- [x] Enregistrer le blueprint (`admin_server.py` : import + `register_blueprint`, calqué sur `eurelis_stats_bp`)
- [x] `TenantModelMgr.list_tenant_models()` — instances (api_key **masquée** `sk-p…rOAA`), `added_models`, `default_models` (résolus) **et `raw_defaults`** (bruts du `Tenant` + flag `resolvable` → détecte les défauts **pendants**)
- [x] `TenantModelMgr.compare_tenants()` — matrices `instances` / `models` / `defaults` par tenant
- [x] Routes `GET /tenants/<id>/models` et `GET /tenants/models/compare?tenant_ids=a,b,c`
- [x] Signatures vérifiées (`list_tenant_added_models` ne renvoie **pas** d'`api_key` ; instances via `TenantModelProviderService`/`TenantModelInstanceService`)
- [x] Validé sur base locale : admin (OpenAI/Admin, clé masquée) vs test_c (0 config, défaut `gpt-4o-mini@OpenAI` **non résoluble**)
- [x] Test HTTP réel (serveur admin 9381) : `GET …/models` → 200 (clé masquée), `GET …/models/compare` → 200 (test_c `resolvable:false`), sans token → 401

### Phase 2 — Backend : copie
- [x] `TenantModelMgr.copy_models()` — Provider + Instance (api_key) en **overwrite** via services bas niveau (synchrone, pas de re-validation) ; `tenant_model` seulement si présent
- [x] Copie des défauts du `Tenant` (chaîne `model@instance@provider` copiée — résoluble car provider/instance créés)
- [x] Groups de routing : **hors périmètre V1** (tables vides en local + Synerga)
- [x] Route `POST /tenants/<dst>/models/copy` (body `{source_tenant_id}`)
- [x] Validé : copie admin → test_b/test_c (défauts pendants → `resolvable:true`) ; **idempotent** (2e/3e passage = overwrite, aucun doublon) ; correctif `insert()` (retourne un int, pas l'objet) → re-fetch provider

### Phase 3 — Frontend : service & types
- [ ] Endpoints dans `utils/api.ts`
- [ ] Fonctions dans `admin-service.ts` + types `admin.service.d.ts`

### Phase 4 — Frontend : page de supervision
- [ ] Page `model-supervision.tsx` (sélection multi-tenants + tableau comparatif)
- [ ] Action « Copier vers… » + dialog de confirmation overwrite
- [ ] Route `AdminModelSupervision` + entrée de menu
- [ ] Libellés i18n `en`/`fr`

### Phase 5 — Finalisation
- [ ] Tests de bout en bout (comparaison + copie réelle entre 2 tenants)
- [ ] En-têtes de commentaires Eurelis sur les nouveaux fichiers
- [ ] Revue de sécurité (aucune fuite d'`api_key` vers le front)
- [ ] Mise à jour de la doc / PR

---

## Fichiers clés de référence

| Rôle                                                  | Fichier                                                                                                      |
|-------------------------------------------------------|--------------------------------------------------------------------------------------------------------------|
| Modèles DB cible (`TenantModel*`, `lignes 1403–1458`) | `api/db/db_models.py`                                                                                        |
| Service haut niveau modèles (réutilisable)            | `api/apps/services/models_api_service.py`                                                                    |
| Service haut niveau providers (réutilisable)          | `api/apps/services/provider_api_service.py`                                                                  |
| Résolution / helpers (`split_model_name`…)            | `api/db/joint_services/tenant_model_service.py`                                                              |
| Services CRUD bas niveau                              | `api/db/services/tenant_model_{provider,instance,group,group_mapping}_service.py`, `tenant_model_service.py` |
| Migration legacy → nouveau (référence)                | `tools/scripts/mysql_migration.py`                                                                           |
| Pattern cross-tenant admin (référence, **non modifié**) | `admin/server/services.py` (`TenantMgr`), `admin/server/routes.py`                                         |
| Code backend Eurelis (**nouveau**)                    | `admin/server/admin_model_supervision.py`                                                                  |
| Enregistrement blueprint (**1 ligne upstream**)       | `admin/server/admin_server.py` (~ligne 53)                                                                   |
| Service frontend admin                                | `web/src/services/admin-service.ts`                                                                          |
| Endpoints frontend                                    | `web/src/utils/api.ts`                                                                                       |
| Pages admin existantes (référence UI)                 | `web/src/pages/admin/users.tsx`, `user-team.tsx`                                                             |
| Routing / navigation                                  | `web/src/routes.tsx`, `web/src/pages/admin/layouts/navigation-layout.tsx`                                    |
| i18n Eurelis                                          | `web/src/locales/eurelis/{en,fr}.ts`                                                                         |
| Legacy hors périmètre                                 | `api/db/db_models.py` (`TenantLLM`), `api/apps/llm_app.py`                                                   |
