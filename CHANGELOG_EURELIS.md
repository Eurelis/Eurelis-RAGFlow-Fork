# Changelog Eurelis

Historique des modifications spécifiques au fork Eurelis de [RAGFlow](https://github.com/infiniflow/ragflow).

---

## [v0.24.0-eurelis.1] - 2026-04-06

Basé sur RAGFlow `v0.24.0`.

### Added

- Analyse du partage des Chats et des Modèles LLM dans RAGFlow (`d4c75528b`)
- Configuration de markdownlint (`7ab4d1d39`)

### Fixed

- Gestion du total dans la récupération d'informations — `tree_structured_query_decomposition_retrieval.py` (`9bba089ab`)
- Gestion des exceptions dans la méthode `research` et amélioration de la vérification de la suffisance (`33401e9e1`)
- Correction de l'initialisation de `kbinfos` dans `_retrieve_information` (`a0b7ce569`)
- Correction d'un commentaire (`f104f0eb2`)
- Correction du build (`91b58d634`)

---

## [v0.25.0-eurelis.1] - 2026-04-21

Basé sur RAGFlow `v0.25.0`.

### Added

- Guide complet sur la gestion des forks Eurelis (`24e617920`)
- Documentation pour la commande `/sync-upstream` avec processus détaillé, tags de sauvegarde et rapport final (`2696386d6`, `e27e2fc91`, `6b88d5054`, `a839c1071`)
- Documentation pour la commande `/build-and-publish` (`1246bea5a`)
- Documentation sur la relation `chunks` / `doc_aggs` dans l'API Chat, avec mécanisme de citation (`2d075d8cc`, `6adf5798f`)
- Documentation pour l'intégration de Tavily dans le pipeline RAG (`775b8266d`)
- Documents d'analyse pour les releases Eurelis (`ad95616bc`)
- Initialisation du CHANGELOG Eurelis (`4d61853d6`)

---

<!-- Template pour les prochaines releases :

## [vX.Y.Z-eurelis.N] - YYYY-MM-DD

Basé sur RAGFlow `vX.Y.Z`.

### Added
### Changed
### Fixed
### Removed

-->
