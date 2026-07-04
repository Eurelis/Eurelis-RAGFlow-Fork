# Eurelis — schéma de contrat de l'upload de fichier chat (DocumentRecord consommé par le Shield).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

STRING = {"type": "string"}

# Réponse de POST /api/v1/documents/upload (data)
UPLOAD_RECORD_SCHEMA = {
    "type": "object",
    "required": ["id", "name", "mime_type", "created_by"],
    "properties": {
        "id": STRING,
        "name": STRING,
        "mime_type": STRING,
        "created_by": STRING,
        "extension": STRING,
        "size": {"type": "number"},
        "preview_url": {"type": ["string", "null"]},
    },
}
