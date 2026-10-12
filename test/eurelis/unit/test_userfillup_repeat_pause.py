# Eurelis — non-régression AILAB-43 (CRM v1.2) : un UserFillUp atteint une 2e fois doit refaire une pause.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Boucle de validation : Message:Version → UserFillUp:Valid {decision, retour} → Switch
# (decision = Valider → Message:Fin ; sinon → Message:Version). Upstream ne vide jamais les entrées
# du UserFillUp : au 2e passage, `Canvas.run` trouve tous les champs « satisfaits » par le tour
# précédent, saute la pause et le Switch relit `Modifier` → boucle infinie (tokens LLM consommés).
# Correctif : `o.reset()` avant `o.invoke()` dans le bloc de détection de pause.
#
# Moteur réel (Canvas.run) sans stack : registre de composants limité à Begin/UserFillUp/Message/Switch
# (le registre complet ne s'importe pas dans le venv local, zhipuai), annulation Redis neutralisée.

import asyncio
import json
from pathlib import Path

import pytest

import agent.canvas as canvas_module
from agent.canvas import Canvas
from agent.component import begin, fillup, message, switch

CANVAS_FILE = Path(__file__).resolve().parents[1] / "fixtures" / "agent_userfillup_loop_canvas.json"
TENANT = "tenant-ailab43"
MAX_NODE_FINISHED = 30  # garde-fou : la version boguée boucle sans fin

MODIFIER = {"decision": {"type": "options", "value": "Modifier"}, "retour": {"type": "paragraph", "value": "Plus court"}}
VALIDER = {"decision": {"type": "options", "value": "Valider"}, "retour": {"type": "paragraph", "value": ""}}


@pytest.fixture(autouse=True)
def engine(monkeypatch):
    registry = {}
    for mod in (begin, fillup, message, switch):
        registry.update({name: getattr(mod, name) for name in dir(mod)})
    monkeypatch.setattr(canvas_module, "component_class", lambda name: registry[name])
    monkeypatch.setattr(canvas_module, "has_canceled", lambda *_: False)


def _run(dsl: str, **kwargs) -> tuple[list, str]:
    """Exécute un tour ; renvoie (évènements, DSL persisté) comme le fait la session d'agent."""
    cvs = Canvas(dsl, TENANT)

    async def collect():
        evs = []
        async for ev in cvs.run(**kwargs):
            evs.append(ev)
            if sum(e["event"] == "node_finished" for e in evs) > MAX_NODE_FINISHED:
                pytest.fail(f"pause sautée, boucle : path={cvs.path[:12]}…")
        return evs

    return asyncio.run(collect()), str(cvs)


def _finished(evs) -> list:
    return [e["data"]["component_id"] for e in evs if e["event"] == "node_finished"]


def _assert_paused(evs, dsl):
    assert evs[-1]["event"] == "user_inputs", f"pas de pause : {[e['event'] for e in evs]}"
    assert set(evs[-1]["data"]["inputs"]) == {"decision", "retour"}, evs[-1]["data"]["inputs"]
    assert json.loads(dsl)["path"] == ["UserFillUp:Valid"]


def test_second_pass_on_userfillup_pauses_again():
    evs, dsl = _run(CANVAS_FILE.read_text(), query="go")
    _assert_paused(evs, dsl)
    assert _finished(evs).count("Message:Version") == 1

    for _ in range(2):
        evs, dsl = _run(dsl, query="", inputs=MODIFIER)
        _assert_paused(evs, dsl)
        assert _finished(evs).count("Message:Version") == 1, "la proposition doit être régénérée une fois"

    evs, dsl = _run(dsl, query="", inputs=VALIDER)
    assert evs[-1]["event"] == "workflow_finished"
    assert _finished(evs)[-1] == "Message:Fin"


def test_prefilled_userfillup_reached_by_pause_block_pauses():
    """Cas ciblé : formulaire déjà rempli (valeurs d'un tour précédent) au moment où le bloc pause l'atteint."""
    _, dsl = _run(CANVAS_FILE.read_text(), query="go")
    state = json.loads(dsl)
    state["components"]["UserFillUp:Valid"]["obj"]["params"]["inputs"]["decision"]["value"] = "Modifier"
    state["components"]["UserFillUp:Valid"]["obj"]["params"]["inputs"]["retour"]["value"] = "Plus court"
    evs, dsl = _run(json.dumps(state), query="", inputs=MODIFIER)
    _assert_paused(evs, dsl)


def test_linear_flow_unchanged():
    """Flux linéaire (UserFillUp atteint une seule fois) : pause puis fin, comme avant le correctif."""
    state = json.loads(CANVAS_FILE.read_text())
    cpns = state["components"]
    cpns["UserFillUp:Valid"]["downstream"] = ["Message:Fin"]
    cpns["Message:Fin"]["upstream"] = ["UserFillUp:Valid"]
    del cpns["Switch:Decision"]
    cpns["Message:Version"]["upstream"] = ["begin"]

    evs, dsl = _run(json.dumps(state), query="go")
    _assert_paused(evs, dsl)
    evs, _ = _run(dsl, query="", inputs=MODIFIER)
    assert evs[-1]["event"] == "workflow_finished"
    assert _finished(evs) == ["UserFillUp:Valid", "Message:Fin"]
