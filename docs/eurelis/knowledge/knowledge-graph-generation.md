# Générer le Knowledge Graph

## Via l'interface

### Étape 1 — Configurer (optionnel)

Aller dans l'onglet **Configuration** du dataset (`/dataset/dataset-setting/:id`), section **Global Index** :

| Champ | Options | Défaut |
|-------|---------|--------|
| **Global Index Model** | Sélecteur LLM | — |
| **Entity Types** | Tags editables | organization, person, geo, event, category |
| **Method** | `light` / `general` | `light` |
| **Entity Resolution** | Toggle | off |
| **Community Reports** | Toggle | off |

> `light` = prompts LightRAG (moins de tokens), `general` = prompts Microsoft GraphRAG (plus complet)

Cliquer **Save** pour sauvegarder (`PUT /api/v1/datasets/<id>`).

Composants : `web/src/components/parse-configuration/graph-rag-form-fields.tsx`

---

### Étape 2 — Lancer la génération

Aller dans l'onglet **Files** (`/dataset/dataset/:id`) :

1. Cliquer le bouton **Generate** (icône baguette magique, en haut à droite)
   — désactivé si aucun document n'a été ingéré (`chunk_count == 0`)
2. Dans le menu déroulant, choisir **Knowledge Graph**
3. Une barre de progression s'affiche

Composant : `web/src/pages/dataset/dataset/generate-button/generate.tsx`
Hook : `web/src/pages/dataset/dataset/generate-button/hook.ts` — `useDatasetGenerate()`

---

### Étape 3 — Visualiser le graphe

Une fois la génération terminée, un onglet **Knowledge Graph** apparaît automatiquement dans la sidebar (visible seulement si `routerData?.graph` n'est pas vide).

Page : `/dataset/knowledge-graph/:id` — graphe interactif `<ForceGraph>` avec nœuds classés par PageRank.

Composant : `web/src/pages/dataset/knowledge-graph/index.tsx`

---

## Via l'API REST

**Lancer** la génération :
```http
POST /api/v1/datasets/<dataset_id>/index?type=graph
Authorization: Bearer <token>
```

**Suivre** la progression :
```http
GET /api/v1/datasets/<dataset_id>/index?type=graph
```

**Consulter** le graphe généré :
```http
GET /api/v1/datasets/<dataset_id>/graph
```

**Supprimer** le graphe :
```http
DELETE /api/v1/datasets/<dataset_id>/graph
```

---

## Configuration via l'API

Configurer le `parser_config` avant de lancer (`PUT /api/v1/datasets/<dataset_id>`) :

```json
{
  "parser_config": {
    "graphrag": {
      "use_graphrag": true,
      "method": "light",
      "entity_types": ["organization", "person", "geo", "event", "category"],
      "resolution": false,
      "community": false
    }
  }
}
```

| Option | Défaut | Effet |
|--------|--------|-------|
| `method` | `"light"` | `"light"` = LightKGExt (rapide), `"general"` = GraphExtractor complet |
| `entity_types` | 5 types | Types d'entités à extraire |
| `resolution` | `false` | Déduplication LLM-assisted des entités |
| `community` | `false` | Détection de communautés Leiden + résumés LLM |

---

## Prérequis

- Les documents du dataset doivent être **déjà ingérés** (chunks standard indexés)
- Un **modèle LLM** doit être configuré sur le tenant
- Un **modèle d'embedding** doit être disponible

---

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `web/src/pages/dataset/dataset/generate-button/generate.tsx` | Bouton Generate + menu dropdown |
| `web/src/pages/dataset/dataset/generate-button/hook.ts` | Hook `useDatasetGenerate()` |
| `web/src/components/parse-configuration/graph-rag-form-fields.tsx` | Formulaire de configuration GraphRAG |
| `web/src/pages/dataset/knowledge-graph/index.tsx` | Page de visualisation du graphe |
| `web/src/pages/dataset/sidebar/index.tsx` | Affichage conditionnel de l'onglet Knowledge Graph |
| `web/src/services/knowledge-service.ts` | Service `runIndex()` |
| `api/apps/restful_apis/dataset_api.py:561` | Route `POST /datasets/<id>/index` |
| `api/apps/services/dataset_api_service.py` | Logique `run_index()` |
| `rag/svr/task_executor.py:1165` | Exécution de la tâche GraphRAG |
