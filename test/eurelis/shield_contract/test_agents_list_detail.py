# Eurelis — P0 : contrat liste / détail / versions des agents canvas consommés par le Shield (031, T006).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Le Shield liste les agents PUBLIÉS (release_time non nul) de catégorie agent_canvas, avec la clé
# d'un membre de l'équipe ; il lit le formulaire de départ dans le DSL de la dernière version publiée
# (liste des versions SANS dsl → détail de version AVEC dsl). La liste ne doit jamais porter de dsl.

import pytest

from configs import VERSION
from libs.agents import ok
from libs.contract import assert_valid
from schemas.agents import (
    AGENT_DETAIL_SCHEMA,
    AGENT_LIST_DATA_SCHEMA,
    VERSION_DETAIL_SCHEMA,
    VERSION_LIST_ITEM_SCHEMA,
)


@pytest.mark.p0
def test_member_lists_published_team_agent(agent_member, contract_agent_id):
    body = ok(agent_member.get(f"/api/{VERSION}/agents", params={"canvas_category": "agent_canvas", "page_size": 0}))
    assert_valid(body["data"], AGENT_LIST_DATA_SCHEMA, label="agents list")
    mine = [a for a in body["data"]["canvas"] if a["id"] == contract_agent_id]
    assert mine, "agent partagé `team` invisible pour un membre de l'équipe"
    assert mine[0]["release_time"], "release_time absent : le Shield ne pourrait pas filtrer les agents publiés"
    assert all(a["canvas_category"] == "agent_canvas" for a in body["data"]["canvas"])


@pytest.mark.p0
def test_agent_detail_metadata(agent_member, contract_agent_id):
    body = ok(agent_member.get(f"/api/{VERSION}/agents/{contract_agent_id}"))
    assert_valid(body["data"], AGENT_DETAIL_SCHEMA, label="agent detail")


@pytest.mark.p0
def test_published_version_dsl(agent_member, contract_agent_id):
    versions = ok(agent_member.get(f"/api/{VERSION}/agents/{contract_agent_id}/versions"))["data"]
    for i, v in enumerate(versions):
        assert_valid(v, VERSION_LIST_ITEM_SCHEMA, label=f"version[{i}]")
    released = [v for v in versions if v["release"]]
    assert released, "aucune version publiée"
    latest = max(released, key=lambda v: v["update_time"])
    detail = ok(agent_member.get(f"/api/{VERSION}/agents/{contract_agent_id}/versions/{latest['id']}"))["data"]
    assert_valid(detail, VERSION_DETAIL_SCHEMA, label="version detail")
    inputs = detail["dsl"]["components"]["begin"]["obj"]["params"]["inputs"]
    assert {"sujet", "regime", "document"} <= set(inputs)
    names = {n["id"]: n["data"].get("name") for n in detail["dsl"]["graph"]["nodes"]}
    assert names.get("UserFillUp:Valid") == "Validation", "nom d'affichage du graphe non exposé"
