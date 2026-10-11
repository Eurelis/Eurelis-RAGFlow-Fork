# Eurelis — non-régression AILAB-43 : les modèles d'un agent canvas sont résolus sur le tenant du propriétaire.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Upstream résout les modèles des composants (LLM, Agent, Categorize, Browser, TTS, chat des outils)
# sur le tenant de l'APPELANT : un membre d'équipe sans fournisseur de modèles ne peut pas exécuter
# un agent partagé (« Provider OpenAI not found for model gpt-4.1@OpenAI »). Le correctif aligne les
# agents sur les assistants : `Canvas.get_model_tenant_id()` vaut le propriétaire du canvas
# (`user_canvas.user_id`), avec repli sur l'appelant (pas de canvas_id, canvas introuvable,
# interrupteur EURELIS_AGENT_MODELS_FROM_OWNER coupé). `get_tenant_id()` reste l'appelant
# (stockage, sessions, attribution de l'usage). Les composants résolvant leur modèle dans leur
# constructeur, le tenant des modèles doit être disponible pendant `load()`.

import json
from types import SimpleNamespace

import pytest

import agent.canvas as canvas_module
from agent import eurelis_model_tenant
from agent.canvas import Canvas, Graph
from api.db.services import canvas_service

OWNER = "owner-tenant"
CALLER = "caller-tenant"
CANVAS_ID = "canvas-1"

DSL = json.dumps(
    {
        "components": {
            "spy": {
                "obj": {"component_name": "Spy", "params": {}},
                "downstream": [],
                "upstream": [],
            }
        },
        "history": [],
        "path": [],
        "retrieval": [],
        "globals": {"sys.query": "", "sys.user_id": "", "sys.conversation_turns": 0, "sys.files": []},
    }
)


class _SpyParam:
    def update(self, _params):
        pass

    def check(self):
        pass


class _Spy:
    """Composant factice : comme LLM/Agent, résout le tenant des modèles dans son constructeur."""

    seen: list = []

    def __init__(self, canvas, component_id, param):
        _Spy.seen.append(canvas.get_model_tenant_id())


@pytest.fixture(autouse=True)
def fake_components(monkeypatch):
    """Registre de composants factice : le test ne dépend pas des extras du venv (zhipuai…)."""
    _Spy.seen = []
    registry = {"SpyParam": _SpyParam, "Spy": _Spy}
    monkeypatch.setattr(canvas_module, "component_class", lambda name: registry[name])


@pytest.fixture
def owner_lookup(monkeypatch):
    """UserCanvasService.get_by_id mocké : renvoie un canvas appartenant à OWNER et compte les appels."""
    calls = []

    def _get_by_id(canvas_id):
        calls.append(canvas_id)
        if canvas_id == CANVAS_ID:
            return True, SimpleNamespace(id=canvas_id, user_id=OWNER)
        return False, None

    monkeypatch.setattr(canvas_service.UserCanvasService, "get_by_id", staticmethod(_get_by_id))
    monkeypatch.delenv(eurelis_model_tenant.ENV_SWITCH, raising=False)
    return calls


def test_model_tenant_is_canvas_owner(owner_lookup):
    cvs = Canvas(DSL, CALLER, canvas_id=CANVAS_ID)
    assert cvs.get_model_tenant_id() == OWNER
    # Stockage, sessions et attribution restent chez l'appelant.
    assert cvs.get_tenant_id() == CALLER


def test_owner_resolved_once_per_canvas(owner_lookup):
    cvs = Canvas(DSL, CALLER, canvas_id=CANVAS_ID)
    for _ in range(3):
        cvs.get_model_tenant_id()
    assert owner_lookup == [CANVAS_ID]


def test_model_tenant_available_while_components_load(owner_lookup):
    Canvas(DSL, CALLER, canvas_id=CANVAS_ID)
    assert _Spy.seen == [OWNER]


def test_falls_back_to_caller_without_canvas_id(owner_lookup):
    assert Canvas(DSL, CALLER).get_model_tenant_id() == CALLER
    assert owner_lookup == []


def test_falls_back_to_caller_when_canvas_not_found(owner_lookup):
    assert Canvas(DSL, CALLER, canvas_id="missing").get_model_tenant_id() == CALLER


def test_falls_back_to_caller_when_lookup_fails(monkeypatch):
    def _boom(_canvas_id):
        raise RuntimeError("db down")

    monkeypatch.setattr(canvas_service.UserCanvasService, "get_by_id", staticmethod(_boom))
    assert eurelis_model_tenant.resolve_model_tenant_id(CANVAS_ID, CALLER) == CALLER


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE"])
def test_switch_off_restores_upstream(owner_lookup, monkeypatch, value):
    monkeypatch.setenv(eurelis_model_tenant.ENV_SWITCH, value)
    assert Canvas(DSL, CALLER, canvas_id=CANVAS_ID).get_model_tenant_id() == CALLER
    assert owner_lookup == []


@pytest.mark.parametrize("value", ["true", "1", "yes", ""])
def test_switch_on_values(owner_lookup, monkeypatch, value):
    monkeypatch.setenv(eurelis_model_tenant.ENV_SWITCH, value)
    assert Canvas(DSL, CALLER, canvas_id=CANVAS_ID).get_model_tenant_id() == OWNER


def test_graph_keeps_caller_as_model_tenant():
    """Pipelines d'ingestion (Graph, pas Canvas) : comportement upstream inchangé."""
    graph = Graph.__new__(Graph)
    graph._tenant_id = CALLER
    assert graph.get_model_tenant_id() == CALLER
