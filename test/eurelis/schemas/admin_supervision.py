# Eurelis — schémas de contrat des endpoints admin (:9381) : stats globales + supervision modèles.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

NUMBER = {"type": "number"}
STRING = {"type": "string"}

# GET /admin/stats/users
ADMIN_USERS_SCHEMA = {
    "type": "object",
    "required": ["users"],
    "properties": {
        "active_users": NUMBER,
        "users": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["user_id", "email", "tokens"],
                "properties": {
                    "user_id": STRING,
                    "email": STRING,
                    "tokens": NUMBER,
                    "sessions": NUMBER,
                    "sources": {"type": "array", "items": STRING},
                },
            },
        },
    },
}

# Une instance de provider vue par la supervision — la clé API doit être MASQUÉE.
INSTANCE_SCHEMA = {
    "type": "object",
    "required": ["instance_name", "provider_name", "api_key_hint", "has_api_key"],
    "properties": {
        "instance_name": STRING,
        "provider_name": STRING,
        "base_url": STRING,
        "api_key_hint": STRING,          # ex. "***" — jamais la valeur en clair
        "has_api_key": {"type": "boolean"},
        "status": STRING,
    },
}

# GET /admin/tenants/{id}/models
TENANT_MODELS_SCHEMA = {
    "type": "object",
    "required": ["added_models", "default_models", "instances", "tenant_id"],
    "properties": {
        "tenant_id": STRING,
        "added_models": {"type": "array"},
        "default_models": {"type": "array"},
        "instances": {"type": "array", "items": INSTANCE_SCHEMA},
    },
}
