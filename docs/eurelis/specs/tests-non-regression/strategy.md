---
title: "Stratégie — Tests de non-régression Eurelis"
type: spec
status: draft
reviewed: 2026-07-04
---

# Stratégie — Tests de non-régression Eurelis

Suite de tests d'intégration **sans bouchons** validant une stack RAGFlow complète, destinée à
protéger trois périmètres :

1. **Le contrat des endpoints RAGFlow consommés par le frontend Shield** — stabilité de la structure
   des flux JSON (dont le streaming SSE des complétions).
2. **Les correctifs Eurelis** appliqués à du code upstream.
3. **Les évolutions spécifiques Eurelis** (supervision modèles, stats de consommation, équipes, PII
   masking, sitemap connector, provisioning OIDC).

Objectif transverse : tests **faciles à lancer et à rejouer** (une commande unique, reproductibles).

---

## Décision — Localisation de la suite : le fork RAGFlow (pas le repo Shield)

La suite de non-régression est implémentée **dans le fork RAGFlow Eurelis**, et non dans le repo Shield.

### Les deux contrats à ne pas confondre
Le Shield **n'appelle pas RAGFlow directement** : son backend proxyfie les appels. Il existe donc deux
contrats distincts :

| Contrat | Parties | Repo propriétaire |
|---|---|---|
| **C1** | Shield frontend ↔ Shield backend | Repo **Shield** |
| **C2** | Shield backend ↔ RAGFlow (endpoints réels, SDK + token RAGFlow) | Fork **RAGFlow** |

Cette suite cible **C2** ainsi que les correctifs et évolutions Eurelis internes à RAGFlow. Le besoin
exprimé (stabilité des endpoints RAGFlow, correctifs, évolutions) porte sur C2, pas sur C1.

### Justification
1. **Deux des trois périmètres n'existent que dans le fork.** Correctifs et évolutions Eurelis (stats,
   supervision modèles, PII, équipes, sitemap) sont du code RAGFlow ; le Shield n'en consomme qu'une
   fraction (`usage-stats/session`).
2. **Le gate doit se déclencher au rebase/release du fork** — c'est là que naissent les régressions (sync
   upstream, publication de l'image). Une suite côté Shield ne tournerait pas à ce moment-là.
3. **L'objet sous test est la stack RAGFlow complète** (compose + task-executor + Ollama), déjà hébergée
   dans `docker/` du fork.
4. **L'infra de test existe déjà côté fork** (`test/testcases/` : auth register/login/token, SDK, fixtures).
5. Tester C2 depuis le repo Shield imposerait soit de bypasser le backend Shield (donc sans intérêt d'y
   être), soit de tester à travers lui — ce qui **conflaterait** C1 et C2 et empêcherait d'attribuer une
   régression (bug Shield vs bug RAGFlow).

### Conséquences
- **Source de vérité du sous-ensemble « contrat »** : la liste d'endpoints + schémas est *dérivée de ce que
  le Shield consomme réellement* (documentée ici, à re-synchroniser si le Shield évolue).
- **Complément optionnel côté Shield** : un smoke test E2E dans le repo Shield (frontend/backend Shield
  contre une stack RAGFlow) reste pertinent pour couvrir **C1**, mais il est distinct de cette suite et ne
  la remplace pas.

---

## 0. Plan de mise en œuvre (TODO)

Plan incrémental : chaque étape est **lançable et validable** indépendamment avant de passer à la
suivante. Cocher une case suppose que son **critère de validation** est vert.

### Phase 1 — Socle stack de test
- [x] **1.1** Écrire `docker/docker-compose-test.yml` (stack RAGFlow complète + service `ollama`).
  - *Fait & validé :* projet Compose isolé `ragflow-test`, **6/6 conteneurs `healthy`** sur l'image
    `eurelis/ragflow:v0.26.1-eurelis.3`. Image sous test = `${RAGFLOW_TEST_IMAGE:-eurelis/ragflow:latest}`
    (image du fork, découplée de l'upstream). Montages `entrypoint.sh`/`service_conf.yaml.template`
    du dépôt retirés (fragiles : cassent le boot si l'image diffère du dépôt).
  - *Apprentissages :* (a) l'image Docker Hub Eurelis est **amd64-only** → `platform: linux/amd64`
    (émulation sur Apple Silicon, `start_period` porté à 240 s) ; (b) lancement =
    `RAGFLOW_TEST_IMAGE=eurelis/ragflow:<tag> docker compose -f docker/docker-compose-test.yml up -d` ;
    (c) prévoir ~20 Go de disque libre côté VM Docker Desktop (l'image pèse ~8,5 Go).
- [x] **1.2** Précharger les modèles Ollama (chat léger + embedding).
  - *Fait & validé via `make e2e-models` :* `qwen2.5:0.5b` (chat) + `nomic-embed-text` (embedding, **dim
    768**) présents ; `/api/generate` et `/api/embeddings` répondent 200. La dim 768 = à déclarer côté
    provider embedding du tenant (Phase 2.2).
- [x] **1.3** Health de la stack RAGFlow.
  - *Validé :* `GET :9380/api/v1/system/healthz` → **200** `{db,doc_engine,redis,storage,status = ok}` ;
    admin `:9381` répond (401 sans auth = serveur up) ; version image = `v0.26.1-eurelis.3`.

### Phase 2 — Squelette de la suite `test/eurelis/`
- [x] **2.1** `conftest.py` + `configs.py` + `libs/` : auth (`register → login → token`), clients `httpx`
  (`api` Bearer, `admin` :9381), fixture SDK optionnelle (`sdk_client`, skip si non installé).
  - *Fait & validé :* suite **httpx-first** (on assert sur le JSON brut). 3 tests de fumée p0 passent
    (`test/eurelis/test_smoke.py`). Registration activée sur la stack de test (`REGISTER_ENABLED=1` dans
    le compose). Mot de passe RSA de l'upstream réutilisé (vérifié). SDK non retenu comme dépendance
    (nécessite install + métadonnées ; masque le JSON qu'on veut contrôler).
- [x] **2.2** Provider Ollama déclaré sur le tenant (chat + embedding) — `libs/ragflow_api.py`.
  - *Fait & validé :* amorçage idempotent via l'API RESTful `tenant_model`. Défauts confirmés = Ollama.
- [x] **2.3** Seed idempotent : dataset + document de référence (parsé) + chat — `seed.py`.
  - *Fait & validé :* `make e2e-seed` deux fois → retrouve l'existant, pas de doublon. Le chat obtient
    `llm_id=qwen2.5:0.5b@local@Ollama`.

**Findings empiriques (à réutiliser en Phase 4+) :**
- **Auth** : `POST /api/v1/users` (register) → `POST /api/v1/auth/login` (en-tête `Authorization` JWT en
  réponse) → `POST /api/v1/system/tokens` (token Bearer, celui du Shield). Le Bearer token est accepté
  par les endpoints RESTful `/api/v1/*`.
- **Amorçage Ollama** (système `tenant_model`) : `PUT /api/v1/providers {provider_name:"Ollama"}` →
  `POST /api/v1/providers/Ollama/instances` avec `model_info:[{model_type:[…],model_name,max_tokens}]`
  et `base_url:"http://ollama:11434"` (**hostname réseau Docker**, validation côté serveur) →
  `PATCH /api/v1/models/default`. Référence modèle = `model@instance@provider` (ex. `nomic-embed-text@local@Ollama`).
- **Incohérences de forme JSON** (piège pour les schémas) : `/datasets` → `data` est une **liste** ;
  `/datasets/{id}/documents` → `data={"docs":[…]}` ; `/chats` → `data={"chats":[…]}`.
- **Contraintes** : créer un chat exige un document **parsé** (`run=DONE`) dans le dataset ; le parse est
  asynchrone (poll sur `docs[].run`), rapide avec Ollama (~6 s pour un petit doc).

### Phase 3 — Orchestration « une commande »
- [x] **3.1** `test/eurelis/Makefile` : cibles `e2e`, `e2e-up`, `e2e-wait`, `e2e-models`, `e2e-seed`,
  `e2e-run`, `e2e-health`, `e2e-ps`, `e2e-logs`, `e2e-down`, `e2e-reset`.
  - *Fait & validé :* Makefile dédié (n'altère pas le Makefile racine). Chemins calculés depuis sa
    propre position ; image/plateforme surchargables ; `make help`, `e2e-health`, `e2e-ps` testés OK
    sur la stack qui tourne. `e2e-seed`/`e2e-run` pointent sur `test/eurelis/` (peuplé en Phases 2 et 4+ ;
    `e2e-seed` no-op tant que `seed.py` absent).
- [x] **3.2** Rejeu rapide.
  - *En place :* `make -C test/eurelis e2e-run` relance pytest sur la stack déjà up (validation
    effective quand les tests existeront — Phase 4).

### Phase 4 — P0 : contrat Shield (structure des flux JSON)
- [x] **4.1** Schémas JSON Schema des endpoints Shield (`test/eurelis/schemas/`) + helper de validation
  (`libs/contract.py`, `additionalProperties` autorisé → seuls retrait/renommage/retypage détectés).
- [x] **4.2** Contrat **SSE des complétions** (`test/eurelis/shield_contract/test_completions_sse.py`, 7 tests).
  - *Validé :* enveloppe `{code,message,data}`, frames streaming (`final:false`) vs finale (`final:true`,
    +`usage`), sentinelle terminale `data:true`, `reference.chunks`/`doc_aggs` + `usage` (tokens) conformes.
    Affinage capté par le test : `doc_aggs` n'est présent que sur la frame finale.
- [x] **4.3** Chats (`/chats` liste + par id), sessions (create/list/history/rename/delete), documents
  (download + upload fichier chat), `system/version` — `test_chats_sessions.py`, `test_documents.py`.
  - *Validé :* `make -C test/eurelis e2e-run PYTEST_ARGS="-m p0"` → **16 passed, 1 skipped**.
  - *Gap connu :* endpoint image de chunk (`/documents/images/{id}`) **skippé** — la donnée de référence
    (doc texte) n'a pas de chunk illustré. À couvrir avec un doc contenant une image (Phase 4 bis).
  - *Findings de forme (schémas)* : `/system/version` → `data` **string** ; `/chats` → `data.chats[]` ;
    `/chats/{id}/sessions` → `data` **liste** ; upload chat → `data` = DocumentRecord.

### Phase 5 — P1 : correctifs Eurelis
- [x] **5.1a** Chats partagés en équipe visibles (`test_team_shared_chats.py`) — **correctif phare validé**.
  - *Validé :* A invite B → B accepte (`PATCH /tenants/{id}`) → A crée un chat `permission:team` → B le voit ;
    contrôle : B ne voit **pas** les chats `me` de A. Flux multi-utilisateur réel (2ᵉ user, jointure tenant).
- [x] **5.1b** Chemin de retrieval (`test_retrieval.py`) — garde `rag/nlp/search.py` (zone du correctif
  « chunk parent orphelin ») contre une régression de crash/forme.
  - *Validé :* `make -C test/eurelis e2e-run PYTEST_ARGS="-m p1"` → **3 passed**. Suite complète : **19 passed, 1 skipped**.
- [ ] **5.1c** *Différé* — **cascade delete** des fichiers chat (nettoyage bucket MinIO `{user}-downloads`
  à la suppression de session) : nécessite une introspection du stockage objet (client MinIO/boto). À
  ajouter avec un helper d'accès MinIO.
- [ ] **5.1d** *Différé* — reproduction **exacte** du chunk orphelin (config NER/parent-child produisant un
  parent absent) : non déterministe ; couvert indirectement par 5.1b. Envisager un test unitaire ciblé.
- [ ] **5.2** *Différé (unitaire / cloud-gated)* — correctifs **provider-cloud** (clé Bedrock non écrasée,
  `BedrockCV`, fallback IMAGE2TEXT→CHAT) : `add_llm` valide par un **appel réel** au provider → non testable
  sur la stack Ollama locale sans credentials cloud. À couvrir par des tests unitaires sur la logique de
  `add_llm`/`tenant_model_service`, et/ou un palier `@pytest.mark.cloud` activé par clés API.

### Phase 6 — P1 : évolutions Eurelis
- [x] **6.1** Stats de consommation user (`:9380`) + admin (`:9381`) — `test_usage_stats_user.py` (6),
  `test_usage_stats_admin.py` (3).
  - *Validé :* schéma **et cohérence des agrégats** (somme tokens par tour = total ; pct = 100 ; total
    ingestion = somme par base) ; `/me/session` = contrat SessionStats du Shield ; contrôle d'accès admin
    (401 sans JWT) ; auth admin via `crypt()` + JWT header (serveur Flask :9381).
  - *Matrice INDÉPENDANTE (source × token_type)* — `test_usage_logging_matrix.py` : chaque test isole
    UNE méthode de logging via un scénario qui ne déclenche qu'elle, et vérifie que la cellule ciblée
    augmente (et, quand isolable, que les voisines n'augmentent pas). Cellules couvertes :
    - `chat/llm` isolé (chat **sans** base → llm seul, embedding=0) ;
    - `chat/embedding` (chat **avec** base → embedding de requête retrieval) ;
    - `ingestion/embedding` isolé (parse **naive** → llm=0) ;
    - `ingestion/llm` (parse `auto_keywords`+`auto_questions`) ;
    - `search/llm` + `search/embedding` (flux recherche IA, `search_config.chat_id` requis).
    Helper `libs/usage.py` (`usage_matrix` par `?source=`). Note : `POST /retrieval` n'est PAS instrumenté ;
    l'embedding `chat` provient de l'embedding de requête du flux chat.
  - **Finding (cache, pas un bug) :** l'extraction mots-clés/questions passe par un **cache LLM**
    (Redis, clé = `llm_name + contenu`). Sur un **cache hit**, l'appel LLM est sauté → aucun token
    comptabilisé. C'est ce qui donnait l'illusion d'une intermittence (1er parse = miss → tokens logués ;
    re-parse du même contenu = hit → 0). **Investigation faite : la propagation ContextVar du task
    executor fonctionne** — vérifié empiriquement (contenu unique → 603 tokens ; même contenu → 0).
    `test_ingestion_llm_logged` utilise donc un **contenu unique** (cache miss garanti) → **déterministe**.
    *Corollaire produit* : les tokens LLM d'ingestion sont **sous-comptés** quand un même contenu de chunk
    se répète (cache global par contenu, tous tenants/datasets confondus) — comportement correct (pas
    d'appel = pas de tokens), mais à garder en tête pour l'interprétation des stats. L'instrumentation
    agrège tous les appels LLM du parse (mots-clés, questions, Raptor, GraphRAG) dans un unique bucket
    `llm@ingestion` — non séparables par activité.
  - **Extraction de contenu par LLM de vision (image2text)** — `test_usage_logging_vision.py`, marker
    `vision`, **gaté par `EURELIS_RUN_VISION=1`** (skippé par défaut). Chemin : parser PICTURE /
    VisionFigureParser → `LLMBundle.describe()` → même bucket `ingestion/llm`. Ingère une image et assert
    `Δ(ingestion, llm)` pour le modèle vision. **Deux providers, choix auto :**
    - **OpenAI cloud** (`gpt-5.4-mini`) si `OPENAI_API_KEY` défini → **VALIDÉ en live** (~15 s) : inférence
      distante, ES non sollicité, fiable. L'instance OpenAI (qui porte la clé) est supprimée en teardown.
    - **Ollama local** (`moondream`) sinon → ⚠️ inférence locale qui **fait crasher Elasticsearch** sous
      émulation (VM 15,6 Go, ES 8 Go + modèle vision + ragflow) — non fiable ici, réservé à un hôte capable.
    NB : DeepDoc (défaut) fait l'OCR/layout avec des modèles **embarqués** → aucun appel LLM, rien à loguer.
  - *Différé :* `agent/*` (nécessite un agent canvas DSL exécutant l'outil retrieval — lourd/instable
    avec un 0.5B) ; Raptor / GraphRAG (dizaines d'appels LLM, couverts indirectement par `llm@ingestion`).
- [x] **6.2** Supervision modèles (`:9381`) — `test_model_supervision.py` (4).
  - *Validé (lecture) :* contrat `{added_models, default_models, instances}`, matrice `compare`
    multi-tenants, et **masquage des clés API** (aucun champ `api_key` brut ; `api_key_hint` masqué) —
    vérifié récursivement.
  - *Validé (mutations) :* `test_supervision_copy_defaults_delete` — roundtrip A→tenant cible vierge :
    `instances/copy` (retour `{added}`) → la clé est **propagée mais reste masquée** chez la cible →
    `defaults/copy` (défauts cible = Ollama) → `instances/delete` (retour `{deleted}`, cible re-vidée).
  - *Findings :* auth admin = HTTP header `Authorization: <JWT>` (JWT signé renvoyé par `/admin/login`,
    décodé par le `request_loader`), password chiffré via `api.utils.crypt.crypt`.
- [x] **6.4** **Patch `llm_factories`** — `test_llm_factories_patch.py` (3 tests). Le fork n'édite jamais
  `conf/llm_factories.json` (upstream) ; les surcharges vivent dans `conf/llm_factories.patch.json`, fusionné
  au boot par `common/settings.py`. Un patch **synthétique** (`test/eurelis/fixtures/llm_factories.patch.json`)
  est **monté** dans la stack de test (`docker-compose-test.yml` → `/ragflow/conf/llm_factories.patch.json`).
  - *Validé :* catalogue fusionné exposé par l'API — **nouveau provider** (`EurelisMergeTest` + son modèle) et
    **append d'un modèle** à un provider existant (`eurelis-openai-marker` sur OpenAI, avec dédup). Vérifie le
    mécanisme de merge de bout en bout au démarrage. (`GET /providers?available=true`, `/providers/<p>/models`.)

- [x] **6.3a** Group work / équipes — **déjà couvert** par `eurelis_fixes/test_team_shared_chats.py` (Phase 5).
- [x] **6.3b** **PII masking en intégration** — `eurelis_features/test_pii_masking.py` (3 tests, marker `pii`).
  - *Fait & validé :* stack avec **PII toujours activé mais scopé au suffixe `::pii`**
    (`PII_MASKING_PROVIDERS=.*::pii@.*`, interpolé via `EURELIS_PII_*` pour ne pas être écrasé par le `.env`).
    Deux modèles Ollama (`qwen2.5:0.5b` sans PII / `qwen2.5:0.5b::pii` avec) et deux chats de référence.
    Observabilité via le **journal d'audit** `ragflow.pii` monté sur l'hôte (`docker/ragflow-logs/pii_audit.log`).
    Assertions : le chat `::pii` déclenche une détection `CREDIT_CARD` ; le chat standard **jamais** ; **aucune
    valeur en clair** journalisée. Escape : `make e2e-pii-off`. Complète les 41 tests unitaires existants.
  - *Findings :* le suffixe est retiré avant l'appel Ollama (vrai modèle appelé) ; Presidio s'initialise à
    chaque boot (~30 s, télécharge spaCy) → à pré-embarquer en CI ; ne pas `rm` le fichier d'audit après boot
    (descripteur ouvert → inode orphelin).
- [ ] **6.3c** *Différé (couvert en unitaire)* — **sitemap connector** : tests unitaires existants
  (`test/unit_test/data_source/test_sitemap_connector_unit.py`). Intégration live = ingestion d'un sitemap réel.
  - *Validé (noyau) :* `make -C test/eurelis e2e-run` → **30 passed, 1 skipped**.

### Phase 7 — Consolidation
- [x] **7.1** `test/eurelis/README.md` — guide de lancement/rejeu : prérequis, démarrage rapide, cibles
  Make, markers (p0/p1/pii), architecture (stack isolée + Ollama + PII scopé ::pii + 2 chats), structure,
  périmètre couvert, reliquats, et tableau de **dépannage** (amd64, disque plein, uv, audit PII, spaCy).
- [ ] **7.2** (Optionnel) Palier `@pytest.mark.cloud` gated par clés API pour le vrai chemin Bedrock/Gemini.
- [ ] **7.3** (Optionnel) Intégration CI : `make e2e` en pipeline.

---

## 1. Décisions structurantes

| Axe | Choix | Justification |
|---|---|---|
| **Instance cible** | Stack Docker locale dédiée | `docker compose` monté par le script de test (image Eurelis), réinitialisable via `down -v`. Isolé, reproductible, CI-friendly. |
| **Framework/outil** | `pytest` + SDK Python `ragflow_sdk` + `httpx` brut | Réutilise l'auth et les patterns existants de `test/testcases/`. SDK pour les scénarios lisibles, `httpx` pour le SSE, les endpoints admin (:9381) et usage-stats. |
| **LLM** | LLM local (Ollama) déterministe | Zéro coût, zéro clé cloud, reproductible en CI. Un modèle chat + un modèle embedding servis localement. On valide la *structure* JSON, pas le contenu généré. |
| **Validation** | Contrat de schéma + assertions ciblées | Schéma Pydantic/jsonschema par endpoint (structure/typage figés) + assertions métier sur les invariants des correctifs. Robuste au non-déterminisme, détecte les breaking changes de flux. |
| **Organisation** | Suite Eurelis dédiée `test/eurelis/` | Conforme à la convention d'empreinte upstream minimale. Résiste aux rebases upstream. Header Eurelis sur chaque fichier. |

---

## 2. Architecture de la stack de test

```
┌─────────────────────────────────────────────────────────┐
│  docker compose (profil de test Eurelis)                  │
│                                                           │
│  ragflow-server (Quart :9380)  ← API + SDK + usage-stats  │
│  admin-server   (Flask :9381)  ← supervision, stats admin │
│  task-executor(s)              ← ingestion / parsing      │
│  mysql, redis, minio, elasticsearch                       │
│  ollama :11434                 ← chat + embedding locaux   │
└─────────────────────────────────────────────────────────┘
                          ▲
                          │ pytest (test/eurelis/)
                          │  - auth : register qa → login → token système
                          │  - SDK ragflow_sdk + httpx
                          │  - validation schéma (Pydantic/jsonschema)
```

- **Ollama** est ajouté au compose comme service dédié aux tests, préchargé avec un modèle chat léger
  (ex. `qwen2.5:0.5b` ou `llama3.2:1b`) et un modèle d'embedding (ex. `nomic-embed-text` / `bge-m3`),
  déclarés comme providers `OpenAI-API-compatible` côté tenant de test.
- **PII masking** (Presidio + spaCy) tourne entièrement en local → déterministe, testable sans LLM cloud.
- Réinitialisation : `docker compose down -v` garantit un état vierge ; l'isolation intra-run passe par
  des noms préfixés UUID + `delete_all` en teardown.

### Caveat providers cloud
Certains **correctifs** sont spécifiques à un provider cloud et **ne peuvent pas** être validés bout-en-bout
avec Ollama :
- clé API Bedrock non écrasée dans `add_llm`,
- `BedrockCV.async_chat` / `async_chat_streamly`,
- fallback IMAGE2TEXT→CHAT (déclenché par le PDF vision parser).

→ Ces correctifs sont couverts par des **tests de contrat au niveau API** (structure de la config LLM
persistée, résolution du `model_type`) sans appel réseau cloud, et/ou par les **tests unitaires existants**.
Un palier optionnel `@pytest.mark.cloud` (désactivé par défaut, activé par clés API) pourra valider le
vrai chemin Bedrock/Gemini plus tard.

---

## 3. Périmètre de test (matrice de couverture)

### 3.1 Contrat Shield — stabilité des flux JSON (priorité P0)
Endpoints RAGFlow réellement proxyfiés par le Shield backend :

| Domaine | Endpoint(s) | Point de vigilance |
|---|---|---|
| Agents | `GET /api/v1/chats`, `GET /api/v1/chats/{id}` | Champs consommés par Shield (`id`, `name`, `llm_id`, `prompt`…) présents et typés |
| Sessions | `GET/POST/DELETE /api/v1/chats/{id}/sessions`, `GET/PATCH /.../{sid}` | Cycle de vie complet, forme de l'historique (`messages` + `reference`) |
| **Complétions SSE** | `POST /api/v1/chats/{id}/completions` (stream=true) | **Frames SSE** : `answer`, `reference.chunks[]`, `reference.doc_aggs[]`, `session_id`, `final`. Cœur du contrat. |
| Documents | `POST /api/v1/documents/upload`, `GET /api/v1/documents/images/{id}`, `GET /api/v1/datasets/{ds}/documents/{doc}` | Type MIME, blobs, `DocumentRecord` |
| Version | `GET /api/v1/system/version` | Présence + format |

### 3.2 Correctifs Eurelis (priorité P1)

| Correctif | Test |
|---|---|
| Chats partagés équipe visibles dans la liste | Créer tenant + membre, chat `permission=team`, vérifier visibilité côté membre |
| Chunk parent orphelin en retrieval | Retrieval sur config NER produisant un parent absent → pas de crash, repli sur enfants |
| Cascade delete fichiers chat | Upload fichier en session → delete session → bucket `{user}-downloads` nettoyé |
| Clé Bedrock / fallback IMAGE2TEXT→CHAT / BedrockCV | Contrat API (config persistée, `model_type` résolu) — cf. caveat cloud |
| ContextVars asyncio (3.13) | Vérifié indirectement par le bon fonctionnement de l'ingestion parallèle |

### 3.3 Évolutions Eurelis (priorité P1)

| Feature | Endpoints / Vérifications |
|---|---|
| Stats de consommation (user) | `GET /api/v1/usage-stats/me/{sources,timeseries,session/{id},ingestion,breakdown}` — schéma + cohérence des agrégats après un chat réel |
| Stats de consommation (admin :9381) | `GET /api/v1/admin/stats/{sources,users,users/{email},timeseries,breakdown}` — schéma + contrôle d'accès admin |
| Supervision modèles (admin :9381) | `GET .../tenants/{id}/models`, `.../models/compare`, `POST .../instances/{copy,delete}`, `.../defaults/copy` — **masquage clés API jamais en clair**, matrice correcte |
| Group work / équipes | Provisioning, ajout/retrait membres, partage ressources |
| PII masking | Détection regex + NER, masquage/réhydratation, opt-in `::pii`, action BLOCK, audit log (local, déterministe) |
| Sitemap connector | Parsing sitemap + index récursif, filtre regex, guard SSRF (local) |

---

## 4. Principes de validation

1. **Contrat de schéma d'abord.** Chaque endpoint a un modèle Pydantic (ou jsonschema) de réponse. Le test
   valide que la réponse **se désérialise sans erreur** dans le schéma → détecte tout champ retiré, renommé
   ou retypé (= breaking change pour le Shield). Les schémas sont versionnés dans `test/eurelis/schemas/`.
2. **Assertions fonctionnelles ciblées** en complément : codes de retour, invariants métier des correctifs
   (visibilité, nettoyage, contrôle d'accès), cohérence numérique des agrégats de stats.
3. **On ne fige jamais le contenu généré par le LLM** (texte de réponse, embeddings) — seulement la forme.
4. **SSE** : on parse le flux, on valide chaque type de frame contre son schéma, et on vérifie la présence
   d'une frame `final` + d'un `session_id` cohérent.
5. **Marqueurs de priorité** : `p0` (contrat Shield), `p1` (correctifs + évolutions), `cloud` (opt-in, gated
   par clés API), réutilisant la convention pytest existante.

---

## 5. Lancement et rejouabilité

Cible : **une commande**. Un `Makefile` (ou script `test/eurelis/run.sh`) qui enchaîne :

```
make e2e            # up stack + ollama, pull modèles, wait health, seed, pytest, (option) teardown
make e2e-up         # monte la stack de test seule
make e2e-seed       # injecte le jeu de données de référence (documents fixtures + tenant/models)
make e2e-run        # relance uniquement pytest contre la stack déjà up  ← rejeu rapide
make e2e-down       # docker compose down -v (reset complet)
```

- **Seed idempotent** : tenant de test, providers Ollama, dataset + documents de référence, un chat/agent.
- **Rejeu rapide** : `make e2e-run` réutilise la stack up ; l'isolation par UUID + teardown évite la
  pollution entre runs.
- **CI** : le même `make e2e` tourne en pipeline (pas de dépendance à des clés cloud grâce à Ollama).

---

## 6. Arborescence proposée

```
test/eurelis/
├── README.md                  # comment lancer / rejouer
├── conftest.py                # auth (register/login/token), client SDK, httpx admin, seed
├── configs.py                 # HOST_ADDRESS, ADMIN_ADDRESS, credentials, modèles Ollama
├── schemas/                   # modèles Pydantic/jsonschema par endpoint
│   ├── chat.py  sessions.py  completions_sse.py  usage_stats.py  admin_*.py
├── fixtures/                  # documents de référence (pdf/md/txt), payloads
├── shield_contract/           # 3.1 — endpoints consommés par le Shield
├── eurelis_fixes/             # 3.2 — correctifs
└── eurelis_features/          # 3.3 — évolutions
docker/
└── docker-compose-test.yml    # stack + service ollama (profil test)
Makefile                       # cibles e2e-*
```

---

## 7. Prochaines étapes

1. Valider cette stratégie.
2. Écrire `docker-compose-test.yml` (ajout service Ollama + préchargement modèles) et les cibles `make e2e-*`.
3. Poser le squelette `test/eurelis/` (conftest, configs, seed) et un premier test P0 : le contrat SSE des
   complétions (endpoint le plus critique pour le Shield).
4. Dérouler la matrice de couverture par priorité (P0 → P1).
