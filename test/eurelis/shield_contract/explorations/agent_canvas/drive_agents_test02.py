# Eurelis — driver de validation SSE de la famille d'agents test-02 (API agent pour le Shield).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Rejoue les 7 scénarios (dont 2 cycles pause/reprise user_inputs) contre un serveur RAGFlow
# et affiche la séquence d'événements observée. Sert de base d'analyse pour l'intégration
# Shield — voir docs/eurelis/features/spec-api-agent-shield.md.
#
# Exécution :
#   RAGFLOW_AUTH_TOKEN=<token Authorization> \
#   TEST02_IDS='{"prologue":"…","task-inputs":"…","userfillup-confirm":"…","userfillup-form":"…","message-variants":"…"}' \
#   python test/eurelis/shield_contract/explorations/agent_canvas/drive_agents_test02.py
#
# Variables d'environnement :
#   HOST_ADDRESS       base URL de l'API (défaut http://localhost:9380)
#   RAGFLOW_AUTH_TOKEN (requis) valeur de l'en-tête Authorization (JWT de login ou "Bearer <api key>")
#   TEST02_IDS         (requis) JSON {clé scénario -> agent_id}, ids imprimés par gen_agents_test02.py
import json
import os

import requests

BASE = os.getenv("HOST_ADDRESS", "http://localhost:9380")
TOKEN = os.environ["RAGFLOW_AUTH_TOKEN"]
HDRS = {"Authorization": TOKEN if TOKEN.startswith("Bearer ") or "." in TOKEN else f"Bearer {TOKEN}", "Content-Type": "application/json"}
AGENTS = json.loads(os.environ["TEST02_IDS"])


def run(agent_id, payload):
    body = {"agent_id": agent_id, "stream": True, **payload}
    events = []
    with requests.post(f"{BASE}/api/v1/agents/chat/completions", headers=HDRS, json=body, stream=True, timeout=120) as r:
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            events.append(json.loads(data))
    return events


def summarize(name, events):
    kinds = [e.get("event") for e in events]
    session = next((e.get("session_id") for e in events if e.get("session_id")), None)
    msg = "".join(e["data"].get("content", "") for e in events if e.get("event") == "message")
    ui = [e["data"] for e in events if e.get("event") == "user_inputs"]
    err = [e for e in events if e.get("code") not in (None, 0)]
    print(f"--- {name}")
    print(f"    events: {kinds}")
    if msg:
        print(f"    message: {msg[:220]!r}")
    if ui:
        print(f"    user_inputs: tips={ui[0].get('tips', '')[:120]!r} champs={list(ui[0].get('inputs', {}).keys())}")
    if err:
        print(f"    ERREURS: {err}")
    return session


# 1. prologue : run simple, la réponse doit streamer via Message
s = summarize("prologue / run simple", run(AGENTS["prologue"], {"question": "Dis bonjour en un mot"}))

# 2. task-inputs : sans inputs le run passe avec des valeurs vides (Begin ne suspend pas),
#    avec inputs dès le premier appel les valeurs sont résolues.
s = summarize("task-inputs / sans inputs (valeurs vides attendues)", run(AGENTS["task-inputs"], {"question": "démarrage"}))
if s:
    summarize(
        "task-inputs / re-run avec inputs",
        run(AGENTS["task-inputs"], {"session_id": s, "question": "démarrage", "inputs": {"sujet": {"value": "RAGFlow"}, "langue": {"value": "Français"}, "commentaire": {"value": ""}}}),
    )

# 3. userfillup-confirm : agent répond puis pause (user_inputs), reprise avec confirmation
s = summarize("userfillup-confirm / question", run(AGENTS["userfillup-confirm"], {"question": "Propose un titre de livre sur les canards"}))
if s:
    summarize("userfillup-confirm / reprise", run(AGENTS["userfillup-confirm"], {"session_id": s, "inputs": {"confirmation": {"value": "oui"}}}))

# 4. userfillup-form : pause formulaire multi-champs, reprise
s = summarize("userfillup-form / question", run(AGENTS["userfillup-form"], {"question": "je veux remplir le formulaire"}))
if s:
    summarize(
        "userfillup-form / reprise",
        run(AGENTS["userfillup-form"], {"session_id": s, "inputs": {"nom": {"value": "Vincent"}, "details": {"value": "test API"}, "choix": {"value": "B"}}}),
    )

# 5. message-variants : réponse directe sans LLM, variante aléatoire
summarize("message-variants / run", run(AGENTS["message-variants"], {"question": "coucou"}))
