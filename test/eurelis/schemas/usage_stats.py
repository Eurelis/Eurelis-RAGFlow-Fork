# Eurelis — schémas de contrat des statistiques de consommation de tokens (feature Eurelis).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

NUMBER = {"type": "number"}
STRING = {"type": "string"}

SOURCES_SCHEMA = {
    "type": "object",
    "required": ["sources", "types"],
    "properties": {
        "sources": {"type": "array", "items": STRING},
        "types": {"type": "array", "items": STRING},
    },
}

# GET /usage-stats/me/session/{id} — contrat SessionStats consommé par le Shield.
SESSION_STATS_SCHEMA = {
    "type": "object",
    "required": ["object_id", "source", "totals", "by_turn"],
    "properties": {
        "object_id": STRING,
        "source": STRING,
        "totals": {
            "type": "object",
            "required": ["turns", "tokens", "total_duration_ms", "avg_duration_ms"],
            "properties": {
                "turns": NUMBER,
                "tokens": NUMBER,
                "total_duration_ms": NUMBER,
                "avg_duration_ms": NUMBER,
            },
        },
        "by_turn": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["turn", "tokens", "duration_ms"],
                "properties": {"turn": NUMBER, "tokens": NUMBER, "duration_ms": NUMBER},
            },
        },
    },
}

TIMESERIES_SCHEMA = {
    "type": "object",
    "required": ["granularity", "series"],
    "properties": {
        "granularity": STRING,
        "series": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["period", "tokens"],
                "properties": {"period": STRING, "tokens": NUMBER, "sessions": NUMBER},
            },
        },
    },
}

BREAKDOWN_SCHEMA = {
    "type": "object",
    "required": ["group_by", "items"],
    "properties": {
        "group_by": STRING,
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["label", "tokens", "token_type"],
                "properties": {
                    "label": STRING,
                    "tokens": NUMBER,
                    "token_type": STRING,
                    "pct_tokens": NUMBER,
                    "provider": STRING,
                    "sessions": NUMBER,
                },
            },
        },
    },
}

INGESTION_SCHEMA = {
    "type": "object",
    "required": ["by_kb", "totals", "period"],
    "properties": {
        "totals": {
            "type": "object",
            "required": ["tokens", "tasks"],
            "properties": {"tokens": NUMBER, "tasks": NUMBER, "total_duration_ms": NUMBER},
        },
        "period": {
            "type": "object",
            "required": ["from", "to"],
            "properties": {"from": STRING, "to": STRING},
        },
        "by_kb": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["kb_id", "kb_name", "tokens", "tasks"],
                "properties": {
                    "kb_id": STRING,
                    "kb_name": STRING,
                    "tokens": NUMBER,
                    "tasks": NUMBER,
                },
            },
        },
    },
}
