# Note d'implémentation : Supervision admin des modèles par tenant

> **Branche :** `eurelis/feature/admin-model-supervision` (depuis `eurelis/main`)
> **Statut global :** 📋 Spécifié — implémentation non démarrée
> **Nature :** fonctionnalité **locale Eurelis** — jamais poussée upstream. Contrainte : **empreinte minimale sur le code upstream** (cf. section dédiée).

## TODO (vue d'ensemble)

> Suivi détaillé : section [Plan de suivi](#plan-de-suivi).

- [x] **Phase 0 — Préparation** : branche, analyse, stratégie, spec ✅
- [ ] **Phase 1 — Backend lecture & comparaison** : `TenantModelMgr.list_tenant_models()` + `compare_tenants()` + routes GET
- [ ] **Phase 2 — Backend copie** : `copy_models()` (chaîne Provider→Instance→Model + défauts `Tenant`) + route POST
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

**Décision : la supervision cible le système `tenant_model_*`.** `tenant_llm` est **legacy et hors périmètre** (peut être vide/périmé sur un déploiement récent ; conservé pour rétrocompat SDK).

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

#### `TenantModelGroup` (`ligne 1439`) & `TenantModelGroupMapping` (`ligne 1448`)

Couche de **routing/load-balancing** : un groupe agrège plusieurs modèles derrière un point logique avec une `strategy` (`weighted`) ; le mapping liste les membres pondérés (`weight`). PK composite `(group_id, provider_id, instance_id, model_id)`.

> **Hors périmètre V1 (confirmé).** Ces deux tables sont **vides** sur l'instance locale — la couche routing n'est pas exploitée sur nos déploiements. La copie ne traite donc **que** la chaîne `Provider → Instance → Model`. À reconsidérer seulement si des groupes apparaissent un jour.
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

1. **Cibler `tenant_model_*`** : c'est ce que l'UI peuple et ce que la résolution runtime consomme.
2. **La copie traite une chaîne**, pas une ligne : `Provider` → `Instance` (+ `api_key`) → `Model`(s), + défauts du `Tenant`.
3. **Secrets centralisés** sur `TenantModelInstance.api_key` → plus propre à copier (1 clé par instance).
4. **Pas de FK** : requêtes cross-tenant = simples filtres `WHERE tenant_id = …` (au niveau provider).

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
| 🆕 Nouveau (Eurelis) | `admin/server/eurelis_model_supervision.py` | Blueprint + handlers + classe `TenantModelMgr` (service) |
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

**`admin/server/eurelis_model_supervision.py`** (nouveau) — classe `TenantModelMgr` + handlers du blueprint Eurelis, opérant sur le système `tenant_model_*` :

| Méthode                             | Rôle                                                                                                                                                                                                                                                                                                    |
|-------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `list_tenant_models(tenant_id)`     | Réutilise `models_api_service.list_tenant_added_models()` + `list_tenant_default_models()`. `api_key` (sur l'instance) **masquée** dans la réponse.                                                                                                                                                     |
| `compare_tenants(tenant_ids)`       | Matrice : pour chaque `(provider, instance, model_name, model_type)`, statut par tenant + `base_url`/`max_tokens` + flag « défaut ».                                                                                                                                                                    |
| `copy_models(source_id, target_id)` | Copie la chaîne **Provider → Instance (api_key) → Model** via les services `provider_api_service` (`add_provider`, `create_provider_instance`, `add_model_to_instance`) en **overwrite**. Copie aussi les défauts du `Tenant` source (si le modèle existe chez la cible). Groups : hors périmètre V1. |

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
- **Copie = chaîne, pas une ligne** : créer le `Provider` cible s'il manque, puis l'`Instance` (avec `api_key`), puis les `Model`(s). Réutiliser `provider_api_service` plutôt que des inserts bruts (validation cohérente).
- **Unicité provider** `(tenant_id, provider_name)` + instance par `(provider_id, instance_name)` : overwrite = mettre à jour l'existant.
- **Défauts du `Tenant`** : ne copier un défaut (`model@instance@provider`) que si la chaîne correspondante existe chez la cible après copie.
- **Groups de routing** : hors périmètre V1 (tables `tenant_model_group*` vides sur l'instance locale).

---

## Plan de suivi

### Phase 0 — Préparation
- [x] Créer la feature branch `eurelis/feature/admin-model-supervision`
- [x] Analyser la gestion des configs de modèles par tenant
- [x] Définir la stratégie + geler les décisions
- [x] Rédiger la note d'implémentation

### Phase 1 — Backend : lecture & comparaison
- [ ] Créer `admin/server/eurelis_model_supervision.py` (blueprint Eurelis + `TenantModelMgr`)
- [ ] Enregistrer le blueprint (1 ligne dans `admin_server.py`)
- [ ] `TenantModelMgr.list_tenant_models()` (réutilise `list_tenant_added_models`/`list_tenant_default_models`) + masquage `api_key`
- [ ] `TenantModelMgr.compare_tenants()` (matrice provider/instance/model)
- [ ] Routes `GET /tenants/<id>/models` et `GET /tenants/models/compare`
- [ ] Vérifier signatures réelles (`models_api_service`, `success_response`/`error_response`)
- [ ] Test manuel via `curl` (auth superuser)

### Phase 2 — Backend : copie
- [ ] `TenantModelMgr.copy_models()` — chaîne Provider→Instance→Model en overwrite (via `provider_api_service`)
- [ ] Copie des défauts du `Tenant` (si chaîne présente chez la cible)
- [x] Groups de routing : **hors périmètre V1** (tables vides sur l'instance locale)
- [ ] Route `POST /tenants/<dst>/models/copy`
- [ ] Test manuel copie + vérification factories JSON / instances multiples

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
| Code backend Eurelis (**nouveau**)                    | `admin/server/eurelis_model_supervision.py`                                                                  |
| Enregistrement blueprint (**1 ligne upstream**)       | `admin/server/admin_server.py` (~ligne 53)                                                                   |
| Service frontend admin                                | `web/src/services/admin-service.ts`                                                                          |
| Endpoints frontend                                    | `web/src/utils/api.ts`                                                                                       |
| Pages admin existantes (référence UI)                 | `web/src/pages/admin/users.tsx`, `user-team.tsx`                                                             |
| Routing / navigation                                  | `web/src/routes.tsx`, `web/src/pages/admin/layouts/navigation-layout.tsx`                                    |
| i18n Eurelis                                          | `web/src/locales/eurelis/{en,fr}.ts`                                                                         |
| Legacy hors périmètre                                 | `api/db/db_models.py` (`TenantLLM`), `api/apps/llm_app.py`                                                   |
