# Eurelis — schémas de contrat des endpoints Agent (canvas) consommés par le Shield (feature 031).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Principe (identique à schemas/searches.py) : figer UNIQUEMENT les champs consommés par le Shield
# (required + type) ; additionalProperties reste autorisé → un ajout de champ upstream ne casse pas,
# seuls un retrait/renommage/changement de type (qui casseraient le Shield) sont détectés.

NUMBER = {"type": "number"}
STRING = {"type": "string"}
BOOL = {"type": "boolean"}
NULLABLE_STRING = {"type": ["string", "null"]}
NULLABLE_NUMBER = {"type": ["number", "null"]}
OBJECT = {"type": "object"}

# --- Liste GET /agents : data.canvas[] (jamais de dsl) ----------------------------------------
AGENT_LIST_ITEM_SCHEMA = {
    "type": "object",
    "required": ["id", "title", "canvas_category", "permission", "release_time"],
    "properties": {
        "id": STRING, "title": STRING, "description": NULLABLE_STRING, "avatar": NULLABLE_STRING,
        "canvas_category": STRING, "permission": {"enum": ["me", "team"]},
        "release_time": NULLABLE_NUMBER,
    },
    "not": {"required": ["dsl"]},
}
AGENT_LIST_DATA_SCHEMA = {
    "type": "object",
    "required": ["canvas", "total"],
    "properties": {"canvas": {"type": "array", "items": AGENT_LIST_ITEM_SCHEMA}, "total": NUMBER},
}

# --- Détail GET /agents/{id} : métadonnées lues par le Shield ---------------------------------
AGENT_DETAIL_SCHEMA = {
    "type": "object",
    "required": ["id", "title"],
    "properties": {"id": STRING, "title": STRING, "description": NULLABLE_STRING, "avatar": NULLABLE_STRING},
}

# --- DSL (publié ou de session) : parties lues côté serveur par le Shield ---------------------
BEGIN_INPUT_SCHEMA = {
    "type": "object",
    "required": ["type"],
    "properties": {
        "type": {"enum": ["line", "paragraph", "options", "file", "integer", "boolean"]},
        "name": STRING, "optional": BOOL, "options": {"type": "array"},
    },
}
DSL_SCHEMA = {
    "type": "object",
    "required": ["components", "graph", "path"],
    "properties": {
        "path": {"type": "array", "items": STRING},
        "components": {
            "type": "object",
            "required": ["begin"],
            "additionalProperties": {
                "type": "object",
                "required": ["obj", "downstream"],
                "properties": {
                    "obj": {"type": "object", "required": ["component_name", "params"]},
                    "downstream": {"type": "array", "items": STRING},
                },
            },
        },
        "graph": {
            "type": "object",
            "required": ["nodes"],
            "properties": {"nodes": {"type": "array", "items": {
                "type": "object", "required": ["id", "data"],
                "properties": {"id": STRING, "data": {"type": "object", "properties": {"name": STRING}}},
            }}},
        },
    },
}

# --- Versions : liste SANS dsl, détail AVEC dsl ------------------------------------------------
VERSION_LIST_ITEM_SCHEMA = {
    "type": "object",
    "required": ["id", "release", "update_time"],
    "properties": {"id": STRING, "release": BOOL, "update_time": NUMBER},
}
VERSION_DETAIL_SCHEMA = {
    "type": "object",
    "required": ["id", "release", "dsl"],
    "properties": {"id": STRING, "release": BOOL, "dsl": DSL_SCHEMA},
}

# --- Upload POST /agents/{id}/upload : objet réinjecté tel quel dans inputs.<champ>.value -------
UPLOAD_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "size", "extension", "mime_type", "created_by"],
    "properties": {
        "id": STRING, "name": STRING, "size": NUMBER, "extension": STRING,
        "mime_type": STRING, "created_by": STRING, "created_at": NUMBER,
    },
}

# --- Sessions ----------------------------------------------------------------------------------
SESSION_CREATED_SCHEMA = {
    "type": "object",
    "required": ["id", "agent_id", "user_id", "source", "dsl"],
    "properties": {"id": STRING, "agent_id": STRING, "user_id": STRING, "source": {"const": "agent"}},
}
SESSION_LIST_ITEM_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "user_id", "create_date", "update_date"],
    "properties": {"id": STRING, "name": STRING, "user_id": STRING, "create_date": STRING, "update_date": STRING},
}
# GET one : conv.to_dict() brut ; `dsl` = chaîne JSON (voie agent) ou objet.
SESSION_DETAIL_SCHEMA = {
    "type": "object",
    "required": ["id", "dialog_id", "user_id", "message", "dsl", "errors"],
    "properties": {
        "id": STRING, "dialog_id": STRING, "user_id": STRING,
        "message": {"type": "array", "items": {"type": "object", "required": ["role", "content"]}},
        "dsl": {"type": ["string", "object"]},
        "errors": NULLABLE_STRING,
        "name": NULLABLE_STRING,
    },
}

# --- Événements SSE de chat/completions (voie session « agent ») -------------------------------
SSE_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["event", "session_id", "data"],
    "properties": {"event": STRING, "session_id": STRING, "data": OBJECT},
}
NODE_FINISHED_DATA_SCHEMA = {
    "type": "object",
    "required": ["component_id", "component_name", "component_type", "error", "elapsed_time"],
    "properties": {
        "component_id": STRING, "component_name": STRING, "component_type": STRING,
        "error": NULLABLE_STRING, "elapsed_time": NUMBER,
    },
}
MESSAGE_DATA_SCHEMA = {
    "type": "object",
    "required": ["content"],
    "properties": {"content": STRING, "start_to_think": BOOL, "end_to_think": BOOL},
}
MESSAGE_END_DATA_SCHEMA = {
    "type": "object",
    "properties": {
        "attachment": {
            "type": "object",
            "required": ["doc_id", "format", "file_name"],
            "properties": {"doc_id": STRING, "format": STRING, "file_name": STRING},
        },
        "reference": OBJECT,
    },
}
USER_INPUTS_DATA_SCHEMA = {
    "type": "object",
    "required": ["inputs", "tips"],
    "properties": {
        "inputs": {"type": "object", "additionalProperties": BEGIN_INPUT_SCHEMA},
        "tips": STRING,
    },
}
WORKFLOW_FINISHED_DATA_SCHEMA = {
    "type": "object",
    "required": ["usage"],
    "properties": {"usage": OBJECT},
}
