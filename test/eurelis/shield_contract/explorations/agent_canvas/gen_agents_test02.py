# Eurelis — générateur de la famille d'agents test-02 (modes d'interaction du canvas agent).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Crée (ou met à jour, idempotent sur le titre) 5 agents isolant chacun un mode d'interaction
# utilisateur, en vue de l'analyse de l'API agent pour l'intégration Shield — voir
# docs/eurelis/features/spec-api-agent-shield.md :
#   - test-02-begin-prologue     : prologue du Begin conversationnel -> Agent -> Message
#   - test-03-begin-task-inputs  : Begin mode "task" avec inputs déclarés (line/options/paragraph)
#   - test-04-userfillup-confirm : Agent -> UserFillUp (pause user_inputs) -> Message
#   - test-05-userfillup-form    : formulaire multi-champs sans LLM
#   - test-06-message-variants   : Message seul, contenus alternatifs + {sys.query}
#
# Exécution (accès direct DB via la couche service, depuis la racine du repo) :
#   PYTHONPATH=$(pwd) .venv/bin/python test/eurelis/shield_contract/explorations/agent_canvas/gen_agents_test02.py
#
# Variables d'environnement :
#   TEST02_USER_ID       (requis) id de l'utilisateur propriétaire des agents
#   TEST02_BASE_AGENT_ID (requis) id d'un agent existant dont le nœud Agent (LLM) sert de modèle
import copy
import json
import os

from common import settings

settings.init_settings()

from common.misc_utils import get_uuid
from api.db.services.canvas_service import UserCanvasService

USER_ID = os.environ["TEST02_USER_ID"]
BASE_AGENT_ID = os.environ["TEST02_BASE_AGENT_ID"]

e, base = UserCanvasService.get_by_id(BASE_AGENT_ID)
assert e, f"Agent modèle introuvable: {BASE_AGENT_ID}"
base_dsl = base.dsl if isinstance(base.dsl, dict) else json.loads(base.dsl)
agent_components = [c for c in base_dsl["components"].values() if c["obj"]["component_name"] == "Agent"]
assert agent_components, "L'agent modèle doit contenir un nœud Agent"
AGENT_PARAMS = copy.deepcopy(agent_components[0]["obj"]["params"])

GLOBALS = {"sys.conversation_turns": 0, "sys.date": "", "sys.files": [], "sys.history": [], "sys.query": "", "sys.user_id": ""}


def skeleton():
    return {
        "components": {},
        "globals": copy.deepcopy(GLOBALS),
        "graph": {"nodes": [], "edges": []},
        "history": [],
        "memory": [],
        "messages": [],
        "path": [],
        "retrieval": [],
        "task_id": "",
        "variables": {},
    }


NODE_TYPES = {"Begin": "beginNode", "Agent": "agentNode", "Message": "messageNode", "UserFillUp": "ragNode"}


def add(dsl, cid, cname, params, name, x, y, upstream=None, downstream=None):
    dsl["components"][cid] = {
        "downstream": downstream or [],
        "obj": {"component_name": cname, "params": copy.deepcopy(params)},
        "upstream": upstream or [],
    }
    dsl["graph"]["nodes"].append(
        {
            "data": {"form": copy.deepcopy(params), "label": cname, "name": name},
            "dragging": False,
            "id": cid,
            "measured": {"height": 48, "width": 200},
            "position": {"x": x, "y": y},
            "selected": False,
            "sourcePosition": "right",
            "targetPosition": "left",
            "type": NODE_TYPES[cname],
        }
    )


def link(dsl, src, tgt):
    dsl["graph"]["edges"].append(
        {
            "data": {"isHovered": False},
            "id": f"xy-edge__{src}start-{tgt}end",
            "source": src,
            "sourceHandle": "start",
            "target": tgt,
            "targetHandle": "end",
        }
    )


def field(key, ftype="line", optional=False, options=None):
    return {"key": key, "name": key, "optional": optional, "options": options or [], "type": ftype, "value": ""}


agents = []

# ---------------------------------------------------------------- A. prologue
dsl = skeleton()
add(dsl, "begin", "Begin", {
    "enablePrologue": True,
    "prologue": "Bienvenue sur test-02-begin-prologue ! Posez-moi une question pour tester le message d'accueil.",
    "mode": "conversational",
    "inputs": {},
}, "begin", 50, 200, downstream=["Agent:Test02Prologue"])
add(dsl, "Agent:Test02Prologue", "Agent", AGENT_PARAMS, "Agent_0", 350, 200,
    upstream=["begin"], downstream=["Message:Test02PrologueReply"])
add(dsl, "Message:Test02PrologueReply", "Message", {
    "content": ["{Agent:Test02Prologue@content}"], "stream": True,
}, "Reply", 650, 200, upstream=["Agent:Test02Prologue"])
link(dsl, "begin", "Agent:Test02Prologue")
link(dsl, "Agent:Test02Prologue", "Message:Test02PrologueReply")
agents.append(("test-02-begin-prologue",
               "Teste le message d'accueil (prologue) du nœud Begin en mode conversationnel : "
               "Begin(prologue) -> Agent -> Message.", dsl))

# ---------------------------------------------------------- B. task + inputs
dsl = skeleton()
add(dsl, "begin", "Begin", {
    "enablePrologue": True,
    "prologue": "Agent test-03-begin-task-inputs : fournissez 'sujet' et 'langue' pour démarrer.",
    "mode": "task",
    "inputs": {
        "sujet": field("sujet", "line", optional=False),
        "langue": field("langue", "options", optional=False, options=["Français", "English"]),
        "commentaire": field("commentaire", "paragraph", optional=True),
    },
}, "begin", 50, 200, downstream=["Message:Test02TaskEcho"])
add(dsl, "Message:Test02TaskEcho", "Message", {
    "content": ["Paramètres reçus au démarrage :\n- sujet : {begin@sujet}\n- langue : {begin@langue}\n- commentaire : {begin@commentaire}"],
    "stream": True,
}, "Echo des inputs", 350, 200, upstream=["begin"])
link(dsl, "begin", "Message:Test02TaskEcho")
agents.append(("test-03-begin-task-inputs",
               "Teste le démarrage en mode 'task' avec des inputs déclarés sur Begin (line, options, "
               "paragraph optionnel). NB vérifié : Begin ne suspend jamais le run — les inputs "
               "doivent être fournis dès le premier appel completions.", dsl))

# ------------------------------------------------------------ C. attente/confirm
dsl = skeleton()
add(dsl, "begin", "Begin", {
    "enablePrologue": True,
    "prologue": "Agent test-04-userfillup-confirm : je réponds puis je vous demande confirmation.",
    "mode": "conversational",
    "inputs": {},
}, "begin", 50, 200, downstream=["Agent:Test02Confirm"])
add(dsl, "Agent:Test02Confirm", "Agent", AGENT_PARAMS, "Agent_0", 350, 200,
    upstream=["begin"], downstream=["UserFillUp:Test02Confirm"])
add(dsl, "UserFillUp:Test02Confirm", "UserFillUp", {
    "enable_tips": True,
    "tips": "Voici ma proposition :\n{Agent:Test02Confirm@content}\n\nConfirmez-vous ? (oui/non)",
    "inputs": {"confirmation": field("confirmation", "line", optional=False)},
    "outputs": {"confirmation": field("confirmation", "line", optional=False)},
}, "Attente confirmation", 650, 200, upstream=["Agent:Test02Confirm"], downstream=["Message:Test02ConfirmReply"])
add(dsl, "Message:Test02ConfirmReply", "Message", {
    "content": ["Vous avez répondu : {UserFillUp:Test02Confirm@confirmation}. Fin du test."],
    "stream": True,
}, "Reply", 950, 200, upstream=["UserFillUp:Test02Confirm"])
link(dsl, "begin", "Agent:Test02Confirm")
link(dsl, "Agent:Test02Confirm", "UserFillUp:Test02Confirm")
link(dsl, "UserFillUp:Test02Confirm", "Message:Test02ConfirmReply")
agents.append(("test-04-userfillup-confirm",
               "Teste le cycle attente de réponse utilisateur : Agent -> UserFillUp (tips référençant "
               "la sortie de l'Agent, un champ requis) -> Message. L'API suspend le run "
               "(événement user_inputs) puis reprend avec la réponse.", dsl))

# ------------------------------------------------------------ D. formulaire multi-champs
dsl = skeleton()
add(dsl, "begin", "Begin", {
    "enablePrologue": True,
    "prologue": "Agent test-05-userfillup-form : envoyez un message, je vous présenterai un formulaire.",
    "mode": "conversational",
    "inputs": {},
}, "begin", 50, 200, downstream=["UserFillUp:Test02Form"])
add(dsl, "UserFillUp:Test02Form", "UserFillUp", {
    "enable_tips": True,
    "tips": "Merci de renseigner le formulaire (vous avez dit : {sys.query})",
    "inputs": {
        "nom": field("nom", "line", optional=False),
        "details": field("details", "paragraph", optional=True),
        "choix": field("choix", "options", optional=False, options=["A", "B", "C"]),
    },
    "outputs": {
        "nom": field("nom", "line", optional=False),
        "details": field("details", "paragraph", optional=True),
        "choix": field("choix", "options", optional=False, options=["A", "B", "C"]),
    },
}, "Formulaire", 350, 200, upstream=["begin"], downstream=["Message:Test02FormReply"])
add(dsl, "Message:Test02FormReply", "Message", {
    "content": ["Formulaire reçu :\n- nom : {UserFillUp:Test02Form@nom}\n- détails : {UserFillUp:Test02Form@details}\n- choix : {UserFillUp:Test02Form@choix}"],
    "stream": True,
}, "Reply", 650, 200, upstream=["UserFillUp:Test02Form"])
link(dsl, "begin", "UserFillUp:Test02Form")
link(dsl, "UserFillUp:Test02Form", "Message:Test02FormReply")
agents.append(("test-05-userfillup-form",
               "Teste un formulaire multi-champs en attente de réponse (line requis, paragraph "
               "optionnel, options requis) sans passage par un LLM : Begin -> UserFillUp -> Message.", dsl))

# ------------------------------------------------------------ E. variantes de Message
dsl = skeleton()
add(dsl, "begin", "Begin", {
    "enablePrologue": True,
    "prologue": "Agent test-06-message-variants : je réponds avec une variante aléatoire.",
    "mode": "conversational",
    "inputs": {},
}, "begin", 50, 200, downstream=["Message:Test02Variants"])
add(dsl, "Message:Test02Variants", "Message", {
    "content": [
        "Variante 1 — vous avez dit : {sys.query}",
        "Variante 2 — votre message était : {sys.query}",
        "Variante 3 — j'ai bien reçu : {sys.query}",
    ],
    "stream": True,
}, "Variantes", 350, 200, upstream=["begin"])
link(dsl, "begin", "Message:Test02Variants")
agents.append(("test-06-message-variants",
               "Teste le nœud Message seul (réponse directe, sans LLM) avec plusieurs contenus "
               "alternatifs (choix aléatoire) et référence à {sys.query}.", dsl))

created = []
for title, description, dsl in agents:
    existing = UserCanvasService.query(user_id=USER_ID, title=title)
    if existing:
        UserCanvasService.update_by_id(existing[0].id, {"dsl": dsl, "description": description})
        created.append((title, existing[0].id, "updated"))
        continue
    cid = get_uuid()
    UserCanvasService.insert(
        id=cid,
        user_id=USER_ID,
        title=title,
        description=description,
        permission="me",
        canvas_category="agent_canvas",
        tags="test-02",
        dsl=dsl,
    )
    created.append((title, cid, "created"))

for title, cid, status in created:
    print(f"{status}: {title} -> {cid}")
