# Changelog Eurelis

Historique des modifications spécifiques au fork Eurelis de [RAGFlow](https://github.com/infiniflow/ragflow).

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
