# Eurelis — P1 : la voie de retrieval (rag/nlp/search.py) répond et renvoie des chunks conformes.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Zone du correctif Eurelis « chunk parent orphelin » (guard None dans retrieval_by_children) :
# ce test garde globalement le chemin de recherche contre une régression de crash/forme.

import pytest

from configs import REF_DATASET_NAME, VERSION
from libs.contract import assert_valid

RETRIEVAL_CHUNK_SCHEMA = {
    "type": "object",
    "required": ["id", "content", "document_id", "dataset_id", "similarity"],
    "properties": {
        "id": {"type": "string"},
        "content": {"type": "string"},
        "document_id": {"type": "string"},
        "dataset_id": {"type": "string"},
        "similarity": {"type": "number"},
    },
}


@pytest.fixture(scope="module")
def ref_dataset_id(token):
    import httpx

    from configs import HOST_ADDRESS, HTTP_TIMEOUT

    with httpx.Client(base_url=HOST_ADDRESS, headers={"Authorization": f"Bearer {token}"}, timeout=HTTP_TIMEOUT) as c:
        ds = c.get(f"/api/{VERSION}/datasets", params={"name": REF_DATASET_NAME}).json()["data"]
        assert ds, "dataset de référence introuvable"
        return ds[0]["id"]


@pytest.mark.p1
def test_retrieval_returns_conformant_chunks(api, ref_dataset_id):
    """POST /retrieval sur le dataset de référence : ne crashe pas et renvoie des chunks conformes."""
    r = api.post(
        f"/api/{VERSION}/retrieval",
        json={"question": "Que fait Eurelis avec RAGFlow ?", "dataset_ids": [ref_dataset_id]},
    )
    assert r.status_code == 200, r.text
    data = r.json().get("data") or {}
    assert isinstance(data.get("chunks"), list) and data["chunks"], "aucun chunk retourné"
    assert data.get("total", 0) >= 1
    for i, chunk in enumerate(data["chunks"]):
        assert_valid(chunk, RETRIEVAL_CHUNK_SCHEMA, label=f"chunk[{i}]")
