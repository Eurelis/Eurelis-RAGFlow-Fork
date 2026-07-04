# Eurelis — schémas de contrat des endpoints Admin (team enrollment) consommés par le Shield.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

STRING = {"type": "string"}

# GET /api/v1/admin/users/{email} renvoie data = LISTE d'utilisateurs (0 ou 1 sur un email donné).
# Le Shield lit l'`id` du premier élément et traite la liste vide comme « utilisateur inexistant ».
# On ne fige donc que la forme (liste d'objets porteurs d'un `id` non vide).
ADMIN_USER_ITEM_SCHEMA = {
    "type": "object",
    "required": ["id"],
    "properties": {"id": {"type": "string", "minLength": 1}},
}
ADMIN_USER_LIST_SCHEMA = {"type": "array", "items": ADMIN_USER_ITEM_SCHEMA}

# Enveloppe Admin standard {code, message, data} — `message` figé (string) car le Shield en dépend
# sur le cas d'erreur d'ajout d'un membre déjà présent (matching de la sous-chaîne "already").
ADMIN_ENVELOPE_SCHEMA = {
    "type": "object",
    "required": ["code", "message", "data"],
    "properties": {"code": {"type": "integer"}, "message": STRING, "data": {}},
}
