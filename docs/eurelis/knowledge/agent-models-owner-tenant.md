---
title: "Agents canvas : modèles du propriétaire, fichiers et sessions de l'appelant"
type: knowledge
status: reference
date: 2026-10-11
---

# Agents canvas : modèles du propriétaire, fichiers et sessions de l'appelant

Depuis `v0.26.3-eurelis.13` (AILAB-43), les modèles utilisés par un agent canvas sont
résolus sur le tenant du **propriétaire du canvas** (`user_canvas.user_id`), quel que soit
l'utilisateur qui l'exécute. C'est l'alignement sur les assistants de chat, qui utilisent
depuis toujours les modèles du propriétaire (`dialog.tenant_id`).

> **En bref.** Un membre d'équipe sans aucun fournisseur de modèles peut exécuter un agent
> partagé « équipe » : ce sont les modèles et les clés du propriétaire qui servent. Les fichiers
> déposés et générés, les sessions et l'attribution de l'usage restent chez l'appelant.
> `EURELIS_AGENT_MODELS_FROM_OWNER=false` rétablit le comportement upstream.

---

## 1. Le comportement upstream

L'upstream construit `Canvas(dsl, tenant_id, …)` avec le tenant de l'**appelant**, et chaque
composant résout son modèle via `self._canvas.get_tenant_id()`. Un utilisateur sans fournisseur
(cas des comptes provisionnés par le Shield) échoue dès `POST /api/v1/agents/{id}/sessions` :

```
LookupError: Provider OpenAI not found for model gpt-4.1@OpenAI.
```

L'échec survient à la création de session, avant toute exécution : `LLM` et `Agent` résolvent
leur modèle **dans leur constructeur**, pendant le chargement du DSL.

## 2. Ce qui est résolu sur quel tenant

| Ressource | Tenant | Où |
|---|---|---|
| Chat / image2text des composants `LLM`, `Agent`, `Categorize`, `Browser` | propriétaire du canvas | `agent/component/*.py` → `get_model_tenant_id()` |
| Synthèse vocale (`Message` en lecture auto) | propriétaire du canvas | `agent/canvas.py` |
| Chat de l'outil `Retrieval` (filtre de métadonnées auto, `toc_enhance`, `use_kg`) | propriétaire du canvas | `agent/tools/retrieval.py` |
| Embedding de l'outil `Retrieval` | tenant de la base (`kbs[0].tenant_id`) | `agent/tools/retrieval.py` (comme les assistants et le rerank) |
| Rerank de l'outil `Retrieval` | tenant de la base | inchangé |
| Mémoire | tenant de la mémoire | inchangé |
| Fichiers déposés (`POST /agents/{id}/upload`), relus via `created_by` | appelant | inchangé |
| Pièces générées (`Message`, `DocsGenerator`, `ExcelProcessor`), téléchargées avec la clé de l'appelant | appelant | inchangé |
| Sessions (`API4Conversation.user_id`, `round`/`tokens`/`duration`) | appelant | inchangé |
| `sys.user_id` et attribution `usage_log` Eurelis | appelant | inchangé |
| Recherche d'une base par **nom** dans `Retrieval` | appelant | inchangé |
| Pipelines d'ingestion (`Pipeline`, `rag/flow/`) et `PipelineChunker` | appelant | inchangé |

## 3. Mécanisme

- `Graph.get_model_tenant_id()` renvoie `_tenant_id` (appelant) : les pipelines d'ingestion
  gardent le comportement upstream.
- `Canvas.get_model_tenant_id()` délègue à `agent/eurelis_model_tenant.py::resolve_model_tenant_id`,
  qui lit le propriétaire via `UserCanvasService.get_by_id(canvas_id)` ; le résultat est mis en
  cache sur l'instance (une requête par canvas).
- `Canvas._id` est affecté **avant** `Graph.__init__` → `load()` : les constructeurs des
  composants y ont donc déjà accès.
- Repli sur l'appelant : pas de `canvas_id`, canvas introuvable, erreur de lecture, interrupteur coupé.
- Le propriétaire qui exécute son propre agent (éditeur, brouillon) n'observe aucun changement.

## 4. Interrupteur

| Variable | Défaut | Effet |
|---|---|---|
| `EURELIS_AGENT_MODELS_FROM_OWNER` | `true` | `false` / `0` / `no` / `off` : modèles **et** embedding de `Retrieval` repassent sur l'appelant (upstream) |

Lue à chaque construction de canvas : un redémarrage des conteneurs suffit, sans redéploiement de code.

## 5. Conséquences à connaître

- **Consommation** : les tokens sont consommés sur les clés du propriétaire et
  `TenantLLM.used_tokens` est incrémenté sur l'instance du propriétaire, comme pour un assistant
  partagé. Les statistiques `usage_log` Eurelis restent ventilées par appelant (`sys.user_id`).
- **Bases de connaissances** : rien de nouveau n'est ouvert. L'outil `Retrieval` lisait déjà
  les bases par identifiant sans contrôle de tenant ; seul l'embedding échouait chez un membre
  sans modèle.
- **Membre ayant ses propres fournisseurs** : il utilise désormais les modèles du propriétaire
  lorsqu'il exécute l'agent d'un autre.
- **Hors périmètre** : un parsing de fichier déposé qui exige un VLM (image2text) reste résolu
  sous l'appelant (`FileService.parse` → `current_user`). Il en va de même pour `PipelineChunker`.

## 6. Tests

- `test/eurelis/unit/test_agent_model_tenant.py` : propriétaire, une seule résolution, disponibilité
  pendant `load()`, replis, interrupteur, `Graph` inchangé.
- `test/eurelis/eurelis_fixes/test_agent_models_owner_tenant_e2e.py` : un membre sans fournisseur
  exécute un agent Begin(fichier) → LLM → Message du propriétaire, dépose un fichier relu par l'agent,
  télécharge la pièce générée ; rattachement de session inchangé. Rouge sur `v0.26.3-eurelis.12`.
