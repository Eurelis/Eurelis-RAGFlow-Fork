# Eurelis — schémas de contrat des objets Chat et Session (endpoints consommés par le Shield).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

STRING = {"type": "string"}

# --- Chat / agent (GET /chats, GET /chats?id=) ----------------------------------------------
CHAT_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "description", "icon", "llm_id", "dataset_ids"],
    "properties": {
        "id": STRING,
        "name": STRING,
        "description": {"type": ["string", "null"]},
        "icon": {"type": ["string", "null"]},
        "llm_id": STRING,
        "dataset_ids": {"type": "array", "items": STRING},
    },
}

# --- Message d'une session (session.messages[]) ---------------------------------------------
MESSAGE_SCHEMA = {
    "type": "object",
    "required": ["role", "content"],
    "properties": {
        "role": STRING,
        "content": {"type": ["string", "null"]},
    },
}

# --- Session (data des endpoints /chats/{id}/sessions) --------------------------------------
SESSION_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "chat_id"],
    "properties": {
        "id": STRING,
        "name": STRING,
        "chat_id": STRING,
        "messages": {"type": "array", "items": MESSAGE_SCHEMA},
        "reference": {"type": "array"},
    },
}
