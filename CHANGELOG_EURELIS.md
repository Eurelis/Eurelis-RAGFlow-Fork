# Changelog Eurelis

Historique des modifications spécifiques au fork Eurelis de [RAGFlow](https://github.com/infiniflow/ragflow).

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
