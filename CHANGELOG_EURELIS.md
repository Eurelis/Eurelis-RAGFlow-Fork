# Changelog Eurelis

Historique des modifications spécifiques au fork Eurelis de [RAGFlow](https://github.com/infiniflow/ragflow).

---

## [v0.26.3-eurelis.7] - 2026-07-14

Basé sur RAGFlow `v0.26.3`. Correctif d'un plantage du panel admin lors du changement de mot de passe d'un utilisateur provisionné via SSO (OIDC/OAuth), qui n'ont pas de mot de passe local.

### Fixed
- **Changement de mot de passe admin pour un utilisateur SSO (`PUT /api/v1/admin/users/{username}/password`)** — `UserMgr.update_user_password` (`admin/server/services.py`) appelait `check_password_hash(usr.password, psw)` pour éviter une écriture inutile si le nouveau mot de passe était identique à l'ancien. Or les comptes provisionnés via SSO (OIDC/OAuth/GitHub) n'ont pas de mot de passe local (`usr.password is None`, colonne `password` en `null=True`) : `check_password_hash(None, …)` plante à l'intérieur de Werkzeug (`pwhash.split('$')` → `'NoneType' object has no attribute 'split'`), renvoyant un `500`. La comparaison est désormais gardée par `usr.password`, si bien qu'un compte sans mot de passe passe directement à l'enregistrement du nouveau (donnant à ces utilisateurs un fallback mot de passe en complément du SSO). Correctif également soumis en upstream (PR infiniflow/ragflow #16914).

---

## [v0.26.3-eurelis.6] - 2026-07-13

Basé sur RAGFlow `v0.26.3`. Correctif de la validation d'email de l'endpoint admin de création d'utilisateur : le plus-addressing (`+` dans la partie locale) était refusé, ce qui empêchait le Shield d'auto-provisionner certains comptes.

### Fixed
- **Plus-addressing (`+`) dans l'email de `POST /api/v1/admin/users`** — la validation de `UserMgr.create_user` (`admin/server/services.py`) utilisait le motif `^[\w\._-]+@…`, dont la classe de caractères de la partie locale omettait `+` : toute adresse en plus-addressing (ex. `v.lambert+diligentia@eurelis.com`), pourtant valide au sens RFC 5321, était rejetée en `400 « Invalid email address »` avant même le contrôle d'unicité. Le Shield, qui auto-provisionne les comptes via cet endpoint, ne pouvait donc pas les créer (le chemin OIDC/Keycloak, lui, ne valide pas l'email — issu d'une claim de token — et passait). Ajout de `+` à la classe de caractères de la partie locale (`^[\w\.+_-]+@…`) ; le domaine est inchangé. L'endpoint d'inscription par mot de passe (`api/apps/restful_apis/user_api.py`), qui porte le même motif, n'est volontairement pas touché (hors périmètre).

### Tests
- **Contrat Shield — création d'utilisateur admin** (`test/eurelis/shield_contract/test_admin_user_creation.py`, `p0`) : fige l'acceptation d'un email avec `+` (`POST /api/v1/admin/users` → `200`, pas de « Invalid email address », `password` absent de la réponse) et le rejet d'un email réellement invalide (`400` + message « Invalid email address »). Schéma `ADMIN_CREATED_USER_SCHEMA` ajouté (`test/eurelis/schemas/admin.py`).

---

## [v0.26.3-eurelis.5] - 2026-07-12

Basé sur RAGFlow `v0.26.3`. Sessions de login interactives **multi-appareils** avec **expiration** : plusieurs sessions d'un même compte coexistent désormais (fini le « dernier login gagne »), bornées par un TTL de 12 h. Ajout de la couverture de non-régression du contrat de sessions et de trois endpoints consommés par le Shield.

### Added
- **TTL de session JWT (12 h)** — la validation des tokens applique désormais `max_age=12*3600` à `jwt.loads`, côté API (`api/apps/__init__.py`) **et** serveur admin (`admin/server/auth.py`) : un JWT plus ancien que 12 h lève `SignatureExpired` → 401, forçant une reconnexion périodique. Aucune expiration temporelle n'était appliquée auparavant (les tokens restaient valides jusqu'à rotation ou logout).

### Changed
- **Sessions login multi-appareils** — les points de login (mot de passe et OAuth/SSO côté API `user_api.py`, login admin `auth.py`) ne régénèrent plus systématiquement l'`access_token` : il n'est renouvelé que s'il est absent ou invalidé (préfixe `INVALID_`). Plusieurs sessions d'un même compte (navigateurs/appareils, ou API `:9380` + admin `:9381`) partagent alors le même `access_token` et **coexistent**, au lieu que chaque nouveau login évince les précédents. Combiné au TTL ci-dessus, l'exposition d'un token reste bornée dans le temps.

### Tests
- **Contrat Shield — sessions login** (`test/eurelis/shield_contract/test_auth_sessions.py`, `p0`) : coexistence multi-session (un 2ᵉ login ne révoque pas le token du 1er) sur l'API et l'admin, et application du TTL (JWT forgé à −13 h refusé, token frais accepté ; forge signée avec le secret réel du serveur, `skip` propre si le secret est indisponible côté hôte).
- **Contrat Shield — `GET /system/version`** (`test/eurelis/shield_contract/`, `p0`) : enveloppe `{code, message, data}` figée, `message` inclus (le Shield le lit pour son diagnostic d'erreur).
- **Contrat Shield — endpoints Admin de rattachement d'équipe** (`test/eurelis/shield_contract/test_admin_teams.py`, `p0`) : résolution d'`id` utilisateur (`GET /admin/users/{email}` → `data` = liste, utilisateur inexistant → `data: []`) et ajout de membre (`POST /admin/tenants/{tenant_id}/users`) avec idempotence (`400` + sous-chaîne « already »).

### Notes
- Le bug upstream des tuples `update_time` / `update_date` dans le login admin (`admin/server/auth.py`, PR upstream infiniflow/ragflow #10642) est **laissé tel quel** pour préserver des rebases propres — il n'affecte pas l'authentification.

---

## [v0.26.3-eurelis.4] - 2026-07-09

Basé sur RAGFlow `v0.26.3`. Correctif du masquage PII multi-langue : l'init Presidio échouait dès que `PII_MASKING_LANGUAGES` contenait une langue autre que « en » (ex. `fr,en`), désactivant silencieusement le masquage. Le modèle FR embarqué en `.3` est désormais réellement exploitable.

### Fixed
- **Init du masquage PII en multi-langue (`fr`, `fr,en`)** — `RecognizerRegistry()` était construit avec son `supported_languages` par défaut (`["en"]`) que `load_predefined_recognizers()` ne met jamais à jour ; l'`AnalyzerEngine`, lui, était créé avec la liste complète des langues, d'où l'erreur Presidio *« Misconfigured engine, supported languages have to be consistent »* et le masquage désactivé silencieusement (`PII_MASKING_STARTUP_FAIL=false`). Le registre est désormais initialisé avec la liste complète des langues configurées (`RecognizerRegistry(supported_languages=languages)`). Les recognizers regex/checksum (EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, IBAN_CODE, IP_ADDRESS) restent disponibles pour chaque langue ; les entités NER (PERSON, LOCATION, DATE_TIME) proviennent du modèle spaCy de chaque langue. Le cas `en` seul est inchangé.

### Tests
- **Non-régression : init PII multi-langue** (`test_initialize_multilang_fr_en` dans `test/unit_test/rag/llm/test_pii_masking.py`) — vérifie que l'init `fr,en` avec NER réussit (`is_available() is True`). Chemin non couvert auparavant : tous les tests d'init utilisaient `PII_MASKING_NER=false` et la langue « en ».

---

## [v0.26.3-eurelis.3] - 2026-07-09

Basé sur RAGFlow `v0.26.3`. Ajout du modèle spaCy français *small* dans l'image pour activer le NER FR du masquage PII (Presidio).

### Added
- **Modèle spaCy `fr_core_news_sm` (3.8.0, ~16 Mo)** embarqué dans l'image aux côtés de `en_core_web_sm`, via `pyproject.toml` (installé par `uv sync`, sans téléchargement runtime). Débloque la détection NER FR (PER/LOC/DATE_TIME) du masquage PII sur les déploiements francophones (ex. Synerga) avec `PII_MASKING_NER=true` + `PII_MASKING_LANGUAGES=fr` + `PII_MASKING_NER_MODEL_FR=fr_core_news_sm`. Le modèle EN existant est conservé. Variante *small* choisie (précision NER moindre que `lg` acceptée) pour garder l'image légère.

### Tests
- **Non-régression : présence des modèles spaCy** (`test/eurelis/eurelis_features/test_spacy_models.py`, `p1`) — vérifie, via `docker exec` dans le conteneur sous test, que l'image embarque `en_core_web_sm` **et** `fr_core_news_sm`, et que le NER FR détecte bien une PER (« Jean Dupont ») et une LOC (« Paris »). Garde-fou contre la régression prod (image sans modèle FR).

### Notes
- `uv.lock` régénéré avec un `uv` récent (0.11.x) respectant `exclude-dependencies` : seule l'entrée `fr-core-news-sm` est ajoutée, `unclecode-litellm` et `agentrun-mem0ai` restent exclus.

---

## [v0.26.3-eurelis.2] - 2026-07-05

Basé sur RAGFlow `v0.26.3`. Ajout du partage d'équipe des Search apps, d'un sélecteur de fenêtre temporelle pour les statistiques, et de la couverture de non-régression du contrat Search consommé par le Shield.

### Added
- **Partage d'équipe des Search apps** (`permission` `me|team`) — symétrique au partage des chats : une search `team` créée par le propriétaire d'un tenant devient visible par les membres l'ayant rejoint. Colonne `search.permission` + migration, filtre équipe dans `SearchService.get_by_tenant_ids`, récupération des tenants rejoints dans le listing (`search_api`), et sélecteur « Me / Équipe » dans les réglages search (front).
- **Sélecteur de fenêtre temporelle des statistiques** (pages user + admin) — granularité Semaine/Mois/Année avec navigation ◀▶, mode « Personnalisé » (calendrier de plage), libellés d'axe hebdomadaires localisés (`YYYY - Sww`). La sélection est conservée entre `/admin/stats` et `/admin/stats/users/<email>` (store dédié).
- **Tests de non-régression Search** — contrat Shield des 5 endpoints de la feature Search UI (028 : liste, détail, retrieval, résumé SSE, recommandation ; `p0`) et partage d'équipe des search (`p1`), avec search app de référence ajoutée au seed.

### Changed
- **Menu mobile** : masquage des liens Discord / GitHub / Help (branding Eurelis), en cohérence avec le masquage déjà en place côté desktop.

### Notes
- Validé par la suite de non-régression sur l'image `v0.26.3-eurelis.2` : **p0 vert** (contrat Shield, dont les 5 endpoints Search) et **partage search `p1` vert**.
- La search app de référence du seed est créée avec un modèle de résumé (`chat_id`) : l'endpoint `/searches/{id}/completions` ne retombe pas sur le modèle par défaut du tenant quand `chat_id` est absent.

---

## [v0.26.3-eurelis.1] - 2026-07-05

Basé sur RAGFlow `v0.26.3`. Rebase du fork sur la nouvelle base upstream — aucune nouvelle fonctionnalité Eurelis, mais réintégration des 43 commits Eurelis sur `v0.26.3` avec résolution des conflits.

### Changed
- **Rebase sur RAGFlow `v0.26.3`** — intégration de 299 commits upstream (`v0.26.1` → `v0.26.3`) : parser DOCX dédié, comptabilité de tokens agrégée « autoritative » + propagation Langfuse des runs agent, provider « New API » (passerelles OpenAI-compatibles), correctifs GraphRAG (`RedisDB.mget`), PDF compressés, fuite de sessions MCP, XSS du modal de rerun agent, etc.
- **Masquage PII fusionné avec la nouvelle comptabilité de tokens upstream** — le hook PII streaming (`chat_model.py` : retour tuple de `_construct_completion_args` + `StreamingUnmasker`/flush) coexiste avec `stream_options.include_usage` + `_commit_round` de l'upstream. Nouvelle classe vision `NewAPICv` intégrée à côté des méthodes PII de `BedrockCV` (`cv_model.py`).
- **Statistiques de consommation alignées sur l'upstream** — comptage `add_ingestion_llm_tokens` / `used_tokens` conservé face au nouveau logging paresseux et à `_report_usage` (`llm_service.py`) ; condition `model_config["model_type"]` harmonisée (`dialog_service.py`).
- **Branding Eurelis réappliqué** sur le nouveau header responsive upstream (`useHeaderNavLayout`, mode compact) — liens Discord/GitHub masqués.

### Fixed
- **`uv.lock` régénéré** avec un `uv` récent respectant `exclude-dependencies` (upstream) : `unclecode-litellm` et `agentrun-mem0ai` restent exclus. Le correctif Eurelis dédié au drop de `unclecode-litellm` devient obsolète (absorbé par le mécanisme upstream).

### Notes
- Deux commits Eurelis écartés au rebase (devenus vides — contenu déjà présent upstream) : correction du commentaire `ContextVars` et drop manuel de `unclecode-litellm`. Un commit i18n FR a été absorbé (mergé upstream).
- Validé par la suite de non-régression : **42 passed / 2 skipped** + palier vision **1 passed** (OpenAI `gpt-5.4-mini`).
- ⚠ La migration `usage_log.token_type` (voir `v0.26.1-eurelis.3`) reste requise sur une base existante non encore migrée.

---

## [v0.26.1-eurelis.3] - 2026-06-30

Basé sur RAGFlow `v0.26.1`. Release finale consolidant les itérations expérimentales `exp.1` → `exp.5` : statistiques de consommation, supervision admin des modèles et correctifs associés.

### Added
- **Supervision admin des modèles par tenant** — nouvelle page d'administration `/admin/model-supervision` (cross-tenant, superuser) pour visualiser, comparer et propager les configurations de modèles.
  - Comparaison multi-tenants en matrice : fournisseurs/instances (clé API **masquée**), modèles par défaut (avec détection des défauts **« pendants »** non résolubles), modèles disponibles (avec filtre texte).
  - Opérations granulaires vers une **liste de tenants cibles** : copier un fournisseur/instance (clé incluse, overwrite), supprimer un fournisseur/instance, copier les modèles par défaut.
  - Backend isolé : blueprint admin Eurelis (`admin/server/admin_model_supervision.py`), 5 routes sous `/api/v1/admin/tenants/…`, ciblant le système `tenant_model_*` (legacy `tenant_llm` hors périmètre). Les clés API ne transitent jamais en clair vers le frontend.
- **Statistiques de consommation de tokens** — table append-only `usage_log` avec dashboards admin et utilisateur. Modèle orthogonal : `source` (flux : `chat` · `search` · `agent` · `ingestion`) × `token_type` (`llm` · `embedding`).
  - Logging câblé sur le chat, le widget chatbot, la recherche IA (`async_ask`), le retrieval d'agent, le retrieval SDK dataset et l'ingestion de documents (tokens *embedding* **et** *LLM*), centralisé dans `api/db/services/eurelis_usage_log.py`.
  - APIs `/api/v1/usage-stats/me/*` (serveur Quart) et `/api/v1/admin/stats/*` (serveur admin Flask) : filtres `source`/`type`, séries temporelles (`by_source`/`by_type`), breakdowns (`group_by=source|type|model|dialog`), `available_sources`/`available_types`.
  - Frontend : dashboard admin, détail par utilisateur et page utilisateur — presets de période, filtres multi-select source/type avec pastilles de couleur, barres empilées par flux, « Top modèles » colorés par nature (`token_type`), filtres de recherche sur les tableaux ressources et utilisateurs.

### Changed
- **Détail de session restreint aux tokens LLM** — `stats_for_session()` filtre les tours sur `token_type` (défaut `llm`). Les totaux et l'histogramme par tour de l'endpoint `/usage-stats/me/session/{id}` reflètent désormais l'usage LLM uniquement, en excluant les embeddings (et autres natures non-LLM).

### Fixed
- **Chats partagés en équipe absents de la liste** — l'endpoint de listing des chats passait `joined_tenant_ids=[]`, donc la clause `(tenant_id ∈ joined ET permission='team')` était toujours vide : seuls les chats propres de l'utilisateur étaient renvoyés. Les chats `permission='team'` des équipes rejointes n'apparaissaient jamais dans la sidebar (accessibles uniquement par lien direct). `joined_tenant_ids` est désormais calculé via `TenantService.get_joined_tenants_by_user_id` et transmis — les membres voient bien les chats partagés avec leur équipe.
- **Démarrage cassé (`ImportError: update_request_with_filtered_beta`)** — `crawl4ai 0.8.9` (sur pypi.org) tire `unclecode-litellm`, un fork de litellm qui s'installe dans le même namespace `litellm/` et écrase le `litellm==1.82.5` pinné, faisant crasher le `task_executor` au boot. `unclecode-litellm` est retiré du `uv.lock` (le build le consomme via `uv sync --frozen`). `pyproject.toml` reste aligné sur l'upstream — son garde-fou `exclude-dependencies` est un champ uv invalide (no-op). Procédure de régénération du lock documentée dans le commit du fix.
- Propagation des `ContextVars` asyncio dans le thread pool (`thread_pool_exec`) sous Python 3.13 (`ThreadPoolExecutor` WorkerContext).
- Dérivation du type `image2text` depuis les tags du factory quand `model_type` l'omet.

### Notes
- ⚠ **Migration manuelle requise** avant de démarrer le serveur sur une base existante (la colonne n'est pas ajoutée par `migrate_db()`) :
  ```sql
  ALTER TABLE usage_log ADD COLUMN token_type VARCHAR(16) NOT NULL DEFAULT 'llm';
  CREATE INDEX usage_log_token_type ON usage_log (token_type);
  ```

---

## [v0.26.1-eurelis.2] - 2026-06-20

Basé sur RAGFlow `v0.26.1`.

### Added
- Provisionnement automatique des équipes à la première connexion OIDC (Option A) :
  les utilisateurs créés via Keycloak sont assignés aux équipes configurées dans
  `default_teams` (liste d'emails d'owners) sans passer par le flux d'invitation.
  Implémenté dans `api/apps/auth/auto_team_provisioning.py`.

---

## [v0.26.1-eurelis.1] - 2026-06-20

Basé sur RAGFlow `v0.26.1`.

### Changed
- Rebase sur RAGFlow `v0.26.1` — intégration de 109 commits upstream (chat channels, PaddleOCR async, Go agent canvas, fix SSRF Markdown, fix OOM PDF)

---

## [v0.26.0-eurelis.2] - 2026-06-19

Basé sur RAGFlow `v0.26.0`.

### Added
- **SitemapConnector** — connecteur d'ingestion de pages web via `sitemap.xml` (sitemaps standard et index récursifs, polling incrémental via `<lastmod>`, conversion HTML→Markdown, protection SSRF, filtre URL regex, suivi de liens PDF)

---

## [v0.26.0-eurelis.2-exp.1] - 2026-06-15 ⚠️ expérimental

Basé sur RAGFlow `v0.26.0` — branche `eurelis/feature/sitemap-connector`.

### Added
- **SitemapConnector** — connecteur d'ingestion de pages web via `sitemap.xml` (sitemaps standard et index récursifs, polling incrémental via `<lastmod>`, conversion HTML→Markdown, protection SSRF, filtre URL regex, suivi de liens PDF)

---

## [v0.26.0-eurelis.1] - 2026-06-14

Basé sur RAGFlow `v0.26.0`.

### Added
- Moteur de masquage PII basé sur Presidio (`rag/llm/pii_masking.py`) — détection et anonymisation des données personnelles dans les requêtes LLM, avec suffixe `::pii` sur le nom du modèle pour activation
- Gestion des équipes (group work) — API, UI admin et i18n pour la création et la gestion des équipes utilisateurs
- Interface d'administration des équipes (`feat(eurelis/admin)`)
- Séparation des surcharges LLM Eurelis dans `conf/llm_factories.patch.json` (Gemini, Bedrock, rangs des providers)
- Documentation Eurelis : guidelines, commandes Claude, procédures fork
- Suppression des blobs uploadés en chat lors de la suppression d'une session
- Remplacement du branding RAGFlow par l'identité Eurelis

### Fixed
- Correction des cas limites du moteur PII masking (streaming, placeholders cross-messages)
- Fallback i18n des templates d'agents, typo `hyphens-auto`, dépendance `useMemo`
- Mirror GitHub pour `graspologic` (fix build — Gitee inaccessible)
- Remplacement du moteur de substitution bash par Python dans `docker/entrypoint.sh` (substitution `${VAR:-default}` plus fiable)

### Changed
- Exclusion des rapports de sync-upstream du tracking git
- Règle MD060 désactivée dans la config markdownlint

---

## [v0.25.6-eurelis.2] - 2026-06-10

Basé sur RAGFlow `v0.25.6`.

### Added

- **PII Masking** — masquage automatique des données personnelles (PII) avant envoi aux LLM,
  via [Microsoft Presidio](https://github.com/microsoft/presidio) :
  - `rag/llm/pii_masking.py` — moteur Presidio : détection, anonymisation, réhydratation des
    réponses (`StreamingUnmasker`, `PiiAuditLogger`, `PiiMaskingEngine` singleton).
  - `rag/llm/chat_model.py` — hook dans `LiteLLMBase._construct_completion_args()` + réhydratation
    dans `async_chat`, `async_chat_streamly`, `async_chat_with_tools`, `async_chat_streamly_with_tools`.
  - `rag/llm/cv_model.py` — intégration dans `GeminiCV`.
  - `api/ragflow_server.py` — initialisation `PiiMaskingEngine.initialize()` au démarrage.
  - `conf/llm_factories.json` — variante `gemini-3.5-flash::pii` (`image2text`).
  - `test/unit_test/rag/llm/test_pii_masking.py` — 41 tests unitaires.
  - `docs/eurelis/features/pii-masking.md` — documentation technique complète.
  - Variables d'environnement : `PII_MASKING_ENABLED`, `PII_MASKING_PROVIDERS`,
    `PII_MASKING_ENTITIES`, `PII_MASKING_SCORE_THRESHOLD`, `PII_MASKING_SCORE_OVERRIDES`,
    `PII_MASKING_ROLES`, `PII_MASKING_LANGUAGES`, `PII_MASKING_NER`, `PII_AUDIT_LOG_ENABLED`, etc.
  - Dépendances : `presidio-analyzer>=2.2.354`, `presidio-anonymizer>=2.2.354`.

### Changed

- **Admin — refonte de la gestion des équipes** :
  - Suppression des pages `/admin/teams` et `/admin/teams/:id`.
  - `/admin/users/:id/team` — nouvelle interface double-liste (dual-listbox) pour gérer les membres
    de l'équipe d'un utilisateur (filtrage, sélection multiple, case à cocher globale).
  - `/admin/users/:id/members` — nouvelle interface double-liste pour gérer les équipes d'un
    utilisateur, avec compteur de membres dans les deux panneaux.
  - Mutations séquentielles pour éviter les deadlocks MySQL (1213) lors de sélections multiples.

### Fixed

- **`LiteLLMBase._clean_conf`** — `model_type` (champ interne RAGFlow injecté depuis l'upstream
  [#15141](https://github.com/infiniflow/ragflow/pull/15141)) n'était pas filtré avant l'appel API,
  causant une erreur `400 Bad Request` sur Bedrock (`extraneous key [model_type] is not permitted`).
  Fix : `gen_conf.pop("model_type", None)` dans `rag/llm/chat_model.py`.
- **`BedrockCV`** — implémentation de `async_chat` et `async_chat_streamly` via
  `litellm.acompletion` (l'implémentation héritée utilisait `self.async_client` non initialisé).

---

## [v0.25.6-eurelis.2-exp.4] - 2026-06-09 ⚠️ expérimental

Basé sur RAGFlow `v0.25.6` — branche `eurelis/main`.

> Première release expérimentale issue de `eurelis/main` : la branche `eurelis/feature/pii-masking` a été intégrée. Contient toutes les modifications de `exp.3`, plus :

### Changed

- **Admin — interface double-liste pour la gestion des équipes** — refonte des pages de gestion membres/équipes :
  - `/admin/users/:id/team` — dual-listbox permettant d'ajouter/retirer des membres de l'équipe d'un utilisateur (filtrage, sélection multiple, case à cocher globale).
  - `/admin/users/:id/members` — dual-listbox pour gérer les équipes auxquelles appartient un utilisateur, avec affichage du compteur de membres dans les deux panneaux.
  - Badge de rôle `normal` masqué (non informatif). Mutations séquentielles pour éviter les deadlocks MySQL (1213) lors de sélections multiples.
  - Suppression des pages `/admin/teams` et `/admin/teams/:id` (remplacées par les vues ci-dessus).

---

## [v0.25.6-eurelis.2-exp.3] - 2026-06-04 ⚠️ expérimental

Basé sur RAGFlow `v0.25.6` — branche `eurelis/feature/pii-masking` (non mergée dans `eurelis/main`).

### Fixed

- **`LiteLLMBase._clean_conf`** — cherry-pick du fix `model_type` depuis `fix/litellm-model-type-leaked-to-api` (absent du tag `v0.25.6-eurelis.2-exp.2`). `gen_conf.pop("model_type", None)` empêche l'envoi du champ interne RAGFlow à l'API Bedrock (`400 Bad Request: extraneous key [model_type] is not permitted`).

### Changed

- **Admin — suppression de la route `/admin/teams`** — la page de gestion des équipes (`/admin/teams`) et son entrée de navigation ont été retirées de l'interface admin. Les routes `/admin/users/:id/team` et `/admin/users/:id/members` restent opérationnelles.

---

## [v0.25.6-eurelis.2-exp.2] - 2026-06-01 ⚠️ expérimental

Basé sur RAGFlow `v0.25.6` — branche `eurelis/feature/pii-masking` (non mergée dans `eurelis/main`).

### Fixed

- **`LiteLLMBase._clean_conf`** — `model_type` (champ interne RAGFlow injecté dans `llm_setting` depuis l'upstream [#15141](https://github.com/infiniflow/ragflow/pull/15141)) n'était pas filtré avant l'appel API, causant une erreur `400 Bad Request` sur Bedrock (`extraneous key [model_type] is not permitted`). Fix : `gen_conf.pop("model_type", None)` dans `LiteLLMBase._clean_conf` (`rag/llm/chat_model.py`). PR upstream ouverte : [infiniflow/ragflow#15491](https://github.com/infiniflow/ragflow/pull/15491).

- **`BedrockCV`** — intégration PII masking + implémentation de `async_chat` et `async_chat_streamly` via `litellm.acompletion` (l'implémentation héritée de `Base` utilisait `self.async_client` non initialisé dans `BedrockCV`).

---

## [v0.25.6-eurelis.2-exp.1] - 2026-05-31 ⚠️ expérimental

Basé sur RAGFlow `v0.25.6` — branche `eurelis/feature/pii-masking` (non mergée dans `eurelis/main`).

### Added

- **PII Masking** — masquage automatique des données personnelles (PII) avant envoi aux LLM, via [Microsoft Presidio](https://github.com/microsoft/presidio) :
  - `rag/llm/pii_masking.py` — moteur Presidio : détection, anonymisation, réhydratation des réponses (`StreamingUnmasker`, `PiiAuditLogger`, `PiiMaskingEngine` singleton).
  - `rag/llm/chat_model.py` — hook dans `LiteLLMBase._construct_completion_args()` + réhydratation dans tous les callers (`async_chat`, `async_chat_streamly`, `async_chat_with_tools`, `async_chat_streamly_with_tools`).
  - `rag/llm/cv_model.py` — intégration dans `GeminiCV` (`async_chat` + `async_chat_streamly`) : masquage du contexte RAG (`system`) + de l'historique en un seul appel.
  - `api/ragflow_server.py` — initialisation `PiiMaskingEngine.initialize()` au démarrage.
  - `conf/llm_factories.json` — ajout de `gemini-3.5-flash::pii` (`image2text`) comme variante avec masquage.
  - `test/unit_test/rag/llm/test_pii_masking.py` — 41 tests unitaires.
  - `docs/eurelis/features/pii-masking.md` — documentation technique complète.

- **Fonctionnalités du moteur PII Masking :**
  - Détection par regex/checksum (EMAIL, PHONE, CREDIT_CARD, IBAN, IP) sans dépendance NER.
  - Détection contextuelle via spaCy NER (PERSON, LOCATION, DATE_TIME) — optionnelle, configurable par langue.
  - Actions `MASK` (remplacement par `<TYPE_N>`) et `BLOCK` (exception, requête bloquée).
  - Placeholders numérotés et cohérents entre messages : même valeur → même placeholder (`_SharedMaskingState`).
  - Réhydratation des réponses en mode streaming (sliding-window buffer, `StreamingUnmasker`).
  - Audit log configurable : niveau `summary` ou `detailed`, destination `app`/`file`/`both`, niveau INFO.
  - Champ `recognizer` dans l'audit log `detailed` (`SpacyRecognizer` vs `EmailRecognizer`, etc.).
  - Recognizers personnalisés via fichier YAML (pattern regex, deny-list, boosting contextuel).
  - Opt-in par modèle via suffix `::pii` (ex. `gemini-3.5-flash::pii`) ou ciblage par provider regex.
  - Mode "audit sans masquage" : `PII_AUDIT_LOG_ENABLED=true` + `PII_MASKING_ENABLED=false`.

- **Variables d'environnement ajoutées :** `PII_MASKING_ENABLED`, `PII_MASKING_PROVIDERS`, `PII_MASKING_ENTITIES`, `PII_MASKING_SCORE_THRESHOLD`, `PII_MASKING_SCORE_OVERRIDES`, `PII_MASKING_ROLES`, `PII_MASKING_LANGUAGES`, `PII_MASKING_NER`, `PII_MASKING_NER_MODEL_EN`, `PII_MASKING_NER_MODEL_FR`, `PII_MASKING_CUSTOM_RECOGNIZERS_FILE`, `PII_MASKING_STARTUP_FAIL`, `PII_AUDIT_LOG_ENABLED`, `PII_AUDIT_LOG_LEVEL`, `PII_AUDIT_LOG_DESTINATION`, `PII_AUDIT_LOG_FILE`.

- **Dépendances Python ajoutées :** `presidio-analyzer>=2.2.354`, `presidio-anonymizer>=2.2.354` (+ `en-core-web-sm` déjà présent via GraphRAG).

---

## [v0.25.6-eurelis.1] - 2026-05-30

Basé sur RAGFlow `v0.25.6`.

### Added

- **Gestion des équipes (admin)** — nouvelle feature `eurelis/group_work` :
  - `admin/server/routes.py` + `admin/server/services.py` — API admin pour la gestion des équipes : listing, ajout/suppression de membres, changement de rôle, validation d'invitation.
  - `web/src/pages/admin/teams.tsx` — page `/admin/teams` : liste des équipes avec compteur de membres.
  - `web/src/pages/admin/team-detail.tsx` — page `/admin/teams/:id` : détail d'une équipe et gestion de ses membres.
  - `web/src/pages/admin/user-own-team.tsx` — page `/admin/users/:id/team` : gestion des membres de l'équipe propre d'un utilisateur.
  - `web/src/pages/admin/user-team.tsx` — page `/admin/users/:id/members` : équipes auxquelles appartient un utilisateur.
  - `api/db/db_models.py` — champ `chat_permission` sur le modèle `Dialog` pour contrôler l'accès aux chats partagés.
  - `web/src/locales/eurelis/en.ts` + `fr.ts` — clés i18n Eurelis isolées de l'upstream.

### Changed

- Synchronisation upstream RAGFlow `v0.25.6` (43 commits intégrés, dont `feat(i18n): complete French translation` — notre contribution FR a été mergée dans l'upstream sous `50424df48`).
- `web/src/pages/admin/users.tsx` — refonte des boutons d'action : icônes distinctes (`LucideUsers` / `LucideLink`) pour les deux pages équipes, changement de mot de passe en première position.

### Fixed

- `web/src/components/llm-setting-items/next.tsx` — le paramètre *Creativity* du chat n'était pas sauvegardé (cherry-pick upstream PR #15243).
- `web/src/pages/agents/template-card.tsx` — descriptions des templates d'agent non affichées pour les langues non couvertes (`en`/`zh`/`de`) : fallback sur `'en'`, correction typo `hypens-auto` → `hyphens-auto`, ajout de `i18n.language` dans les dépendances du `useMemo` (PR upstream [#15370](https://github.com/infiniflow/ragflow/pull/15370)).

---

## [v0.25.4-eurelis.1] - 2026-05-17

Basé sur RAGFlow `v0.25.4`.

### Changed

- Synchronisation avec l'upstream RAGFlow `v0.25.4` (commit `86bcf9767`).

### Fixed

- `api/apps/restful_apis/chat_api.py` — suppression en cascade des fichiers uploadés en chat lors de la suppression d'une session. Les blobs orphelins dans le bucket MinIO `{user_id}-downloads` sont désormais nettoyés à la suppression de session.

---

## [v0.25.1-eurelis.3] - 2026-05-10

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

### Added

- `rag/llm/cv_model.py` — classe `BedrockCV` : implémentation `CvModel` pour le provider Bedrock via LiteLLM (préfixe `bedrock/`). Supporte les modes d'authentification AWS `access_key_secret`, `iam_role` et chaîne de credentials par défaut.
- `web/public/logo.svg` — remplacement du logo RAGFlow par le logo Eurelis avec dégradé (`#00253a` → `#cc007b` → `#ffb3d9`).

### Changed

- `web/src/layouts/components/header.tsx` — masquage des icônes Discord et GitHub dans la barre de navigation.
- `web/src/pages/home/banner.tsx`, `web/src/pages/next-search/ragflow-logo.tsx`, `web/src/pages/login-next/bg.tsx`, `web/tailwind.css` — alignement des couleurs de dégradé et de l'accent principal (`--accent-primary`) sur l'identité visuelle Eurelis.
- `api/db/joint_services/tenant_model_service.py` — accès direct aux attributs `.llm_name` / `.llm_factory` de `TenantLLM`, filtre `fid=` sur `LLMService.query`, logs debug à chaque étape du fallback IMAGE2TEXT→CHAT, normalisation de `model_type` à `image2text` après le fallback.
- `rag/llm/cv_model.py` — suppression du paramètre `base_url` inutilisé dans `BedrockCV.__init__`.
- `rag/nlp/search.py` — ajout d'un `logging.warning` lors de la détection d'un chunk parent manquant dans `retrieval_by_children`.
- `rag/advanced_rag/tree_structured_query_decomposition_retrieval.py` — passage d'un message descriptif à `logging.exception` au lieu de l'objet exception.

### Fixed

- `api/db/joint_services/tenant_model_service.py` — fallback IMAGE2TEXT→CHAT : un modèle déclaré `model_type: "chat"` avec le tag `IMAGE2TEXT` peut désormais être résolu lors de l'ingestion PDF parser.
- `api/apps/llm_app.py` — régression upstream `050113482` : la clé API Bedrock assemblée depuis les champs séparés était écrasée par la logique "existing key". Fix : écriture dans `req["api_key"]` avant la vérification.

---

## [v0.25.1-eurelis.3-exp.5] - 2026-05-10

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Added

- `web/public/logo.svg` — remplacement du logo RAGFlow par un dégradé aux couleurs Eurelis (`#00253a` → `#cc007b` → `#ffb3d9`).

### Changed

- `web/src/layouts/components/header.tsx` — masquage des icônes Discord et GitHub dans la barre de navigation (commentées).
- `api/db/joint_services/tenant_model_service.py` — accès direct aux attributs `.llm_name` / `.llm_factory` de `TenantLLM` (suppression du `.to_dict()`), filtre `fid=` sur `LLMService.query`, correspondance exacte du tag `IMAGE2TEXT`, logs debug à chaque étape du fallback. (amélioration de la PR upstream #14704)
- `rag/llm/cv_model.py` — suppression du paramètre `base_url` inutilisé dans `BedrockCV.__init__`. (amélioration de la PR upstream #14705)
- `rag/nlp/search.py` — ajout d'un `logging.warning` lors de la détection d'un chunk parent manquant dans `retrieval_by_children`. (amélioration de la PR upstream #14556)
- `rag/advanced_rag/tree_structured_query_decomposition_retrieval.py` — passage d'un message descriptif à `logging.exception` au lieu de l'objet exception. (amélioration de la PR upstream #13942)

---

## [v0.25.1-eurelis.3-exp.4] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Fixed

- `api/apps/llm_app.py` — régression upstream `050113482` : la clé API Bedrock assemblée depuis les champs séparés (`bedrock_ak`, `bedrock_sk`...) était écrasée par la logique "existing key" car `req["api_key"]` était `None`. Fix : écriture dans `req["api_key"]` avant la vérification, cohérent avec le pattern Tencent Cloud.

---

## [v0.25.1-eurelis.3-exp.3] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Added

- `rag/llm/cv_model.py` — classe `BedrockCV` : implémentation `CvModel` pour le provider Bedrock via LiteLLM (préfixe `bedrock/`). Supporte les modes d'authentification AWS `access_key_secret`, `iam_role` et chaîne de credentials par défaut. Résout l'erreur `'LiteLLMBase' object has no attribute 'describe_with_prompt'` lors de l'ingestion PDF parser avec un modèle Bedrock.

---

## [v0.25.1-eurelis.3-exp.2] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Fixed

- `api/db/joint_services/tenant_model_service.py` — normalisation de `model_type` à `image2text` après le fallback IMAGE2TEXT→CHAT : le caller (`tenant_llm_service`) instancie désormais correctement `CvModel` au lieu de `ChatModel`, résolvant l'erreur `'LiteLLMBase' object has no attribute 'describe_with_prompt'` lors de l'ingestion PDF parser.

---

## [v0.25.1-eurelis.3-exp.1] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Fixed

- `api/db/joint_services/tenant_model_service.py` — fallback IMAGE2TEXT → CHAT manquant : un modèle déclaré `model_type: "chat"` avec le tag `IMAGE2TEXT` peut désormais être résolu lors de l'ingestion PDF parser. Le fallback n'est accordé qu'après vérification du tag `IMAGE2TEXT` dans la table `llm` pour garantir la capacité vision.

---

## [v0.25.1-eurelis.2] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

### Changed

- Synchronisation upstream RAGFlow post-`v0.25.1` (tag `nightly`, 96 commits intégrés)

---

## [v0.25.1-eurelis.1] - 2026-05-02

Basé sur RAGFlow `v0.25.1`.

### Added

- Dépendance `zhipuai>=2.0.1` pour le support des modèles ZhipuAI (`cb70f7362`)

### Changed

- Amélioration de `tree_structured_query_decomposition_retrieval` : meilleure gestion du total et des cas limites (`3e2486ac6`)

### Fixed

- `rag/nlp/search.py` — `retrieval_by_children` : guard `None` sur le chunk parent pour éviter un `TypeError` sur les enfants orphelins — repli sur les chunks enfants en cas de parent absent de l'index (`188f825a9`)

---

## [v0.25.0-eurelis.3-exp.1] - 2026-05-02

> **Pré-release expérimentale** de `v0.25.0-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

Contient toutes les modifications de `v0.25.0-eurelis.2`, plus :

### Fixed

- `rag/nlp/search.py` — `retrieval_by_children` : guard `None` sur le chunk parent pour éviter un `TypeError` sur les enfants orphelins — repli sur les chunks enfants en cas de parent absent de l'index (`2eca7d7e2`)

---

## [v0.25.0-eurelis.2] - 2026-05-02

Basé sur RAGFlow `v0.25.0` (synchronisé avec upstream `v0.25.1`).

### Added

- Dépendance `zhipuai>=2.0.1` pour le support des modèles ZhipuAI (`111392888`)

### Changed

- Amélioration de la décomposition de requêtes en arbre (`tree_structured_query_decomposition_retrieval`) : meilleure gestion du total et des cas limites (`2eca7d7e2`)
- Synchronisation upstream RAGFlow `v0.25.1`

---

## [v0.25.0-eurelis.1] - 2026-04-21

Basé sur RAGFlow `v0.25.0`.

---

## [v0.24.0-eurelis.1] - 2026-04-06

Basé sur RAGFlow `v0.24.0`.

### Fixed

- Gestion du total dans la récupération d'informations — `tree_structured_query_decomposition_retrieval.py` (`9bba089ab`)
- Gestion des exceptions dans la méthode `research` et amélioration de la vérification de la suffisance (`33401e9e1`)
- Correction de l'initialisation de `kbinfos` dans `_retrieve_information` (`a0b7ce569`)

---

<!-- Template pour les prochaines releases :

## [vX.Y.Z-eurelis.N] - YYYY-MM-DD

Basé sur RAGFlow `vX.Y.Z`.

### Added
### Changed
### Fixed
### Removed

-->
