# Gestion des Métadonnées : Ingestion → Recherche RAG

## Architecture globale

Les métadonnées opèrent à **deux niveaux distincts** :

1. **Niveau chunk** — positions PDF, type de document → stockées dans le doc_store principal
2. **Niveau document** — métadonnées agrégées (auteur, catégorie, date...) → stockées dans un index séparé `ragflow_doc_meta_{tenant_id}`

---

## 1. Extraction pendant l'ingestion

**Point d'entrée** : `rag/svr/task_executor.py:423`

```python
if task["parser_config"].get("enable_metadata", False):
    metadata_conf   = task["parser_config"].get("metadata", [])       # schéma custom
    built_in_fields = task["parser_config"].get("built_in_metadata", [])
```

### Deux sources de métadonnées

| Source | Champs | Mécanisme |
|--------|--------|-----------|
| **Natives (PDF)** | page, position `[left,right,top,bottom]`, `doc_type_kwd` | `rag/flow/parser/pdf_chunk_metadata.py` |
| **Extraites par LLM** | auteur, titre, date, catégorie, mots-clés, + champs custom | `gen_metadata()` via prompt `rag/prompts/meta_data.md` |

### Schéma custom (défini par l'utilisateur)

```json
[
  { "key": "author",   "description": "..." },
  { "key": "category", "enum": ["Technical", "Legal", "HR"] }
]
```

Converti en JSON Schema puis envoyé au LLM avec le contenu du chunk.

### Règles du prompt d'extraction (`rag/prompts/meta_data.md`)

- Evidence stricte : extrait uniquement ce qui est explicitement mentionné
- Enum : si fourni, la valeur DOIT être dans la liste
- Zéro hallucination

### Stockage (`api/db/services/doc_metadata_service.py`)

```
Index ES/Infinity : ragflow_doc_meta_{tenant_id}
{
  "id":          "doc_123",
  "kb_id":       "kb_456",
  "meta_fields": { "author": "Alice", "category": "Tech", "date": "2025-05-03" }
}
```

---

## 2. Exploitation pendant la recherche

**Point d'entrée** : `api/db/services/dialog_service.py:1434`

```python
if meta_data_filter:
    metas   = DocMetadataService.get_flatted_meta_by_kbs(kb_ids)
    doc_ids = await apply_meta_data_filter(meta_data_filter, metas, question, chat_mdl, doc_ids)
```

Les `doc_ids` filtrés **restreignent l'espace de recherche** avant la recherche vectorielle/keyword.

### Trois modes de filtrage (`common/metadata_utils.py:166`)

| Mode | Comportement |
|------|-------------|
| `auto` | LLM analyse la question + toutes les métadonnées disponibles → génère les conditions |
| `semi_auto` | LLM filtre sur un sous-ensemble de champs choisis par l'utilisateur |
| `manual` | Conditions explicites `{key, op, value}` définies par l'utilisateur |

### 18 opérateurs supportés

```
Comparaison : =  ≠  >  <  ≥  ≤
Texte       : contains  not contains  start with  end with  in  not in
Null        : empty  not empty
Dates       : YYYY-MM-DD + opérateurs de comparaison
```

### Exemple de filtre manuel

```json
{
  "method": "manual",
  "logic": "and",
  "manual": [
    { "key": "date",     "op": "≥", "value": "2025-01-01" },
    { "key": "category", "op": "=", "value": "Technical"  }
  ]
}
```

### Génération automatique de filtre (`rag/prompts/meta_filter.md`)

- Input : structure des métadonnées plates `{field: {value: [doc_ids]}}` + question utilisateur
- Output : `{conditions: [...], logic: "and|or"}`

---

## 3. Flux complet

```
Document
  ↓ Parser (deepdoc)
Chunks + positions PDF  →  doc_store principal (ragflow_{kb_id})
  ↓ IF enable_metadata
  gen_metadata() [LLM] → {key: value} par chunk
  ↓ Agrégation par document
  ragflow_doc_meta_{tenant_id}
       │
       │ (at retrieval time)
  get_flatted_meta_by_kbs()
  → {field: {value: [doc_ids]}}
       ↓
  apply_meta_data_filter()   ← mode auto / semi_auto / manual
  → doc_ids filtrés
       ↓
  retriever.retrieval(doc_ids=filtered)
  → vector + keyword search restreints
       ↓
  Top-K chunks → contexte LLM
```

---

## 4. Configuration dans un Dialog (Chat)

Champ `meta_data_filter` sur le modèle `Dialog` (`api/db/db_models.py:978`) :

```json
{
  "method":    "auto",
  "logic":     "and",
  "semi_auto": ["author", "category"],
  "manual":    [{ "key": "...", "op": "...", "value": "..." }]
}
```

Configurable via `POST /api/v1/chats` ou `PUT /api/v1/chats/{chat_id}`.

---

## Fichiers clés

| Fichier | Rôle |
|---------|------|
| `common/metadata_utils.py:42` | Logique de filtrage + opérateurs |
| `common/metadata_utils.py:278` | Conversion schéma custom → JSON Schema |
| `api/db/services/doc_metadata_service.py` | CRUD index métadonnées |
| `rag/svr/task_executor.py:423` | Extraction LLM pendant ingestion |
| `rag/prompts/meta_data.md` | Prompt extraction métadonnées |
| `rag/prompts/meta_filter.md` | Prompt génération de filtres |
| `rag/prompts/generator.py:483` | `gen_meta_filter()` + `gen_metadata()` |
| `api/db/services/dialog_service.py:1434` | Application du filtre au retrieval |
| `rag/flow/parser/pdf_chunk_metadata.py` | Métadonnées de position PDF |
