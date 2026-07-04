# Eurelis — P0 : contrat du retrieval /datasets/search consommé par le Shield (feature 028, T012).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Les chunks portent les NOMS INTERNES RAGFlow (chunk_id/content_with_weight/doc_id/docnm_kwd/kb_id),
# distincts des noms enrichis du résumé (document_id/dataset_id) — c'est le contrat dont dépend
# normalizeChunk côté Shield. Ne pas uniformiser.

import pytest

from configs import REF_QUERY, VERSION
from libs.contract import assert_valid
from schemas.searches import DOC_AGG_SCHEMA, RETRIEVAL_CHUNK_SCHEMA, RETRIEVAL_DATA_SCHEMA


@pytest.mark.p0
def test_datasets_search_contract(api, ref_dataset_id, ref_search_id):
    """T012 — POST /datasets/search (search_id injecté par le Shield). Noms de champs INTERNES."""
    body = {
        "dataset_ids": [ref_dataset_id],
        "question": REF_QUERY,
        "search_id": ref_search_id,    # fait hériter le search_config (comme le proxy Shield)
        "page": 1,
        "size": 10,
        "highlight": True,
    }
    r = api.post(f"/api/{VERSION}/datasets/search", json=body)
    assert r.status_code == 200 and r.json()["code"] == 0, r.text
    data = r.json()["data"]
    assert_valid(data, RETRIEVAL_DATA_SCHEMA, label="datasets.search.data")
    assert data["chunks"], "aucun chunk (le doc de référence doit être parsé/indexé)"
    for i, c in enumerate(data["chunks"]):
        assert_valid(c, RETRIEVAL_CHUNK_SCHEMA, label=f"chunk[{i}]")
    for i, a in enumerate(data["doc_aggs"]):
        assert_valid(a, DOC_AGG_SCHEMA, label=f"doc_agg[{i}]")
