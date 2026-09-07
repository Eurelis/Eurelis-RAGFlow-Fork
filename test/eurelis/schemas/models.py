# Eurelis — schéma de contrat de GET /api/v1/models (résolution des llm_id UUID par le Shield).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
# NB : la docstring Swagger de la route est obsolète ; ce schéma fige la réponse réelle.

STRING = {"type": "string"}

# --- Entrée de modèle (data[]) ---------------------------------------------------------------
# Le Shield reconstruit le nom composite f"{name}@{instance_name}@{provider_name}"
# à partir de l'entrée dont model_id correspond au llm_id UUID d'un chat.
MODEL_SCHEMA = {
    "type": "object",
    "required": ["model_id", "name", "provider_name", "instance_name", "model_type"],
    "properties": {
        "model_id": {"type": "string", "pattern": "^[0-9a-f]{32}$"},
        "name": {"type": "string", "minLength": 1},
        "provider_name": {"type": "string", "minLength": 1},
        "instance_name": {"type": "string", "minLength": 1},
        "model_type": {"type": "array", "items": STRING},
    },
}

# --- Enveloppe de la réponse -----------------------------------------------------------------
MODELS_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["code", "data"],
    "properties": {
        "code": {"type": "integer"},
        "data": {"type": "array", "items": MODEL_SCHEMA},
    },
}
