---
title: "Documentation Eurelis — RAGFlow Fork"
type: knowledge
status: reference
date: 2026-06-28
---

# Documentation Eurelis — RAGFlow Fork

Index de navigation de la documentation propre au fork Eurelis de RAGFlow.
Chaque document porte un frontmatter YAML (`title`, `type`, `status`, `date`…) ;
les documents `feature` et `spec` portent en plus une date `reviewed` indiquant leur dernière revalidation contre le code.

**Conventions de `status` :**

| Statut | Signification |
|---|---|
| `implemented` | Fonctionnalité / spec présente dans le code et validée |
| `partial` | Partiellement implémentée (reste du travail identifié) |
| `proposed` | Piste / spec rédigée, non implémentée |
| `analysis` | Document d'analyse ou de conception (pas un livrable de code) |
| `reference` | Documentation technique de référence |
| `published` | Article de blog |

---

## 📁 Arborescence

```
docs/eurelis/
├── README.md            ← cet index
├── blog/                Articles de blog (série PII / Presidio)
├── features/
│   ├── done/            Fonctionnalités livrées + correctifs + analyses abouties
│   └── roadmap/         Pistes et specs non encore implémentées
├── guidelines/          Procédures de gestion du fork (rebase, release, patchs)
├── knowledge/           Documentation technique de référence
│   └── api-examples/    Référence API + exemples de réponses JSON
├── specs/
│   └── usage-stats/     Specs du domaine « statistiques de consommation »
├── notebooks/           Notebooks de démo / benchmark (Presidio, NER)
└── sync-upstream/       Journaux de synchronisation upstream (locaux, non versionnés)
```

---

## 📰 blog/

Série d'articles sur le masquage des données personnelles (PII) dans un pipeline RAG.
Voir [blog/README.md](./blog/README.md) pour l'index détaillé.

| Document | Statut |
|---|---|
| [01 — Introduction au PII masking avec Presidio](./blog/01-introduction-pii-masking-presidio.md) | `published` |
| [02 — Mise en œuvre de Presidio dans un RAG](./blog/02-mise-en-oeuvre-presidio-rag.md) | `published` |
| [03 — Benchmark NER spaCy × Presidio](./blog/03-benchmark-ner-spacy-presidio.md) | `published` |

---

## ✅ features/done/

Fonctionnalités livrées, correctifs et analyses abouties.

| Document | Statut |
|---|---|
| [Supervision admin des modèles par tenant](./features/done/admin-model-supervision.md) | `implemented` |
| [Statistiques de consommation par utilisateur](./features/done/user-statistics-and-consumption.md) | `implemented` |
| [Gestion des équipes (group_work)](./features/done/group-work.md) | `implemented` |
| [PII Masking (Presidio)](./features/done/pii-masking.md) | `implemented` |
| [Fix — clé API Bedrock écrasée dans `add_llm`](./features/done/fix-bedrock-add-llm-api-key-override.md) | `implemented` |
| [Fix — fallback IMAGE2TEXT → CHAT du parser PDF](./features/done/fix-image2text-chat-fallback.md) | `implemented` |
| [Partage des chats (équipe)](./features/done/chat-sharing-analysis.md) | `implemented` |
| [Provisionnement des équipes via Keycloak](./features/done/keycloak-team-provisioning.md) | `partial` |
| [Analyse — Traductions françaises manquantes](./features/done/missing-fr-translations.md) | `analysis` |

---

## 🛣️ features/roadmap/

Pistes et specs non encore implémentées.

| Document | Statut |
|---|---|
| [Internationalisation des templates d'agent](./features/roadmap/agent-template-i18n.md) | `partial` |
| [Extension des tags aux discussions et recherches](./features/roadmap/agent-tags-extension-chat-search.md) | `proposed` |
| [Contrôle de la profondeur Deep Research](./features/roadmap/deep-research-depth-control.md) | `proposed` |
| [Intégration sessions / utilisateurs dans Langfuse](./features/roadmap/langfuse-session-user-integration.md) | `proposed` |
| [Analyse — Partage des modèles LLM](./features/roadmap/model-sharing-analysis.md) | `analysis` |

---

## 📐 specs/usage-stats/

Specs du domaine « statistiques de consommation » (table `usage_log`, API, intégration Shield).

| Document | Statut |
|---|---|
| [Table `usage_log` (append-only)](./specs/usage-stats/usage-log-table.md) | `implemented` |
| [API statistiques de consommation & dashboard admin](./specs/usage-stats/usage-stats-api.md) | `implemented` |
| [API statistiques de consommation (utilisateur)](./specs/usage-stats/api-usage-stats-user.md) | `implemented` |
| [Historisation des tokens d'ingestion](./specs/usage-stats/usage-stats-ingestion.md) | `implemented` |
| [Shield — intégration token usage & visibilité stats](./specs/usage-stats/shield-token-usage-stats.md) | `implemented` |

---

## 📖 guidelines/

Procédures de gestion du fork.

| Document | Statut |
|---|---|
| [Gestion du fork (remotes, branches, rebase)](./guidelines/fork-management.md) | `reference` |
| [Gestion de `conf/llm_factories.patch.json`](./guidelines/llm-factories-patch.md) | `reference` |
| [Release et build des images](./guidelines/release-management.md) | `reference` |

---

## 🧠 knowledge/

Documentation technique de référence.

| Document | Statut |
|---|---|
| [Initialisation de l'utilisateur admin par défaut](./knowledge/admin-user-init.md) | `reference` |
| [Configuration des variables d'une Chat App](./knowledge/chat-app-variable-configuration.md) | `reference` |
| [Endpoints API Chat et pièces jointes](./knowledge/chat-endpoints-and-attachments.md) | `reference` |
| [Gestion des entités (ingestion → recherche)](./knowledge/entity-management.md) | `reference` |
| [Génération du Knowledge Graph](./knowledge/knowledge-graph-generation.md) | `reference` |
| [Configuration des modèles LLM par tenant](./knowledge/llm-default-configuration.md) | `reference` |
| [Gestion des métadonnées (ingestion → recherche)](./knowledge/metadata-management.md) | `reference` |
| [Cycle de chargement de `service_conf.yaml`](./knowledge/service-conf-loading-cycle.md) | `reference` |
| [Intégration Tavily (recherche web)](./knowledge/tavily-integration.md) | `reference` |
| [Gestion des utilisateurs et administration](./knowledge/user-and-admin-management.md) | `reference` |
| [Gestion des tags de version](./knowledge/version-tag-management.md) | `reference` |
| [Réorganisation du workspace Eurelis](./knowledge/workspace-reorganisation.md) | `reference` |
| [Référence API `chunks` / `doc_aggs`](./knowledge/api-examples/chunks-and-doc-aggs-api-reference.md) | `reference` |

`knowledge/api-examples/` contient aussi deux exemples de réponses JSON
([RAG](./knowledge/api-examples/chunks-and-doc-aggs-api-reference-rag.json) ·
[web search](./knowledge/api-examples/chunks-and-doc-aggs-api-reference-websearch.json)).

---

## 📓 notebooks/

Notebooks de démonstration et de benchmark associés à la série blog Presidio.

- `notebooks/presidio_demo.ipynb` — démonstration du masquage PII.
- `notebooks/presidio_ner_benchmark.ipynb` — benchmark des modèles NER spaCy.

---

## 🔄 sync-upstream/

Journaux des opérations de synchronisation depuis l'upstream `infiniflow/ragflow`.
Ces fichiers sont **locaux et non versionnés** (`*.md` ignoré dans ce dossier via `.gitignore`).
