# Eurelis — P1 : statistiques de consommation de tokens côté utilisateur (:9380). Feature Eurelis.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Valide schéma ET cohérence des agrégats (sommes, pourcentages). L'endpoint /me/session est aussi
# le contrat SessionStats consommé par le Shield.

import httpx
import pytest

from configs import HOST_ADDRESS, HTTP_TIMEOUT, VERSION
from libs.contract import assert_valid
from libs.sse import stream_completions
from schemas.usage_stats import (
    BREAKDOWN_SCHEMA,
    INGESTION_SCHEMA,
    SESSION_STATS_SCHEMA,
    SOURCES_SCHEMA,
    TIMESERIES_SCHEMA,
)


@pytest.fixture(scope="module")
def used_session(token, ref_chat_id):
    """Crée une session et y génère une complétion (donc de la consommation à mesurer)."""
    with httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        sid = client.post(f"/api/{VERSION}/chats/{ref_chat_id}/sessions", json={"name": "usage"}).json()["data"]["id"]
        stream_completions(client, ref_chat_id, "Que fait Eurelis ?", sid)
        yield sid
        client.request("DELETE", f"/api/{VERSION}/chats/{ref_chat_id}/sessions", json={"ids": [sid]})


@pytest.mark.p1
def test_sources_contract(api):
    r = api.get(f"/api/{VERSION}/usage-stats/me/sources")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert_valid(data, SOURCES_SCHEMA, label="sources")
    # schéma orthogonal Eurelis : le type de token distingue llm et embedding.
    assert "llm" in data["types"] and "embedding" in data["types"], data["types"]


@pytest.mark.p1
def test_session_stats_contract(api, used_session):
    """Contrat SessionStats (Shield) + cohérence : tokens > 0 et totaux alignés sur les tours."""
    r = api.get(f"/api/{VERSION}/usage-stats/me/session/{used_session}")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert_valid(data, SESSION_STATS_SCHEMA, label="session stats")
    assert data["object_id"] == used_session
    assert data["totals"]["tokens"] > 0, "aucun token comptabilisé pour la session"
    assert data["totals"]["turns"] == len(data["by_turn"]), "totals.turns != nombre de tours"
    assert data["totals"]["tokens"] == sum(t["tokens"] for t in data["by_turn"]), "somme des tokens par tour incohérente"


@pytest.mark.p1
def test_timeseries_contract(api, used_session):
    r = api.get(f"/api/{VERSION}/usage-stats/me/timeseries")
    assert r.status_code == 200, r.text
    assert_valid(r.json()["data"], TIMESERIES_SCHEMA, label="timeseries")


@pytest.mark.p1
def test_breakdown_coherence(api, used_session):
    """Breakdown : schéma + les pourcentages de tokens somment à ~100."""
    r = api.get(f"/api/{VERSION}/usage-stats/me/breakdown")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert_valid(data, BREAKDOWN_SCHEMA, label="breakdown")
    items = data["items"]
    if items and all("pct_tokens" in it for it in items):
        assert abs(sum(it["pct_tokens"] for it in items) - 100.0) < 1.0, "pct_tokens ne somment pas à 100"


@pytest.mark.p1
def test_ingestion_coherence(api):
    """Ingestion : schéma + total des tokens = somme des tokens par base."""
    r = api.get(f"/api/{VERSION}/usage-stats/me/ingestion")
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert_valid(data, INGESTION_SCHEMA, label="ingestion")
    assert data["totals"]["tokens"] == sum(kb["tokens"] for kb in data["by_kb"]), "total ingestion != somme par base"
