# Eurelis — schémas de contrat des endpoints Search consommés par le Shield (feature 028-search-ui).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Principe (identique à schemas/completions.py) : figer UNIQUEMENT les champs consommés par le
# Shield (required + type) ; additionalProperties reste autorisé → un ajout de champ upstream ne
# casse pas, seuls un retrait/renommage/changement de type (qui casseraient le Shield) sont détectés.

NUMBER = {"type": "number"}
STRING = {"type": "string"}
BOOL = {"type": "boolean"}
NULLABLE_STRING = {"type": ["string", "null"]}

# --- T010 : item de data.search_apps[] (métadonnées de liste) --------------------------------
# `permission` (me|team) porte le partage d'équipe ajouté par le fork Eurelis (non requis ici :
# on ne fige que ce que le Shield consomme ; le partage est testé par test_team_shared_searches).
SEARCH_APP_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "tenant_id", "created_by", "update_time", "create_time"],
    "properties": {
        "id": STRING, "name": STRING, "description": NULLABLE_STRING, "avatar": NULLABLE_STRING,
        "tenant_id": STRING, "created_by": STRING, "status": STRING,
        "update_time": NUMBER, "create_time": NUMBER,
        "nickname": STRING, "tenant_avatar": NULLABLE_STRING,
        "permission": {"enum": ["me", "team"]},
    },
}
SEARCH_LIST_DATA_SCHEMA = {
    "type": "object",
    "required": ["search_apps", "total"],
    "properties": {
        "search_apps": {"type": "array", "items": SEARCH_APP_SCHEMA},
        "total": NUMBER,
    },
}

# --- T011 : data.search_config (flags/params lus par le Shield) ------------------------------
SEARCH_CONFIG_SCHEMA = {
    "type": "object",
    "required": ["kb_ids", "summary", "related_search"],
    "properties": {
        "kb_ids": {"type": "array", "items": STRING},
        "summary": BOOL,
        "related_search": BOOL,
        "query_mindmap": BOOL,
        "similarity_threshold": NUMBER,
        "vector_similarity_weight": NUMBER,
        "top_k": NUMBER,
        "rerank_id": STRING,
    },
}
SEARCH_DETAIL_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "search_config"],
    "properties": {
        "id": STRING, "name": STRING, "description": NULLABLE_STRING, "avatar": NULLABLE_STRING,
        "search_config": SEARCH_CONFIG_SCHEMA,
    },
}

# --- T012 : chunk du retrieval /datasets/search (NOMS INTERNES RAGFlow) ----------------------
RETRIEVAL_CHUNK_SCHEMA = {
    "type": "object",
    "required": ["chunk_id", "content_with_weight", "doc_id", "docnm_kwd", "kb_id", "image_id", "similarity"],
    "properties": {
        "chunk_id": STRING,
        "content_with_weight": STRING,
        "doc_id": STRING,
        "docnm_kwd": STRING,
        "kb_id": STRING,
        "image_id": STRING,            # "" si pas d'image
        "similarity": NUMBER,
        "vector_similarity": NUMBER,
        "term_similarity": NUMBER,
        "highlight": STRING,           # présent quand highlight=true
    },
}
DOC_AGG_SCHEMA = {
    "type": "object",
    "required": ["doc_id", "doc_name", "count"],
    "properties": {"doc_id": STRING, "doc_name": STRING, "count": NUMBER},
}
RETRIEVAL_DATA_SCHEMA = {
    "type": "object",
    "required": ["total", "chunks", "doc_aggs"],
    "properties": {
        "total": NUMBER,
        "chunks": {"type": "array", "items": RETRIEVAL_CHUNK_SCHEMA},
        "doc_aggs": {"type": "array", "items": DOC_AGG_SCHEMA},
    },
}

# --- T030 : résumé SSE — référence ENRICHIE (façon chatbot, noms document_id/dataset_id) -----
SUMMARY_CHUNK_SCHEMA = {
    "type": "object",
    "required": ["id", "content", "document_id", "document_name", "dataset_id", "image_id"],
    "properties": {
        "id": STRING, "content": STRING, "document_id": STRING, "document_name": STRING,
        "dataset_id": STRING, "image_id": STRING, "similarity": NUMBER, "url": NULLABLE_STRING,
    },
}
SUMMARY_REFERENCE_SCHEMA = {
    "type": "object",
    "required": ["chunks"],
    "properties": {
        "chunks": {"type": "array", "items": SUMMARY_CHUNK_SCHEMA},
        "doc_aggs": {"type": "array", "items": DOC_AGG_SCHEMA},
        "total": NUMBER,
    },
}
SUMMARY_ANSWER_DATA_SCHEMA = {
    "type": "object",
    "required": ["answer", "reference", "final"],
    "properties": {
        "answer": STRING,
        "reference": {},          # affiné par le test (objet sur la frame finale)
        "final": BOOL,
    },
}
SUMMARY_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["code", "message", "data"],
    "properties": {"code": {"type": "integer"}, "message": STRING, "data": {}},
}

# --- T036 : POST /chat/recommendation → data = liste de chaînes ------------------------------
RELATED_DATA_SCHEMA = {"type": "array", "items": STRING}
