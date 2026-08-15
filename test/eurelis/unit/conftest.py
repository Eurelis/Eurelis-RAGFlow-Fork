# Eurelis — conftest des tests unitaires (sans stack RAGFlow) : neutralise les fixtures serveur.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import os

# Comme api/ragflow_server.py : force le registre litellm EMBARQUÉ (pas de fetch distant),
# pour que les tests de registre reflètent exactement le runtime. Doit être posé avant
# le premier import de litellm (la carte est figée à l'import).
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def provisioned() -> None:
    """Surcharge no-op : les tests unitaires n'ont besoin d'aucune stack qui tourne."""
