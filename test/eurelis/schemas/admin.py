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

# POST /api/v1/admin/users → data = utilisateur créé (mot de passe retiré par la route).
# Le Shield auto-provisionne les comptes via cet endpoint ; on fige la forme minimale consommée
# (id non vide + email écho) et l'ABSENCE du champ password (jamais renvoyé).
ADMIN_CREATED_USER_SCHEMA = {
    "type": "object",
    "required": ["id", "email"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "email": STRING,
    },
    "not": {"required": ["password"]},
}

# POST /api/v1/admin/tenants/{tenant_id}/users → data = enregistrement d'appartenance créé/réactivé.
# On fige la forme minimale consommable : identifiants, rôle (normal|admin, jamais owner), statut.
ADMIN_MEMBER_RECORD_SCHEMA = {
    "type": "object",
    "required": ["id", "user_id", "tenant_id", "role", "status"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "user_id": {"type": "string", "minLength": 1},
        "tenant_id": {"type": "string", "minLength": 1},
        "role": {"type": "string", "enum": ["normal", "admin"]},
        "status": STRING,
    },
}
