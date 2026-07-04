# Eurelis — helper : matrice de consommation de tokens par (source, token_type).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

from configs import VERSION

# Toutes les sources connues du schéma usage_log Eurelis.
KNOWN_SOURCES = ("chat", "search", "agent", "ingestion", "dataset")


def usage_matrix(api, sources=KNOWN_SOURCES) -> dict:
    """
    Renvoie {(source, token_type): tokens} en agrégeant /me/breakdown filtré par source.
    Permet des assertions d'isolation stricte (telle paire augmente, les autres non).
    """
    matrix: dict = {}
    for src in sources:
        data = api.get(f"/api/{VERSION}/usage-stats/me/breakdown", params={"source": src}).json()["data"]
        for item in data.get("items", []):
            key = (src, item["token_type"])
            matrix[key] = matrix.get(key, 0) + item["tokens"]
    return matrix


def delta(before: dict, after: dict) -> dict:
    """Cellules dont le total a changé, {(source, token_type): écart}."""
    keys = set(before) | set(after)
    return {k: after.get(k, 0) - before.get(k, 0) for k in keys if after.get(k, 0) != before.get(k, 0)}
