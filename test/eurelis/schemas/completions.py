# Eurelis — schémas de contrat du flux SSE de POST /api/v1/chats/{id}/completions.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Principe : on fige les champs CONSOMMÉS par le Shield (required + type). additionalProperties
# reste autorisé → un ajout de champ upstream ne casse pas ; seuls un retrait / renommage /
# changement de type (qui casseraient le Shield) sont détectés.

NUMBER = {"type": "number"}
STRING = {"type": "string"}
NULLABLE_STRING = {"type": ["string", "null"]}

# --- Un chunk de citation (reference.chunks[]) ----------------------------------------------
CHUNK_SCHEMA = {
    "type": "object",
    "required": [
        "id", "content", "document_id", "document_name",
        "dataset_id", "similarity", "image_id", "url",
    ],
    "properties": {
        "id": STRING,
        "content": STRING,
        "document_id": STRING,
        "document_name": STRING,
        "dataset_id": STRING,
        "similarity": NUMBER,
        "vector_similarity": NUMBER,
        "term_similarity": NUMBER,
        "image_id": STRING,          # "" si pas d'image
        "url": NULLABLE_STRING,      # null si pas d'URL
    },
}

# --- Agrégat par document (reference.doc_aggs[]) --------------------------------------------
DOC_AGG_SCHEMA = {
    "type": "object",
    "required": ["doc_id", "doc_name", "count"],
    "properties": {
        "doc_id": STRING,
        "doc_name": STRING,
        "count": NUMBER,
    },
}

# reference des frames de streaming : seul `chunks` est garanti (souvent vide en cours de flux).
REFERENCE_MIN_SCHEMA = {
    "type": "object",
    "required": ["chunks"],
    "properties": {
        "chunks": {"type": "array", "items": CHUNK_SCHEMA},
        "doc_aggs": {"type": "array", "items": DOC_AGG_SCHEMA},
        "total": NUMBER,
    },
}

# reference de la frame finale : `chunks` ET `doc_aggs` garantis (citations rendues par le Shield).
REFERENCE_SCHEMA = {
    "type": "object",
    "required": ["chunks", "doc_aggs"],
    "properties": {
        "chunks": {"type": "array", "items": CHUNK_SCHEMA},
        "doc_aggs": {"type": "array", "items": DOC_AGG_SCHEMA},
        "total": NUMBER,
    },
}

# --- Consommation de tokens (frame finale) — enrichissement Eurelis -------------------------
USAGE_SCHEMA = {
    "type": "object",
    "required": ["prompt_tokens", "completion_tokens", "total_tokens", "model", "provider"],
    "properties": {
        "prompt_tokens": NUMBER,
        "completion_tokens": NUMBER,
        "total_tokens": NUMBER,
        "model": STRING,
        "provider": STRING,
        "duration_ms": NUMBER,
        "embedding_tokens": NUMBER,
        "embedding_model": STRING,
        "embedding_provider": STRING,
    },
}

# --- Payload d'une frame de réponse (data des frames streaming/finale) ----------------------
ANSWER_DATA_SCHEMA = {
    "type": "object",
    "required": ["answer", "reference", "final", "session_id", "id", "chat_id"],
    "properties": {
        "answer": STRING,
        "reference": REFERENCE_MIN_SCHEMA,
        "final": {"type": "boolean"},
        "session_id": STRING,
        "id": STRING,
        "chat_id": STRING,
        "audio_binary": {"type": ["string", "null"]},
        "usage": USAGE_SCHEMA,   # présent sur la frame finale
    },
}

# --- Enveloppe SSE : {code, message, data} --------------------------------------------------
# data = objet (frame de réponse) OU booléen true (frame terminale).
ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["code", "message", "data"],
    "properties": {
        "code": {"type": "integer"},
        "message": STRING,
        "data": {},  # affiné par le test selon le type de frame
    },
}
