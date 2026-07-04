# Eurelis — P0 : contrat des endpoints Search consommés par le Shield (feature 028, T010/T011/T036).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import pytest

from configs import REF_QUERY, VERSION
from libs.contract import assert_valid
from schemas.searches import (
    RELATED_DATA_SCHEMA,
    SEARCH_CONFIG_SCHEMA,
    SEARCH_DETAIL_SCHEMA,
    SEARCH_LIST_DATA_SCHEMA,
)


@pytest.mark.p0
def test_searches_list_contract(api, ref_search_id):
    """T010 — GET /searches : data.search_apps[] + total ; search_config ABSENT de la liste."""
    r = api.get(f"/api/{VERSION}/searches", params={"page": 0, "page_size": 0})
    assert r.status_code == 200 and r.json()["code"] == 0, r.text
    data = r.json()["data"]
    assert_valid(data, SEARCH_LIST_DATA_SCHEMA, label="searches.data")
    assert ref_search_id in [s["id"] for s in data["search_apps"]], "search de référence absente de la liste"
    for s in data["search_apps"]:
        assert "search_config" not in s, "search_config NE DOIT PAS figurer dans la liste"


@pytest.mark.p0
def test_search_detail_contract(api, ref_search_id):
    """T011 — GET /searches/{id} : data.search_config avec kb_ids/summary/related_search."""
    r = api.get(f"/api/{VERSION}/searches/{ref_search_id}")
    assert r.status_code == 200 and r.json()["code"] == 0, r.text
    data = r.json()["data"]
    assert_valid(data, SEARCH_DETAIL_SCHEMA, label="search.detail")
    assert_valid(data["search_config"], SEARCH_CONFIG_SCHEMA, label="search_config")
    assert data["search_config"]["kb_ids"], "kb_ids vide sur la search de référence"


@pytest.mark.p0
def test_chat_recommendation_contract(api, ref_search_id):
    """T036 — POST /chat/recommendation : data = liste de chaînes (contenu non figé)."""
    r = api.post(
        f"/api/{VERSION}/chat/recommendation",
        json={"question": REF_QUERY, "search_id": ref_search_id},
    )
    assert r.status_code == 200 and r.json()["code"] == 0, r.text
    assert_valid(r.json()["data"], RELATED_DATA_SCHEMA, label="recommendation.data")
    # NB : le petit modèle Ollama peut renvoyer une liste vide → on fige la STRUCTURE, pas la longueur.
