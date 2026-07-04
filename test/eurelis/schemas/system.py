# Eurelis — schémas de contrat de l'endpoint system/version consommé par le Shield.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

STRING = {"type": "string"}

# Enveloppe de GET /api/v1/system/version.
# Le Shield (probe_system_version) consomme `code` (test code==0), `data` (version)
# ET `message` (message d'erreur sur code != 0) — les trois sont figés ici.
SYSTEM_VERSION_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["code", "message", "data"],
    "properties": {
        "code": {"type": "integer"},
        "message": STRING,
        "data": {"type": "string", "minLength": 1},
    },
}
