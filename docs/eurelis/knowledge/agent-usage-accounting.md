---
title: "Agents canvas : comptabilisation des tokens et de la durée"
type: knowledge
status: reference
date: 2026-10-12
---

# Agents canvas : comptabilisation des tokens et de la durée

Depuis `v0.26.3-eurelis.14` (AILAB-43), chaque exécution d'un agent canvas est comptabilisée à
deux endroits :

- dans la session (`api_4_conversation.tokens` / `duration`) ;
- dans les statistiques d'usage (`usage_log`, `source="agent"`).

Jusqu'à `eurelis.13`, ces deux compteurs restaient à zéro : la consommation des agents était
invisible.

> **En bref.** Une exécution = un appel de complétion d'agent, c'est-à-dire un départ ou une reprise
> après une pause `UserFillUp`. Chaque exécution écrit **une** ligne `usage_log` (`llm`) et
> incrémente la session, **pauses comprises**. Les tokens comptés sont ceux des appels de chat LLM.
> La durée est le temps réel de l'exécution, en millisecondes.

---

## 1. Le constat (préprod Synerga, eurelis.13)

Parcours complet de l'agent CRM v1.1 piloté par l'API, comme le fait le Shield : une création de
session, puis 5 complétions SSE (4 pauses et une fin), soit environ 7 minutes de LLM.

| Compteur | Valeur constatée |
|---|---|
| `api_4_conversation.round` | 1 → 5 (correct) |
| `api_4_conversation.tokens` / `duration` | `0` / `0.0` à chaque tour |
| `usage_log` | aucune ligne |
| `workflow_finished.usage` (dernière étape) | `total_tokens: 26822` |

Le moteur calculait bien l'usage, mais personne ne le lisait. De plus, les étapes arrêtées sur une
pause n'émettent pas de `workflow_finished` : leur usage n'apparaissait nulle part.

## 2. Ce qui est compté

| Élément | Compté dans la ligne `llm` | Remarque |
|---|---|---|
| Appels de chat de `LLMBundle` (`LLM`, `Agent` et ses tours d'outils, `Categorize`, sous-agents, réécriture de requête…) | oui | Collecteur `token_usage_sink` installé par `Canvas.run`, alimenté par `LLMBundle._report_usage` |
| Embedding de requête de l'outil `Retrieval` | **non** | Journalisé à part par `eurelis_usage_log` (`source="agent"`, `token_type="embedding"`), donc pas de double comptage. `encode` / `encode_queries` n'écrivent pas dans le collecteur. |
| Rerank, image2text, synthèse vocale | non | Voir les limites (§ 6) |

Total = `canvas._run_usage_payload()["total_tokens"]`, lu **après** le flux : pas besoin de
`workflow_finished`. La sémantique de `workflow_finished.usage` est inchangée : c'est toujours le
total de l'exécution courante.

## 3. Quand

Module `api/db/services/eurelis_agent_usage.py` :

- `AgentRunMeter(canvas)` est créé juste avant `canvas.run` ;
- `stop()` fige la durée et les tokens (idempotent) ;
- `log_agent_run()` écrit la ligne `usage_log`. Cette fonction est synchrone et ne lève jamais d'exception.

| Chemin | Appelant | `append_message(tokens, duration)` | Ligne `usage_log` |
|---|---|---|---|
| Session `agent` (Shield, `/agents/chat/completions` avec `session_id`, et mode OpenAI-compatible) | `api/db/services/canvas_service.py::completion` | après le flux, comme avant | dans le `finally` du flux : pause, fin, erreur d'un composant, déconnexion du client |
| Session `workflow` | `api/apps/restful_apis/agent_api.py::_run_workflow_session` | dans `persist_workflow_session` (si `final_ans`) | dans le `finally` (SSE et non-stream) |

Une exécution qui s'arrête sur une pause écrit donc sa ligne et incrémente la session. Une session
de 5 exécutions donne 5 lignes et `round` +5.

## 4. Sur quel utilisateur

| Champ `usage_log` | Valeur |
|---|---|
| `user_id` | `user_id` de la **session** : celui transmis par l'appelant à la création de la session (le Shield passe l'utilisateur final) |
| `resource_id` | id de l'agent |
| `object_id` | id de la session |
| `source` / `token_type` | `agent` / `llm` |
| `model` / `provider` | vides (voir § 6) |

C'est cohérent avec [les modèles du propriétaire](./agent-models-owner-tenant.md) : les tokens
sont consommés sur les clés du propriétaire du canvas, mais **attribués** à l'appelant.

Unités : `tokens` en tokens, `duration` en millisecondes. C'est la même unité que les lignes `chat`
(`duration_ms`), dans `usage_log` comme dans `api_4_conversation`.

## 5. Contexte asynchrone : les appels hors du fil principal

Le collecteur est une `ContextVar` qui porte un dictionnaire partagé. Tout code exécuté avec une
copie du contexte écrit donc dans le même total. Points vérifiés sur le chemin agent :

| Mécanisme | Copie du contexte |
|---|---|
| `Canvas._run_batch` (composants synchrones dans le pool du canvas) | oui (`contextvars.copy_context()`) |
| `common.misc_utils.thread_pool_exec` (outils de l'agent, `invoke_async` des composants synchrones) | oui |
| `asyncio.run` / `asyncio.to_thread` dans un composant | oui (la tâche hérite du contexte courant) |
| `LLMBundle._run_coroutine_sync`, `_sync_from_async_stream`, `_bridge_sync_stream` (threads nus) | **non**, mais ces fonctions ne sont pas appelées sur le chemin agent (seul `rag/app/resume.py` les utilise, à l'ingestion) |

Aucun appel du chemin agent n'échappe donc au collecteur. Le test unitaire déclare une partie de
l'usage depuis un `thread_pool_exec` imbriqué dans le pool du canvas.

**`calls: 1` pour l'étape Retouche (105 s, préprod).** `calls` compte les appels de chat LLM, pas
les composants. Un seul appel `Agent` sans outil qui génère 11 574 tokens de complétion dure de
l'ordre de 100 s avec Claude via Bedrock. Le chiffre est donc cohérent et ne signale pas une perte
d'appels.

## 6. Limites connues

- **`model` / `provider` vides** : le collecteur n'agrège qu'un total, et une exécution peut
  appeler plusieurs modèles. `stats_by_model` range donc les agents sous un modèle vide.
- **Rerank, image2text et synthèse vocale** des composants d'agent ne passent pas par le
  collecteur : ils ne sont pas comptés dans la ligne `llm`, et aucune autre ligne ne les couvre.
- **Déconnexion du client** au milieu d'un flux de session `agent` : la ligne `usage_log` est
  écrite (dans le `finally`), mais la session n'est pas persistée (comportement upstream
  inchangé). `api_4_conversation` n'est donc pas incrémentée pour cette exécution.
- **Chemin workflow sans réponse** (`final_ans` vide) : la ligne `usage_log` est écrite, mais
  `append_message` n'est pas appelé (comportement existant).
- **Exécution sans LLM** (agent de contrat, boucle sans modèle) : une ligne est écrite avec
  `tokens = 0` et la durée réelle.
- **Historique non rattrapé** : les sessions d'agent antérieures à `eurelis.14` restent à 0.

## 7. Tests

| Test | Type | Ce qu'il vérifie |
|---|---|---|
| `test/eurelis/unit/test_agent_usage_accounting.py` | Unitaire, sans stack, `Canvas.run` réel avec composants « LLM » factices | `append_message` reçoit des tokens et une durée non nuls, y compris sur une pause. Une ligne `usage_log` par exécution (`source`, `user_id`, `object_id`). Ligne écrite aussi sur erreur de composant. Usage déclaré depuis un thread. `workflow_finished.usage` inchangé. Embedding absent du collecteur. |
| `test/eurelis/eurelis_fixes/test_agent_usage_accounting_e2e.py` | E2E `p0`, LLM Ollama, `fixtures/agent_usage_canvas.json` | Départ → pause → reprise → fin. `round` +2. Tokens de session = somme des deux exécutions (pause comprise). Durée > 0. 2 lignes `usage_log` `agent`, dont la 2e égale à `workflow_finished.usage.total_tokens`. |

Les deux tests sont rouges sur `v0.26.3-eurelis.13` : session à 0 tokens et aucune ligne
`usage_log`.
