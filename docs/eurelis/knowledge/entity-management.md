# Gestion des Entités : Ingestion → Recherche RAG

## Architecture globale

RAGFlow maintient **deux pipelines parallèles** :

1. **Retrieval standard** — chunks texte, toujours actif
2. **GraphRAG** — entités + relations, optionnel par Knowledge Base

---

## 1. Extraction (ingestion)

**Extracteur principal : LLM-based** (pas de NER classique)

- `rag/graphrag/general/graph_extractor.py` — `GraphExtractor._process_single_content()`
- Chaque chunk est envoyé au LLM avec un prompt structuré
- Le LLM retourne un format délimité :
  ```
  ("entity"<|>NOM<|>TYPE<|>DESCRIPTION)
  ("relationship"<|>SOURCE<|>CIBLE<|>DESCRIPTION<|>POIDS)
  ```
- Jusqu'à **2 gleanings** (passes supplémentaires) pour maximiser l'extraction

**Types d'entités par défaut** (`rag/graphrag/general/extractor.py:46`) :
```python
["organization", "person", "geo", "event", "category"]
```
Personnalisables par KB.

---

## 2. Pipeline complet d'ingestion (GraphRAG)

Orchestré par `rag/graphrag/general/index.py` → `run_graphrag_for_kb()` :

```
Chunks du document
  ↓ generate_subgraph()    # Extraction LLM → NetworkX Graph
  ↓ merge_subgraph()       # Fusion avec le graphe global (+ PageRank)
  ↓ resolve_entities()     # Déduplication (editdistance + LLM)  [optionnel]
  ↓ extract_community()    # Leiden clustering + résumés LLM     [optionnel]
  ↓ set_graph()            # Indexation dans doc_store
```

---

## 3. Stockage des entités

Les entités et relations sont des **chunks normaux** dans le doc_store (Elasticsearch/Infinity), différenciés par `knowledge_graph_kwd` :

| Valeur | Contenu |
|--------|---------|
| `"entity"` | Un nœud du graphe |
| `"relation"` | Une arête |
| `"graph"` | Graphe NetworkX JSON complet |
| `"community_report"` | Résumé de communauté |

**Structure d'un chunk entité** (`rag/graphrag/utils.py:300`) :
```python
{
  "entity_kwd": "APPLE INC",
  "entity_type_kwd": "ORGANIZATION",
  "knowledge_graph_kwd": "entity",
  "content_with_weight": {"entity_type": ..., "description": ..., "source_id": [...]},
  "rank_flt": 0.042,           # PageRank
  "q_1536_vec": [...],         # Embedding du nom
  "n_hop_with_weight": [...]   # Voisins jusqu'à N-hops
}
```

**Structure d'un chunk relation** (`rag/graphrag/utils.py:354`) :
```python
{
  "from_entity_kwd": "APPLE INC",
  "to_entity_kwd": "TIM COOK",
  "knowledge_graph_kwd": "relation",
  "content_with_weight": {"description": ..., "keywords": [...], "source_id": [...]},
  "weight_int": 3,             # Force de la relation
  "weight_flt": 0.76,
  "q_1536_vec": [...]          # Embedding de "source->target: description"
}
```

---

## 4. Retrieval RAG avec entités

Classe `KGSearch` — `rag/graphrag/search.py:retrieval()` :

1. **Query rewrite** (`:46`) — LLM extrait types et entités de la requête
2. **Recherche dense** sur entités par embedding (`get_relevant_ents_by_keywords()`)
3. **Filtre par type** + ranking par PageRank (`get_relevant_ents_by_types()`)
4. **Recherche sur relations** par embedding (`get_relevant_relations_by_txt()`)
5. **Traversée N-hops** — cumul de score : `sim / (2 + i)` par niveau
6. **Score final** : `similarity × pagerank`
7. **Output** formaté en CSV pour le contexte LLM (entités + relations + community reports)

**Format de sortie vers le LLM** :
```markdown
---- Entities ----
Entity,Score,Description
APPLE INC,0.87,"Apple Inc is a technology company..."

---- Relations ----
From Entity,To Entity,Score,Description
APPLE INC,TIM COOK,0.76,"Tim Cook is CEO of Apple Inc"

---- Community Report ----
1. Community Title
## Content
...
```

---

## 5. Résolution d'entités (déduplication)

`rag/graphrag/entity_resolution.py` — `EntityResolution.__call__()` :

1. Détecte les paires de nœuds similaires :
   - **English** : editdistance
   - **Autres langues** : overlap de tokens
   - Filtre : présence de digits différents → non-similaire
2. Batch LLM pour vérifier si les paires sont vraiment identiques
3. Fusionne les nœuds confirmés : description + source_id + edges
4. Recalcule le PageRank

---

## 6. Community Detection (optionnel)

`rag/graphrag/general/index.py` — `extract_community()` :

- Algorithme de **Leiden** pour détecter les communautés
- LLM génère un rapport pour chaque communauté
- Indexés avec `knowledge_graph_kwd="community_report"`
- Inclus dans le contexte du retrieval final

---

## 7. Flux de données complet

```
Document
  ↓
Parser (deepdoc/mineru)
  ↓
Chunks standard ──────────────────────────→ Index (retrieval standard)
  ↓
GraphRAG (optionnel)
  ↓
GraphExtractor.LLM
  ├─ entity_name (UPPERCASE)
  ├─ entity_type (from entity_types config)
  ├─ entity_description
  └─ source_id = [doc_id]
  ↓
Subgraph NetworkX
  ↓
merge_subgraph() → graph global + PageRank
  ↓
resolve_entities() [optionnel] → déduplication
  ↓
extract_community() [optionnel] → rapports
  ↓
set_graph() → indexation doc_store
  ├─ chunk par entité (entity_kwd, embedding, rank_flt)
  └─ chunk par relation (from/to_entity_kwd, embedding)
  ↓
RETRIEVAL
  query → query_rewrite() → types + entités
         → dense search (embeddings)
         → filter par type + PageRank
         → N-hop traversal
         → score = similarity × pagerank
         → contexte LLM (CSV)
```

---

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `rag/graphrag/general/graph_extractor.py` | Extraction LLM → entités/relations |
| `rag/graphrag/general/extractor.py` | Orchestration extraction + gleanings |
| `rag/graphrag/general/index.py` | Pipeline complet GraphRAG |
| `rag/graphrag/entity_resolution.py` | Déduplication entités |
| `rag/graphrag/utils.py` | Indexation + conversion chunks |
| `rag/graphrag/search.py` | Retrieval GraphRAG |
| `rag/svr/task_executor.py:1190` | Point d'entrée depuis le task executor |

---

## Points clés à retenir

1. **Extraction LLM-only** : pas de NER classique, tout passe par le modèle de langage avec un format structuré
2. **Stockage unifié** : entités et relations sont des chunks comme les autres dans le doc_store, distingués par `knowledge_graph_kwd`
3. **Recherche hybride** : dense (embedding) + filtre type + boost PageRank + traversée N-hops
4. **Déduplication intelligente** : textuelle (editdistance) puis validation LLM
5. **Community detection** : optionnel, ajoute des résumés de haut niveau dans le contexte RAG
6. **Activation** : GraphRAG est optionnel et configurable par KB (`with_resolution`, `with_community`, `entity_types`)
