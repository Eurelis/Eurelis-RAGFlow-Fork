# Changelog Eurelis

Historique des modifications spécifiques au fork Eurelis de [RAGFlow](https://github.com/infiniflow/ragflow).

---

## [v0.26.3-eurelis.15] - 2026-10-26

Basé sur RAGFlow `v0.26.3`. Trois correctifs pour la prod Synerga / Diligentia :
- les agents qui dépassent leur nombre maximal de tours d'outils ne finissent plus en `**ERROR**` sur Bedrock (AILAB-46) ;
- les PDF joints au chat gardent leur disposition en colonnes (AILAB-45) ;
- les conteneurs de la sandbox de code sont recréés après chaque exécution (AILAB-21).

### Fixed
- **Agent en échec après `max_rounds` tours d'outils sur Bedrock** (`rag/llm/chat_model.py`, `LiteLLMBase.async_chat_with_tools` et `Base.async_chat_with_tools`, nouveau module Eurelis `rag/llm/eurelis_tool_rounds.py`). Constaté en prod Diligentia les 19 et 22/10 : l'étape `Agent:PartieChiffree` de l'agent CRM (outil CodeExec, `max_rounds` 6, aval VariableAssigner, donc chemin non-streaming) échouait au bout de 7 à 10 min et d'environ 1 M de tokens avec `litellm.UnsupportedParamsError: Bedrock doesn't support tool calling without `tools=` param specified.`

  **Cause** : dans le chemin non-streaming, si le modèle appelait encore un outil au dernier tour, le repli « Exceed max rounds » appelait `async_chat` / `_async_chat`, qui n'envoient pas `tools`. Or l'historique contient des blocs tool_use/tool_result, et Bedrock Converse refuse une telle requête.

  **Correctif** : le dernier appel déclare les outils (`tools`, `tool_choice="auto"`), comme le chemin streaming qui n'avait pas le bug.
  - Les `tool_calls` de ce dernier appel ne sont jamais exécutés.
  - S'il ne produit aucun texte, l'agent répond « L'agent a dépassé N tours d'outils sans produire de réponse. », sans lever d'exception.
  - La consigne de fin est explicite : « Exceed max rounds: N. Do not call any tool anymore: answer now with the information already gathered. ». Elle est aussi utilisée dans les deux chemins streaming.
  - L'usage du dernier appel est agrégé comme celui des autres tours (comptage d'`eurelis.14` inchangé), et le démasquage PII est conservé.
  - Ni `litellm.modify_params` (global), ni `tool_choice="none"` (non pris en charge par Converse, retiré sans bruit par `drop_params`).

  Seules ces deux méthodes avaient le défaut : les quatre occurrences de « Exceed max rounds » sont dans `Base` et `LiteLLMBase`, et aucune autre classe ne surcharge la boucle d'outils.

  **Changement de comportement** : si le dernier appel lève une exception, elle passe par la politique de retry de la boucle, comme dans le chemin streaming. Avant, `async_chat` l'avalait et la renvoyait directement en `**ERROR**`.
- **PDF joints au chat lus sans leurs colonnes** (`deepdoc/parser/pdf_parser.py`, `rag/app/naive.py`, `api/db/services/file_service.py`, nouveau module Eurelis `deepdoc/parser/eurelis_pdf_layout_text.py`). Signalé sur Synerbot (SM-259) : une balance comptable PDF convertie en Excel avait ses 100 soldes créditeurs saisis en positif. Le mode par défaut de `page.extract_text()` détachait chaque montant de son en-tête Débiteur, Créditeur ou N-1.

  **Correctif** :
  - `FileService.parse` (pièces jointes de chat et d'agent) lit les PDF en mode `layout` de pypdf, avec repli sur le mode par défaut si erreur ou texte vide.
  - Seuls les espaces de fin de ligne et les lignes vides en série sont retirés : l'alignement reste intact.
  - L'ingestion des bases de connaissances est inchangée (`PlainParser()` reste en mode par défaut).

  **Surcoût** : ×3,3 en caractères mais **+10 % en tokens** sur la balance de 11 pages, +5 % sur les PDF Diligentia. Caractères U+E0xx et chiffres identiques (cf. AILAB-26).
- **Sandbox de code : état partagé entre exécutions** (`agent/sandbox/executor_manager/core/container.py`). Le conteneur revenait dans le pool après la seule suppression de `/workspace/<task_id>`. `/tmp` et les processus d'arrière-plan survivaient donc jusqu'à l'exécution suivante, qui peut venir d'un autre cabinet (VM sandbox commune aux instances Synerga). `release_container` détruit et recrée désormais le conteneur, en tâche de fond (AILAB-21).

### Tests
- **Unitaires — dernier tour d'outils** (`test/eurelis/unit/test_tool_loop_max_rounds.py`, 5 tests sans réseau). LiteLLM et client OpenAI sont mockés : le faux fournisseur refuse, comme Bedrock, un historique d'outils sans `tools=`.
  - Chemin non-streaming avec `max_rounds=1` et un outil appelé à chaque tour, pour `LiteLLMBase` et `Base` : chaque appel déclare `tools`, aucun outil n'est exécuté au dernier tour, la réponse explicite est renvoyée sans `**ERROR**`, et les tokens sont agrégés sur les 3 appels.
  - Même scénario quand le dernier appel renvoie du texte : ce texte est rendu, et `last_usage` couvre tous les tours.
  - Chemin streaming : repli inchangé (appel avec `tools`, texte relayé, usage agrégé).

  Les 4 tests non-streaming sont rouges sans le correctif.
- **E2E — colonnes des PDF joints** (`test/eurelis/eurelis_fixes/test_chat_pdf_layout_columns_e2e.py`, `p1`). `FileService.parse` est exécuté dans le conteneur sous test, sur des PDF synthétiques sans donnée client. Les montants restent sous leur en-tête ; les PDF de texte simple et scannés, ainsi que l'ingestion KB, sont inchangés. Rouge sur `eurelis.14`, vert avec le correctif. Complété par des tests unitaires (`test/eurelis/unit/test_pdf_layout_text.py`).

Suite complète sur conteneur patché (AILAB-45 et AILAB-46) : 159 passed, 3 skipped (attendus), contrats Shield `test_agents_*` et comptage des agents verts.

---

## [v0.26.3-eurelis.14] - 2026-10-12

Basé sur RAGFlow `v0.26.3`. Deux correctifs des agents canvas consommés par le Shield (AILAB-43) : les **boucles de validation** font de nouveau une pause à chaque passage, et la **consommation des agents** (tokens, durée) est enfin comptabilisée.

Boucles de validation (agent CRM v1.2) : L'agent CRM propose plusieurs tours de modification par étape : `Agent:X` → `UserFillUp:ValidX` {decision Valider|Modifier, retour} → `Switch` (« Modifier » renvoie sur `Agent:X`). Au 2e passage sur le même `UserFillUp`, le moteur ne faisait plus de pause. Le `Switch` relisait le `Modifier` du tour précédent et le flux bouclait sans fin, en consommant des tokens LLM à chaque tour.

### Fixed
- **Pause `UserFillUp` sautée au 2e passage, boucle infinie** (`agent/canvas.py`, `Canvas._run_impl`, bloc de détection de pause) : la pause n'a lieu que si un champ du formulaire n'est pas satisfait. Or les `inputs` du `UserFillUp` gardaient les valeurs du tour précédent, persistées dans le DSL de la session. Au début d'un tour, seules les sorties des composants du `path` sont remises à zéro. Correctif d'une ligne : `o.reset()` avant `o.invoke()`, qui vide les entrées et les sorties du formulaire avant de l'évaluer. Le bug ne se déclenchait que si tous les champs avaient reçu une valeur : un champ facultatif laissé à `None` forçait la pause.

  **Portée vérifiée** :
  - le `UserFillUp` auquel l'utilisateur vient de répondre n'est pas concerné : il tourne dans le premier lot de la reprise, avant le bloc de pause ;
  - un flux linéaire, où chaque `UserFillUp` n'est atteint qu'une fois, garde le même comportement ;
  - aucune valeur d'entrée par défaut légitime n'est perdue : le front n'écrit pas de `value` dans les entrées d'un `UserFillUp`, et `fillup.py` n'en lit aucune.

  Documenté dans `docs/eurelis/knowledge/agent-userfillup-repeat-pause.md`.
- **Tokens et durée des agents canvas jamais comptabilisés** (`api/db/services/canvas_service.py`, `api/apps/restful_apis/agent_api.py`, nouveau module Eurelis `api/db/services/eurelis_agent_usage.py`). Constat en préprod Synerga (`eurelis.13`) sur un parcours complet de l'agent CRM via l'API : `api_4_conversation.tokens = 0`, `duration = 0.0` et aucune ligne `usage_log`, alors que `workflow_finished.usage` annonçait 26 822 tokens. Causes :
  - aucun appelant du chemin agent ne passait `tokens` / `duration` à `append_message` ;
  - le chemin session (celui du Shield) n'écrivait jamais dans `usage_log` ;
  - le chemin workflow écrivait `tokens=0, duration=0.0` en dur.

  Correctif : `AgentRunMeter` mesure chaque exécution (départ ou reprise après pause). Il lit la durée réelle et le total du collecteur de `Canvas.run` (`_run_usage_payload()`) après le flux, sans dépendre de `workflow_finished`. Ces valeurs sont passées à `append_message`, et `log_agent_run` écrit **une ligne `usage_log` par exécution** dans le `finally`, pauses, erreurs et déconnexions comprises : `source="agent"`, `token_type="llm"`, `resource_id` = agent, `object_id` = session, `user_id` = celui de la session (attribution chez l'appelant, modèles chez le propriétaire). Durée en millisecondes, comme les lignes `chat`. `model` / `provider` restent vides : le collecteur n'agrège qu'un total.

  **Pas de double comptage** : seuls les appels de chat de `LLMBundle` alimentent le collecteur, et l'embedding de `Retrieval` reste journalisé à part (`token_type="embedding"`). `workflow_finished.usage` est inchangé.

  **Contexte asynchrone vérifié** : `_run_batch`, `thread_pool_exec` et `asyncio.run` propagent le collecteur, aucun appel LLM du chemin agent n'y échappe. Le `calls: 1` de l'étape Retouche (105 s) correspond à un seul appel générant 11 574 tokens.

  **Limites** : rerank, image2text et synthèse vocale ne sont pas comptés ; l'historique antérieur reste à 0. Documenté dans `docs/eurelis/knowledge/agent-usage-accounting.md`.

### Tests
- **Unitaires** (`test/eurelis/unit/test_userfillup_repeat_pause.py`, 3 tests sans stack, moteur `Canvas.run` réel avec un registre limité à Begin/UserFillUp/Message/Switch) :
  - cycle départ → Modifier → Modifier → Valider : une pause à chaque passage, avec les champs `decision` et `retour` ;
  - formulaire pré-rempli atteint par le bloc de pause : la pause est émise ;
  - flux linéaire inchangé.

  Les deux premiers sont rouges sans la ligne `o.reset()`.
- **E2E — boucle de validation** (`test/eurelis/eurelis_fixes/test_userfillup_repeat_pause_e2e.py`, `p0`, canvas sans LLM `test/eurelis/fixtures/agent_userfillup_loop_canvas.json`) :
  - parcours via les sessions d'agent et `/agents/chat/completions` en SSE : départ → pause, Modifier → pause, Modifier → pause, Valider → `workflow_finished` ;
  - à chaque pause : `path[0]` persisté = `UserFillUp:Valid`, `Message:Version` exécuté une seule fois de plus ;
  - flux SSE borné (12 `node_finished`, timeout de lecture 30 s) : la version boguée échoue proprement au lieu de bloquer la suite.

  Vérifié **rouge** sur l'image `v0.26.3-eurelis.13` (« flux non borné, pause sautée » dès la 1re reprise « Modifier », en 11 s) et **vert** avec le correctif.
- **Unitaires — usage des agents** (`test/eurelis/unit/test_agent_usage_accounting.py`, 5 tests sans stack, `Canvas.run` réel avec composants « LLM » factices et services DB mockés) :
  - `append_message` reçoit des tokens et une durée non nuls, y compris quand l'exécution s'arrête sur une pause ;
  - une ligne `usage_log` `agent` par exécution (utilisateur de la session, agent, session) ;
  - ligne écrite aussi quand un composant échoue ;
  - usage déclaré depuis un `thread_pool_exec` imbriqué dans le pool du canvas ;
  - `workflow_finished.usage` inchangé ;
  - embedding absent du collecteur.

  Les 3 tests de complétion sont rouges sans le correctif de `canvas_service.py`.
- **E2E — usage des agents** (`test/eurelis/eurelis_fixes/test_agent_usage_accounting_e2e.py`, `p0`, canvas `test/eurelis/fixtures/agent_usage_canvas.json` avec Begin → LLM → UserFillUp → LLM → Message sur Ollama) :
  - départ → pause → reprise → fin ;
  - session : `round` +2, tokens égaux à la somme des deux exécutions (pause comprise), durée > 0 ;
  - `/usage-stats/me/session/<id>` : 2 lignes `agent`, dont la 2e égale `workflow_finished.usage.total_tokens`.

  Vérifié **rouge** sur l'image `v0.26.3-eurelis.13` (tokens de session 0, « Session not found » côté `usage_log`) et **vert** avec le correctif.

Suite complète sur conteneur patché (les deux correctifs) : 124 passed, 3 skipped (attendus), contrats Shield `test_agents_*` verts.

---

## [v0.26.3-eurelis.13] - 2026-10-11

Basé sur RAGFlow `v0.26.3`. Les **agents canvas utilisent désormais les modèles du propriétaire du canvas**, comme les assistants de chat (AILAB-43). Recette Shield v0.20.1 sur la sandbox ai-lab (image `v0.26.3-eurelis.12`) : un utilisateur provisionné par le Shield, membre de l'équipe du propriétaire mais sans aucun fournisseur de modèles, échouait dès `POST /api/v1/agents/{id}/sessions` avec `LookupError: Provider OpenAI not found for model gpt-4.1@OpenAI.`. Le seul contournement consistait à recopier la clé de la plateforme dans chaque compte.

### Fixed
- **Agents partagés inexécutables par un membre sans fournisseur de modèles** (`agent/canvas.py`, nouveau module Eurelis `agent/eurelis_model_tenant.py`) : l'upstream résolvait tous les modèles d'un agent sur le tenant de l'**appelant**, alors que les assistants résolvent les leurs sur le tenant du propriétaire (`dialog.tenant_id`). Nouvelle méthode `Canvas.get_model_tenant_id()`, qui vaut le propriétaire du canvas (`user_canvas.user_id`, lu une seule fois par canvas). Elle retombe sur l'appelant sans `canvas_id`, si le canvas est introuvable ou si l'interrupteur est coupé. `Canvas._id` est désormais affecté **avant** le chargement du DSL : `LLM` et `Agent` résolvent leur modèle dans leur constructeur, d'où l'échec dès la création de session. Points basculés sur le propriétaire :
  - chat et image2text de `LLM`, `Agent`, `Categorize` et `Browser` ;
  - synthèse vocale du `Message` en lecture automatique ;
  - chat de l'outil `Retrieval` (filtre de métadonnées auto/semi-auto, `toc_enhance`, `use_kg`).

  L'embedding de `Retrieval` passe sur le tenant de la base (`kbs[0].tenant_id`), comme les assistants et le rerank du même outil.
  **Changement de comportement** :
  - les tokens sont consommés sur les clés du propriétaire ;
  - `TenantLLM.used_tokens` est incrémenté sur l'instance du propriétaire ;
  - un membre qui a ses propres fournisseurs utilise les modèles du propriétaire lorsqu'il exécute l'agent d'un autre.

  **Ce qui reste chez l'appelant** :
  - fichiers déposés (`/agents/{id}/upload`, relus via `created_by`) ;
  - pièces générées (`Message`, `DocsGenerator`, `ExcelProcessor`) et leur téléchargement ;
  - sessions (`user_id`, `round`/`tokens`/`duration`), `sys.user_id` et attribution `usage_log` Eurelis ;
  - recherche d'une base par nom dans `Retrieval` ;
  - contrôle d'accès `UserCanvasService.accessible`.

  **Inchangés** : les pipelines d'ingestion (`Pipeline`, `rag/flow/`) et `PipelineChunker`.

  Interrupteur `EURELIS_AGENT_MODELS_FROM_OWNER` (défaut `true`) : `false` rétablit le comportement upstream sans redéploiement de code. Documenté dans `docs/eurelis/knowledge/agent-models-owner-tenant.md`.

### Tests
- **Unitaires** (`test/eurelis/unit/test_agent_model_tenant.py`, 16 tests sans stack, registre de composants factice) :
  - tenant des modèles = propriétaire, `get_tenant_id()` = appelant ;
  - une seule lecture du propriétaire ;
  - tenant disponible pendant la construction des composants ;
  - repli sur l'appelant sans `canvas_id`, si le canvas est introuvable ou si la lecture échoue ;
  - valeurs de l'interrupteur ;
  - `Graph` (ingestion) inchangé.
- **E2E — membre sans fournisseur** (`test/eurelis/eurelis_fixes/test_agent_models_owner_tenant_e2e.py`, `p0`) :
  - mise en place : le propriétaire publie et partage `team` un agent Begin(question, document:file) → LLM (Ollama) → Message markdown ; le coéquipier se voit retirer tous ses fournisseurs ;
  - le coéquipier crée une session, dépose un fichier, exécute l'agent et obtient une réponse LLM ;
  - le contenu du fichier est relu par l'agent ;
  - le coéquipier télécharge la pièce générée ;
  - le rattachement de la session est inchangé.

  Vérifié **rouge** sur l'image `v0.26.3-eurelis.12` (`LookupError: Provider Ollama not found for model qwen2.5:0.5b@local@Ollama.` à la création de session) et **vert** avec le correctif. Le coéquipier est enrôlé par une fixture de module, et non par la fixture de session `agent_member_token` : l'instancier depuis `eurelis_fixes` enrôlerait B avant que `test_admin_teams` ne l'en retire, ce qui ferait échouer `test_member_lists_published_team_agent`. Création idempotente d'agent factorisée dans `test/eurelis/libs/agents.py` (`ensure_agent`), contrats Shield inchangés. Suite complète sur conteneur patché : 112 passed, 3 skipped (attendus).

---

## [v0.26.3-eurelis.12] - 2026-10-11

Basé sur RAGFlow `v0.26.3`. Correctif de la **persistance des sessions d'agent** : depuis l'instrumentation usage-stats (v0.26.1-eurelis.3), aucune session d'agent ni conversation API n'était enregistrée — l'historique restait vide, une pause `UserFillUp` ne pouvait pas être reprise et les compteurs `round`/`tokens`/`duration` n'étaient jamais incrémentés. Bloquant pour les agents canvas consommés par le Shield (AILAB-43).

### Fixed
- **Sessions d'agent jamais persistées** (`api/db/services/api_service.py`, `API4ConversationService.append_message`) — le `with DB.atomic()` ajouté par Eurelis autour de `update_by_id` (lui-même décoré `@DB.connection_context()`, dont la sortie ferme la connexion) levait systématiquement `peewee.OperationalError: Attempting to close database while transaction is open` : rollback de la mise à jour à chaque message. Touchait tous les appelants — complétions d'agent (`canvas_service`, `restful_apis/agent_api.py`) et conversations API (`conversation_service`). Retour à la structure upstream (pas de transaction englobante) en conservant les incréments Eurelis `tokens`/`duration` de `append_message`. *Correction (eurelis.14) : ces incréments ne servaient qu'aux conversations API ; aucun appelant du chemin agent ne leur passait de valeur, et les sessions d'agent restaient à 0 tokens et 0 durée jusqu'à `v0.26.3-eurelis.14`.*

### Tests
- **Contrats Shield des agents canvas** (`test/eurelis/shield_contract/test_agents_*.py`, feature 031 du Shield) : liste (catégorie agent, `release_time`, sans `dsl`), détail et versions publiées, sessions (release, filtre `user_id`, suppression), upload et téléchargement d'une pièce générée, flux SSE départ → pause `UserFillUp` → reprise. Agent de contrat **sans LLM** (`test/eurelis/fixtures/agent_contract_canvas.json`) créé chez l'utilisateur de test, publié et partagé `team`, exécuté avec la clé d'un membre de l'équipe (helpers `test/eurelis/libs/agents.py`, schémas `test/eurelis/schemas/agents.py`). `test_pause_is_persisted` et `test_resume_does_not_replay_and_finishes` gardent la régression ci-dessus.

---

## [v0.26.3-eurelis.11] - 2026-09-13

Basé sur RAGFlow `v0.26.3`. Correctif du **prompt système contenant des accolades littérales** (AILAB-35) : un assistant rattaché à une base de connaissances répondait `**ERROR**: ' font-family'` à toute question dès que son prompt contenait du CSS, du JavaScript, du JSON ou un `${x}`, alors que le même prompt passait sans base. Reproduit en production Synerga sur « Expert Facturation Electronique » après ajout du prompt Office (artefacts HTML, AILAB-34).

### Fixed
- **Prompt système avec accolades littérales : `KeyError` et assistant muet dès qu'une base est rattachée** (`api/db/services/dialog_service.py`, `async_chat`) — le prompt était rendu par `str.format(**kwargs)`, qui lit toute accolade comme un champ de template : `body { font-family: Arial; }` levait `KeyError(' font-family')` et chaque réponse devenait `**ERROR**: ' font-family'`. Les assistants sans base (`async_chat_solo`, prompt brut) n'étaient pas touchés, d'où deux variantes de prompt à maintenir (accolades simples / doublées) et un assistant en variante simple qui cassait silencieusement dès qu'on lui rattachait une base. Nouveau module Eurelis `api/db/services/eurelis_prompt_template.py` : `render_prompt_template()` ne substitue que les paramètres **déclarés** dans `prompt_config.parameters` (plus `knowledge`, toujours substitué s'il est présent), par remplacement textuel de `{clé}` ; le reste du texte est transmis intact au modèle. Un seul prompt fonctionne désormais avec et sans base. **Changement de comportement assumé** : `{{` n'est plus un échappement et un `{clé}` non déclaré (ex. `{doc_ids}`) n'est plus substitué — les prompts en « variante accolades doublées » doivent repasser en accolades simples au déploiement.

### Tests
- **Unitaires — rendu du prompt** (`test/eurelis/unit/test_prompt_template_literal_braces.py`, 9 tests sans stack) : CSS/JS/template literal transmis intacts, preuve que `str.format` lève sur le même prompt, paramètres déclarés substitués dans n'importe quel ordre, `knowledge` substitué même non déclaré, placeholder non déclaré laissé tel quel, valeur absente laissée telle quelle, valeurs non-chaîne stringifiées et `None` ignoré, `{{` non interprété, template vide.
- **E2E — assistant avec base et prompt à accolades** (`test/eurelis/eurelis_fixes/test_prompt_literal_braces_e2e.py`, `p1`) : crée un chat sur le dataset de référence `eurelis-ref` avec un prompt système `{knowledge}` + CSS + JS + `${…}`, ouvre une session et lance une complétion SSE ; vérifie qu'aucune frame ne porte `**ERROR**`, que le texte généré (agrégation des deltas) est non vide et que la réponse cite des chunks de la base (chemin `async_chat` avec retrieval, pas le chemin solo). Vérifié en rouge sur l'image v0.26.3-eurelis.10 d'origine (`**ERROR**: ' font-family'`) et en vert avec le correctif.

---

## [v0.26.3-eurelis.10] - 2026-08-14

Basé sur RAGFlow `v0.26.3`. Correctif des **réponses tronquées à ~4 096 tokens de sortie sur Bedrock** (AILAB-22) : suffixe « The answer is truncated by your chosen LLM… » sur les réponses longues, reproduit en production Synerga avec `eu.anthropic.claude-opus-4-8`. Rend au passage le toggle « Max tokens » des composants agent LLM réellement opérant.

### Fixed
- **Réponses Bedrock tronquées au défaut service (~4 096 tokens)** (`rag/llm/chat_model.py`, `LiteLLMBase._construct_completion_args`, branche Bedrock) — aucun `max_tokens` n'était jamais transmis à Bedrock : `_clean_conf` neutralise volontairement `max_tokens` (garde-fou contre les caps legacy de `Dialog.llm_setting` / des DSL d'agents), et litellm n'injecte `maxTokens` dans Converse que si l'appelant le fournit (contrairement à Anthropic direct, où il injecte un défaut par modèle depuis son registre). Bedrock retombait donc sur son petit défaut service et coupait en plein mot avec `stop_reason: max_tokens` → `finish_reason: "length"` → suffixe `LENGTH_NOTIFICATION_EN`. Désormais, si ni `max_tokens` ni `max_completion_tokens` ne figurent dans les arguments, la branche Bedrock injecte le vrai max output du modèle depuis le registre litellm (`max_output_tokens` ; stratégie litellm/Anthropic direct transposée à Bedrock), avec repli sur l'env var `LLM_BEDROCK_DEFAULT_MAX_OUTPUT_TOKENS` (défaut 4096 = comportement historique, zéro risque sur modèle exotique) pour les modèles inconnus du registre. Le `pop("max_tokens")` de `_clean_conf` est inchangé.
  **Découverte importante en cours de correctif** : `api/ragflow_server.py` pinne `LITELLM_LOCAL_MODEL_COST_MAP=True`, donc le registre effectif en process est celui **embarqué** dans le litellm pinné — celui de 1.82.5 ignorait les modèles plus récents que lui, dont précisément `eu.anthropic.claude-opus-4-8` et `eu.anthropic.claude-sonnet-5` (128 000 dans le registre distant), qui seraient retombés sur 4096 et restés tronqués. D'où le bump litellm ≥ 1.92 ci-dessous, **prérequis du correctif pour ces modèles** : un rollback du pin réintroduirait silencieusement la troncature (un test unitaire ancré sur le registre embarqué garde cette régression).

### Changed
- **litellm `1.82.5` → `1.96.2`** (`pyproject.toml`, divergence assumée du pin upstream `1.84.0`) — prérequis du correctif ci-dessus : le registre **embarqué** de litellm (le seul consulté en process, cf. `LITELLM_LOCAL_MODEL_COST_MAP=True`) connaît `eu.anthropic.claude-opus-4-8` depuis 1.88.0 et `eu.anthropic.claude-sonnet-5` depuis 1.92.0 (`max_output_tokens = 128 000`). Le bump couvre au passage les CVE litellm < 1.84.0 signalées par l'upstream. Surfaces vérifiées sur 1.96.2 : imports `litellm.caching.caching` / `litellm.integrations.custom_logger` / `from litellm import logging` (les casses historiques 1.82.6-1.82.8 et 1.88.0), `acompletion`, `get_model_info` ; transitives mises à jour : aiohttp 3.14.1 → 3.14.3, pydantic-settings 2.12.0 → 2.15.0. Validé par les suites unitaires (Bedrock max_tokens, PII masking 42/42) et par le rejeu E2E de la conversation de repro (note complète, injection 128 000 servie par le registre). Pin exact conservé — à réconcilier quand l'upstream dépassera 1.92.
- **Toggle « Max tokens » des composants agent LLM rendu opérant** (`agent/component/llm.py`, `LLMParam.gen_conf`) — quand `maxTokensEnabled` est vrai et `max_tokens > 0`, la conf émet désormais `max_completion_tokens` au lieu de `max_tokens` : ce dernier était systématiquement retiré par `_clean_conf` (garde-fou legacy), rendant le toggle UI sans effet. `max_completion_tokens` figure déjà dans `ALLOWED_GEN_CONF_KEYS` (il traverse `_clean_conf` intact) et Converse le mappe sur `maxTokens`. Les DSL legacy portant `max_tokens: 256`/`4096` sans toggle activé restent neutralisés (aucune réactivation de cap).

### Tests
- **Unitaires — injection Bedrock & toggle agent** (`test/eurelis/unit/test_bedrock_max_tokens.py`, sans stack — nouveau répertoire `test/eurelis/unit/` avec conftest neutralisant les fixtures serveur et forçant `LITELLM_LOCAL_MODEL_COST_MAP=True` comme le runtime) : injection du max output du registre pour un modèle connu, dont les modèles prod `eu.anthropic.claude-opus-4-8` / `eu.anthropic.claude-sonnet-5` à 128 000 (échoue si le pin litellm redescend sous 1.92 — garde anti-rollback) ; repli env var puis 4096 pour un modèle inconnu ; `max_completion_tokens` explicite transmis tel quel (pas d'injection) ; aucune injection hors Bedrock ; toggle agent activé → `max_completion_tokens` émis, désactivé ou DSL legacy sans toggle → rien.
- **E2E — validation fonctionnelle AILAB-22** : rejeu du prompt de la conversation de repro du dialog « Test - Réviseur comptable senior » (instance locale, `eu.anthropic.claude-opus-4-8@Default@Bedrock`, serveur sans aucune env var) — avant correctif : coupure en plein mot à ~8 900 caractères avec le suffixe « The answer is truncated… » ; après : note complète (~10 700 caractères) avec conclusion, sans suffixe.
- **E2E opt-in — Bedrock réel** (`test/eurelis/eurelis_fixes/test_bedrock_max_tokens_e2e.py`, `p3`) : palier avec appel cloud payant, skippé par défaut — activé quand `EURELIS_BEDROCK_TEST_AK`/`EURELIS_BEDROCK_TEST_SK` sont fournis (région via `EURELIS_BEDROCK_TEST_REGION`, modèle via `EURELIS_BEDROCK_TEST_CHAT_MODEL`, défaut `eu.anthropic.claude-opus-4-8`). Provisionne une instance Bedrock sur le tenant de test, demande une liste numérotée de 200 items (~8-10k tokens de sortie, au-delà du défaut service ~4 096) et vérifie l'absence du suffixe de troncature **et** la présence du dernier item. Ajoute un skip attendu (3 au lieu de 2) dans les runs sans credentials.

---

## [v0.26.3-eurelis.9] - 2026-07-19

Basé sur RAGFlow `v0.26.3`. Ajoute le support du **reranking via AWS Bedrock** (connecteur absent de l'upstream), corrige un défaut de qualité qui neutralisait les rerankers neuronaux, et intègre la consommation de tokens du reranking dans les statistiques Eurelis.

### Added
- **Connecteur reranker AWS Bedrock** (`rag/llm/rerank_model.py`, classe `BedrockRerank`, `_FACTORY_NAME = "Bedrock"`) — la factory Bedrock proposait chat/embedding/CV mais aucun reranker : sélectionner un modèle rerank Bedrock plantait avec `Factory not in rerank model`. Le connecteur appelle l'API Rerank de `bedrock-agent-runtime` et réutilise le protocole de clé JSON de `BedrockEmbed` (`auth_mode` / `bedrock_region` / `bedrock_ak` / `bedrock_sk`, modes `access_key_secret` / `iam_role` / `assume_role`). Documents tronqués à la fenêtre du modèle (Cohere Rerank v3.5 ~2k tokens, Amazon Rerank v1 8k) ; scores renvoyés en `[0,1]` (normalisation partagée `Base.similarity` inchangée). Modèles à déclarer dans le catalogue via `conf/llm_factories.patch.json` (`amazon.rerank-v1:0`, `cohere.rerank-v3-5:0`). Soumis en upstream (PR infiniflow/ragflow #16960, qui porte en plus des durcissements API — cap 32 000 caractères, découpage en lots de 1 000, pagination `nextToken` — non encore back-portés ici).
- **Consommation du reranking dans `usage_log`** (`token_type="rerank"`) — `LLMBundle.similarity` (`api/db/services/llm_service.py`) accumule désormais les tokens rerank sur le bundle (comme `encode`/`encode_queries`), et de nouveaux helpers `log_rerank_from_bundle` / `log_rerank_from_usage` (`api/db/services/eurelis_usage_log.py`) écrivent la consommation pour les flux **chat** (`chat_api.py`, `conversation_service.py`) et **search** (recherche IA `async_ask` dans `dialog_service.py` + retrieval pur des Search apps / SDK dans `dataset_api_service.py`). Sans changement de schéma — la colonne `token_type` discrimine déjà et l'API stats ventile `"rerank"` dynamiquement (`GROUP BY`). Le reranking était auparavant un angle mort des statistiques (uniquement loggué en INFO et Langfuse).

### Changed
- **Reranking sur le texte naturel des chunks au lieu de la version tokenisée** (`Dealer.rerank_by_model`, `rag/nlp/search.py`) — les rerankers externes recevaient `content_ltks` (texte tokenisé : minusculisé, stemmé, accents éclatés) au lieu du texte naturel. Un reranker neuronal note ce charabia bien plus bas : sur des chunks FR réels, le même chunk pertinent chutait de ~0,5-0,85 (`content_with_weight`) à ~0,01-0,03 (`content_ltks`), soit un facteur 10-90×, neutralisant le reranker (la remontée était alors portée par les seuls mots-clés) et forçant un `similarity_threshold` artificiellement bas. Le reranker est désormais nourri au `content_with_weight` (mise en forme conservée, tableaux HTML compris — à ne pas nettoyer : Cohere exploite la structure des tableaux) ; `ins_tw` / la similarité mots-clés du blend restent inchangés. Bénéfice universel (Cohere, Jina, Voyage…). Soumis en upstream (PR infiniflow/ragflow #16961). Documenté dans `docs/eurelis/knowledge/reranking-natural-text-input.md`.

### Tests
- **Unitaires — logging conso rerank** (`test/unit_test/api/db/services/test_rerank_usage_log.py`) : accumulation des tokens sur le bundle (`LLMBundle.similarity`) et écriture des lignes `token_type="rerank"` (depuis le bundle et depuis le dict `usage`, no-op sans reranker configuré, skip à 0 token).

---

## [v0.26.3-eurelis.8] - 2026-07-15

Basé sur RAGFlow `v0.26.3`. Aligne le résumé IA des **Search apps** sur le partage d'équipe déjà en place pour le chat : un membre d'un tenant peut désormais lancer le résumé d'une Search app partagée (`permission="team"`), avec attribution correcte de la consommation. Ajoute par ailleurs un contrôle de santé `litellm` au healthz.

### Added
- **Contrôle `litellm` dans `/system/healthz`** (`api/utils/health_utils.py`) — nouvelle sonde `check_litellm()` qui vérifie que `litellm.acompletion` est bien exposé et appelable. Une install corrompue ou masquée (ex. `unclecode-litellm` écrasant le namespace `litellm`, qui charge alors comme un namespace package vide) fait désormais échouer le healthz (`litellm: "nok"`, `all_ok=False` → HTTP 500) au lieu de planter au premier appel de complétion. Couvert par le smoke test `p0` (`test/eurelis/test_smoke.py`).

### Fixed
- **Résumé IA d'une Search app partagée bloqué pour les membres (`POST /api/v1/searches/{search_id}/completions`)** — l'endpoint était gardé par `SearchService.accessible4deletion` (contrôle `created_by` strict, correct pour l'édition mais trop restrictif pour l'exécution), renvoyant `{code: AUTHENTICATION_ERROR, message: "No authorization."}` à tout membre non-propriétaire, même sur une app `permission="team"`. Côté Shield, la recherche et les résultats fonctionnaient mais le panneau « Résumé » restait vide (réponse JSON HTTP 200 non-SSE). Nouveau helper `_accessible_search` (`api/apps/restful_apis/search_api.py`), miroir de `_ensure_owned_chat` du chat : autorise le propriétaire **ou** un membre d'un tenant rejoint sur une app `permission="team"`. L'édition (`update`/`delete`) reste réservée au propriétaire (`accessible4deletion` inchangé).

### Changed
- **Découplage résolution des modèles / attribution de conso pour le résumé Search** (`async_ask`, `api/db/services/dialog_service.py`) — la signature devient `async_ask(question, kb_ids, owner_tenant_id, acting_user_id=None, …)`. Le chat/rerank (et le coût provider + clé API) sont désormais résolus sur le **propriétaire** de l'app (`owner_tenant_id`), tandis que la ligne de consommation (`eurelis_usage_log`) est attribuée au **membre appelant** (`acting_user_id`) — même règle produit que le chat. Auparavant, tout était résolu sur l'appelant, ce qui faisait échouer la synthèse pour un membre sans LLM configuré et loguait une conso incohérente. Rétro-compatible : sans `acting_user_id`, le comportement historique (`owner == appelant`) est conservé — l'appelant `/searchbots/ask` (`bot_api.py`) est inchangé.

### Tests
- **Unitaires — autorisation & attribution** (`test/testcases/test_web_api/test_search_app/test_search_routes_unit.py`, `p2`) : matrice d'autorisation de `/completions` (propriétaire ✓, membre d'un tenant rejoint + `team` ✓, non-membre ✗, `permission="me"` non-propriétaire ✗, search introuvable ✗) et vérification que `async_ask` reçoit `owner_tenant_id` = propriétaire et `acting_user_id` = appelant. Harness complété (`TenantPermission`, `get_joined_tenants_by_user_id`, `pagination_utils`, `headers.add_header`) — ce dernier réparant aussi les cas préexistants cassés par l'import upstream de `pagination_utils`.
- **E2E — le membre peut lancer le résumé** (`test/eurelis/eurelis_features/test_team_shared_searches.py::test_teammate_can_run_summary_completion`, `p1`) : garde la régression exacte (plus de « No authorization. » pour un membre sur une app `team`).

---

## [v0.26.3-eurelis.7] - 2026-07-14

Basé sur RAGFlow `v0.26.3`. Correctif d'un plantage du panel admin lors du changement de mot de passe d'un utilisateur provisionné via SSO (OIDC/OAuth), qui n'ont pas de mot de passe local.

### Fixed
- **Changement de mot de passe admin pour un utilisateur SSO (`PUT /api/v1/admin/users/{username}/password`)** — `UserMgr.update_user_password` (`admin/server/services.py`) appelait `check_password_hash(usr.password, psw)` pour éviter une écriture inutile si le nouveau mot de passe était identique à l'ancien. Or les comptes provisionnés via SSO (OIDC/OAuth/GitHub) n'ont pas de mot de passe local (`usr.password is None`, colonne `password` en `null=True`) : `check_password_hash(None, …)` plante à l'intérieur de Werkzeug (`pwhash.split('$')` → `'NoneType' object has no attribute 'split'`), renvoyant un `500`. La comparaison est désormais gardée par `usr.password`, si bien qu'un compte sans mot de passe passe directement à l'enregistrement du nouveau (donnant à ces utilisateurs un fallback mot de passe en complément du SSO). Correctif également soumis en upstream (PR infiniflow/ragflow #16914).

---

## [v0.26.3-eurelis.6] - 2026-07-13

Basé sur RAGFlow `v0.26.3`. Correctif de la validation d'email de l'endpoint admin de création d'utilisateur : le plus-addressing (`+` dans la partie locale) était refusé, ce qui empêchait le Shield d'auto-provisionner certains comptes.

### Fixed
- **Plus-addressing (`+`) dans l'email de `POST /api/v1/admin/users`** — la validation de `UserMgr.create_user` (`admin/server/services.py`) utilisait le motif `^[\w\._-]+@…`, dont la classe de caractères de la partie locale omettait `+` : toute adresse en plus-addressing (ex. `v.lambert+diligentia@eurelis.com`), pourtant valide au sens RFC 5321, était rejetée en `400 « Invalid email address »` avant même le contrôle d'unicité. Le Shield, qui auto-provisionne les comptes via cet endpoint, ne pouvait donc pas les créer (le chemin OIDC/Keycloak, lui, ne valide pas l'email — issu d'une claim de token — et passait). Ajout de `+` à la classe de caractères de la partie locale (`^[\w\.+_-]+@…`) ; le domaine est inchangé. L'endpoint d'inscription par mot de passe (`api/apps/restful_apis/user_api.py`), qui porte le même motif, n'est volontairement pas touché (hors périmètre).

### Tests
- **Contrat Shield — création d'utilisateur admin** (`test/eurelis/shield_contract/test_admin_user_creation.py`, `p0`) : fige l'acceptation d'un email avec `+` (`POST /api/v1/admin/users` → `200`, pas de « Invalid email address », `password` absent de la réponse) et le rejet d'un email réellement invalide (`400` + message « Invalid email address »). Schéma `ADMIN_CREATED_USER_SCHEMA` ajouté (`test/eurelis/schemas/admin.py`).

---

## [v0.26.3-eurelis.5] - 2026-07-12

Basé sur RAGFlow `v0.26.3`. Sessions de login interactives **multi-appareils** avec **expiration** : plusieurs sessions d'un même compte coexistent désormais (fini le « dernier login gagne »), bornées par un TTL de 12 h. Ajout de la couverture de non-régression du contrat de sessions et de trois endpoints consommés par le Shield.

### Added
- **TTL de session JWT (12 h)** — la validation des tokens applique désormais `max_age=12*3600` à `jwt.loads`, côté API (`api/apps/__init__.py`) **et** serveur admin (`admin/server/auth.py`) : un JWT plus ancien que 12 h lève `SignatureExpired` → 401, forçant une reconnexion périodique. Aucune expiration temporelle n'était appliquée auparavant (les tokens restaient valides jusqu'à rotation ou logout).

### Changed
- **Sessions login multi-appareils** — les points de login (mot de passe et OAuth/SSO côté API `user_api.py`, login admin `auth.py`) ne régénèrent plus systématiquement l'`access_token` : il n'est renouvelé que s'il est absent ou invalidé (préfixe `INVALID_`). Plusieurs sessions d'un même compte (navigateurs/appareils, ou API `:9380` + admin `:9381`) partagent alors le même `access_token` et **coexistent**, au lieu que chaque nouveau login évince les précédents. Combiné au TTL ci-dessus, l'exposition d'un token reste bornée dans le temps.

### Tests
- **Contrat Shield — sessions login** (`test/eurelis/shield_contract/test_auth_sessions.py`, `p0`) : coexistence multi-session (un 2ᵉ login ne révoque pas le token du 1er) sur l'API et l'admin, et application du TTL (JWT forgé à −13 h refusé, token frais accepté ; forge signée avec le secret réel du serveur, `skip` propre si le secret est indisponible côté hôte).
- **Contrat Shield — `GET /system/version`** (`test/eurelis/shield_contract/`, `p0`) : enveloppe `{code, message, data}` figée, `message` inclus (le Shield le lit pour son diagnostic d'erreur).
- **Contrat Shield — endpoints Admin de rattachement d'équipe** (`test/eurelis/shield_contract/test_admin_teams.py`, `p0`) : résolution d'`id` utilisateur (`GET /admin/users/{email}` → `data` = liste, utilisateur inexistant → `data: []`) et ajout de membre (`POST /admin/tenants/{tenant_id}/users`) avec idempotence (`400` + sous-chaîne « already »).

### Notes
- Le bug upstream des tuples `update_time` / `update_date` dans le login admin (`admin/server/auth.py`, PR upstream infiniflow/ragflow #10642) est **laissé tel quel** pour préserver des rebases propres — il n'affecte pas l'authentification.

---

## [v0.26.3-eurelis.4] - 2026-07-09

Basé sur RAGFlow `v0.26.3`. Correctif du masquage PII multi-langue : l'init Presidio échouait dès que `PII_MASKING_LANGUAGES` contenait une langue autre que « en » (ex. `fr,en`), désactivant silencieusement le masquage. Le modèle FR embarqué en `.3` est désormais réellement exploitable.

### Fixed
- **Init du masquage PII en multi-langue (`fr`, `fr,en`)** — `RecognizerRegistry()` était construit avec son `supported_languages` par défaut (`["en"]`) que `load_predefined_recognizers()` ne met jamais à jour ; l'`AnalyzerEngine`, lui, était créé avec la liste complète des langues, d'où l'erreur Presidio *« Misconfigured engine, supported languages have to be consistent »* et le masquage désactivé silencieusement (`PII_MASKING_STARTUP_FAIL=false`). Le registre est désormais initialisé avec la liste complète des langues configurées (`RecognizerRegistry(supported_languages=languages)`). Les recognizers regex/checksum (EMAIL_ADDRESS, PHONE_NUMBER, CREDIT_CARD, IBAN_CODE, IP_ADDRESS) restent disponibles pour chaque langue ; les entités NER (PERSON, LOCATION, DATE_TIME) proviennent du modèle spaCy de chaque langue. Le cas `en` seul est inchangé.

### Tests
- **Non-régression : init PII multi-langue** (`test_initialize_multilang_fr_en` dans `test/unit_test/rag/llm/test_pii_masking.py`) — vérifie que l'init `fr,en` avec NER réussit (`is_available() is True`). Chemin non couvert auparavant : tous les tests d'init utilisaient `PII_MASKING_NER=false` et la langue « en ».

---

## [v0.26.3-eurelis.3] - 2026-07-09

Basé sur RAGFlow `v0.26.3`. Ajout du modèle spaCy français *small* dans l'image pour activer le NER FR du masquage PII (Presidio).

### Added
- **Modèle spaCy `fr_core_news_sm` (3.8.0, ~16 Mo)** embarqué dans l'image aux côtés de `en_core_web_sm`, via `pyproject.toml` (installé par `uv sync`, sans téléchargement runtime). Débloque la détection NER FR (PER/LOC/DATE_TIME) du masquage PII sur les déploiements francophones (ex. Synerga) avec `PII_MASKING_NER=true` + `PII_MASKING_LANGUAGES=fr` + `PII_MASKING_NER_MODEL_FR=fr_core_news_sm`. Le modèle EN existant est conservé. Variante *small* choisie (précision NER moindre que `lg` acceptée) pour garder l'image légère.

### Tests
- **Non-régression : présence des modèles spaCy** (`test/eurelis/eurelis_features/test_spacy_models.py`, `p1`) — vérifie, via `docker exec` dans le conteneur sous test, que l'image embarque `en_core_web_sm` **et** `fr_core_news_sm`, et que le NER FR détecte bien une PER (« Jean Dupont ») et une LOC (« Paris »). Garde-fou contre la régression prod (image sans modèle FR).

### Notes
- `uv.lock` régénéré avec un `uv` récent (0.11.x) respectant `exclude-dependencies` : seule l'entrée `fr-core-news-sm` est ajoutée, `unclecode-litellm` et `agentrun-mem0ai` restent exclus.

---

## [v0.26.3-eurelis.2] - 2026-07-05

Basé sur RAGFlow `v0.26.3`. Ajout du partage d'équipe des Search apps, d'un sélecteur de fenêtre temporelle pour les statistiques, et de la couverture de non-régression du contrat Search consommé par le Shield.

### Added
- **Partage d'équipe des Search apps** (`permission` `me|team`) — symétrique au partage des chats : une search `team` créée par le propriétaire d'un tenant devient visible par les membres l'ayant rejoint. Colonne `search.permission` + migration, filtre équipe dans `SearchService.get_by_tenant_ids`, récupération des tenants rejoints dans le listing (`search_api`), et sélecteur « Me / Équipe » dans les réglages search (front).
- **Sélecteur de fenêtre temporelle des statistiques** (pages user + admin) — granularité Semaine/Mois/Année avec navigation ◀▶, mode « Personnalisé » (calendrier de plage), libellés d'axe hebdomadaires localisés (`YYYY - Sww`). La sélection est conservée entre `/admin/stats` et `/admin/stats/users/<email>` (store dédié).
- **Tests de non-régression Search** — contrat Shield des 5 endpoints de la feature Search UI (028 : liste, détail, retrieval, résumé SSE, recommandation ; `p0`) et partage d'équipe des search (`p1`), avec search app de référence ajoutée au seed.

### Changed
- **Menu mobile** : masquage des liens Discord / GitHub / Help (branding Eurelis), en cohérence avec le masquage déjà en place côté desktop.

### Notes
- Validé par la suite de non-régression sur l'image `v0.26.3-eurelis.2` : **p0 vert** (contrat Shield, dont les 5 endpoints Search) et **partage search `p1` vert**.
- La search app de référence du seed est créée avec un modèle de résumé (`chat_id`) : l'endpoint `/searches/{id}/completions` ne retombe pas sur le modèle par défaut du tenant quand `chat_id` est absent.

---

## [v0.26.3-eurelis.1] - 2026-07-05

Basé sur RAGFlow `v0.26.3`. Rebase du fork sur la nouvelle base upstream — aucune nouvelle fonctionnalité Eurelis, mais réintégration des 43 commits Eurelis sur `v0.26.3` avec résolution des conflits.

### Changed
- **Rebase sur RAGFlow `v0.26.3`** — intégration de 299 commits upstream (`v0.26.1` → `v0.26.3`) : parser DOCX dédié, comptabilité de tokens agrégée « autoritative » + propagation Langfuse des runs agent, provider « New API » (passerelles OpenAI-compatibles), correctifs GraphRAG (`RedisDB.mget`), PDF compressés, fuite de sessions MCP, XSS du modal de rerun agent, etc.
- **Masquage PII fusionné avec la nouvelle comptabilité de tokens upstream** — le hook PII streaming (`chat_model.py` : retour tuple de `_construct_completion_args` + `StreamingUnmasker`/flush) coexiste avec `stream_options.include_usage` + `_commit_round` de l'upstream. Nouvelle classe vision `NewAPICv` intégrée à côté des méthodes PII de `BedrockCV` (`cv_model.py`).
- **Statistiques de consommation alignées sur l'upstream** — comptage `add_ingestion_llm_tokens` / `used_tokens` conservé face au nouveau logging paresseux et à `_report_usage` (`llm_service.py`) ; condition `model_config["model_type"]` harmonisée (`dialog_service.py`).
- **Branding Eurelis réappliqué** sur le nouveau header responsive upstream (`useHeaderNavLayout`, mode compact) — liens Discord/GitHub masqués.

### Fixed
- **`uv.lock` régénéré** avec un `uv` récent respectant `exclude-dependencies` (upstream) : `unclecode-litellm` et `agentrun-mem0ai` restent exclus. Le correctif Eurelis dédié au drop de `unclecode-litellm` devient obsolète (absorbé par le mécanisme upstream).

### Notes
- Deux commits Eurelis écartés au rebase (devenus vides — contenu déjà présent upstream) : correction du commentaire `ContextVars` et drop manuel de `unclecode-litellm`. Un commit i18n FR a été absorbé (mergé upstream).
- Validé par la suite de non-régression : **42 passed / 2 skipped** + palier vision **1 passed** (OpenAI `gpt-5.4-mini`).
- ⚠ La migration `usage_log.token_type` (voir `v0.26.1-eurelis.3`) reste requise sur une base existante non encore migrée.

---

## [v0.26.1-eurelis.3] - 2026-06-30

Basé sur RAGFlow `v0.26.1`. Release finale consolidant les itérations expérimentales `exp.1` → `exp.5` : statistiques de consommation, supervision admin des modèles et correctifs associés.

### Added
- **Supervision admin des modèles par tenant** — nouvelle page d'administration `/admin/model-supervision` (cross-tenant, superuser) pour visualiser, comparer et propager les configurations de modèles.
  - Comparaison multi-tenants en matrice : fournisseurs/instances (clé API **masquée**), modèles par défaut (avec détection des défauts **« pendants »** non résolubles), modèles disponibles (avec filtre texte).
  - Opérations granulaires vers une **liste de tenants cibles** : copier un fournisseur/instance (clé incluse, overwrite), supprimer un fournisseur/instance, copier les modèles par défaut.
  - Backend isolé : blueprint admin Eurelis (`admin/server/admin_model_supervision.py`), 5 routes sous `/api/v1/admin/tenants/…`, ciblant le système `tenant_model_*` (legacy `tenant_llm` hors périmètre). Les clés API ne transitent jamais en clair vers le frontend.
- **Statistiques de consommation de tokens** — table append-only `usage_log` avec dashboards admin et utilisateur. Modèle orthogonal : `source` (flux : `chat` · `search` · `agent` · `ingestion`) × `token_type` (`llm` · `embedding`).
  - Logging câblé sur le chat, le widget chatbot, la recherche IA (`async_ask`), le retrieval d'agent, le retrieval SDK dataset et l'ingestion de documents (tokens *embedding* **et** *LLM*), centralisé dans `api/db/services/eurelis_usage_log.py`.
  - APIs `/api/v1/usage-stats/me/*` (serveur Quart) et `/api/v1/admin/stats/*` (serveur admin Flask) : filtres `source`/`type`, séries temporelles (`by_source`/`by_type`), breakdowns (`group_by=source|type|model|dialog`), `available_sources`/`available_types`.
  - Frontend : dashboard admin, détail par utilisateur et page utilisateur — presets de période, filtres multi-select source/type avec pastilles de couleur, barres empilées par flux, « Top modèles » colorés par nature (`token_type`), filtres de recherche sur les tableaux ressources et utilisateurs.

### Changed
- **Détail de session restreint aux tokens LLM** — `stats_for_session()` filtre les tours sur `token_type` (défaut `llm`). Les totaux et l'histogramme par tour de l'endpoint `/usage-stats/me/session/{id}` reflètent désormais l'usage LLM uniquement, en excluant les embeddings (et autres natures non-LLM).

### Fixed
- **Chats partagés en équipe absents de la liste** — l'endpoint de listing des chats passait `joined_tenant_ids=[]`, donc la clause `(tenant_id ∈ joined ET permission='team')` était toujours vide : seuls les chats propres de l'utilisateur étaient renvoyés. Les chats `permission='team'` des équipes rejointes n'apparaissaient jamais dans la sidebar (accessibles uniquement par lien direct). `joined_tenant_ids` est désormais calculé via `TenantService.get_joined_tenants_by_user_id` et transmis — les membres voient bien les chats partagés avec leur équipe.
- **Démarrage cassé (`ImportError: update_request_with_filtered_beta`)** — `crawl4ai 0.8.9` (sur pypi.org) tire `unclecode-litellm`, un fork de litellm qui s'installe dans le même namespace `litellm/` et écrase le `litellm==1.82.5` pinné, faisant crasher le `task_executor` au boot. `unclecode-litellm` est retiré du `uv.lock` (le build le consomme via `uv sync --frozen`). `pyproject.toml` reste aligné sur l'upstream — son garde-fou `exclude-dependencies` est un champ uv invalide (no-op). Procédure de régénération du lock documentée dans le commit du fix.
- Propagation des `ContextVars` asyncio dans le thread pool (`thread_pool_exec`) sous Python 3.13 (`ThreadPoolExecutor` WorkerContext).
- Dérivation du type `image2text` depuis les tags du factory quand `model_type` l'omet.

### Notes
- ⚠ **Migration manuelle requise** avant de démarrer le serveur sur une base existante (la colonne n'est pas ajoutée par `migrate_db()`) :
  ```sql
  ALTER TABLE usage_log ADD COLUMN token_type VARCHAR(16) NOT NULL DEFAULT 'llm';
  CREATE INDEX usage_log_token_type ON usage_log (token_type);
  ```

---

## [v0.26.1-eurelis.2] - 2026-06-20

Basé sur RAGFlow `v0.26.1`.

### Added
- Provisionnement automatique des équipes à la première connexion OIDC (Option A) :
  les utilisateurs créés via Keycloak sont assignés aux équipes configurées dans
  `default_teams` (liste d'emails d'owners) sans passer par le flux d'invitation.
  Implémenté dans `api/apps/auth/auto_team_provisioning.py`.

---

## [v0.26.1-eurelis.1] - 2026-06-20

Basé sur RAGFlow `v0.26.1`.

### Changed
- Rebase sur RAGFlow `v0.26.1` — intégration de 109 commits upstream (chat channels, PaddleOCR async, Go agent canvas, fix SSRF Markdown, fix OOM PDF)

---

## [v0.26.0-eurelis.2] - 2026-06-19

Basé sur RAGFlow `v0.26.0`.

### Added
- **SitemapConnector** — connecteur d'ingestion de pages web via `sitemap.xml` (sitemaps standard et index récursifs, polling incrémental via `<lastmod>`, conversion HTML→Markdown, protection SSRF, filtre URL regex, suivi de liens PDF)

---

## [v0.26.0-eurelis.2-exp.1] - 2026-06-15 ⚠️ expérimental

Basé sur RAGFlow `v0.26.0` — branche `eurelis/feature/sitemap-connector`.

### Added
- **SitemapConnector** — connecteur d'ingestion de pages web via `sitemap.xml` (sitemaps standard et index récursifs, polling incrémental via `<lastmod>`, conversion HTML→Markdown, protection SSRF, filtre URL regex, suivi de liens PDF)

---

## [v0.26.0-eurelis.1] - 2026-06-14

Basé sur RAGFlow `v0.26.0`.

### Added
- Moteur de masquage PII basé sur Presidio (`rag/llm/pii_masking.py`) — détection et anonymisation des données personnelles dans les requêtes LLM, avec suffixe `::pii` sur le nom du modèle pour activation
- Gestion des équipes (group work) — API, UI admin et i18n pour la création et la gestion des équipes utilisateurs
- Interface d'administration des équipes (`feat(eurelis/admin)`)
- Séparation des surcharges LLM Eurelis dans `conf/llm_factories.patch.json` (Gemini, Bedrock, rangs des providers)
- Documentation Eurelis : guidelines, commandes Claude, procédures fork
- Suppression des blobs uploadés en chat lors de la suppression d'une session
- Remplacement du branding RAGFlow par l'identité Eurelis

### Fixed
- Correction des cas limites du moteur PII masking (streaming, placeholders cross-messages)
- Fallback i18n des templates d'agents, typo `hyphens-auto`, dépendance `useMemo`
- Mirror GitHub pour `graspologic` (fix build — Gitee inaccessible)
- Remplacement du moteur de substitution bash par Python dans `docker/entrypoint.sh` (substitution `${VAR:-default}` plus fiable)

### Changed
- Exclusion des rapports de sync-upstream du tracking git
- Règle MD060 désactivée dans la config markdownlint

---

## [v0.25.6-eurelis.2] - 2026-06-10

Basé sur RAGFlow `v0.25.6`.

### Added

- **PII Masking** — masquage automatique des données personnelles (PII) avant envoi aux LLM,
  via [Microsoft Presidio](https://github.com/microsoft/presidio) :
  - `rag/llm/pii_masking.py` — moteur Presidio : détection, anonymisation, réhydratation des
    réponses (`StreamingUnmasker`, `PiiAuditLogger`, `PiiMaskingEngine` singleton).
  - `rag/llm/chat_model.py` — hook dans `LiteLLMBase._construct_completion_args()` + réhydratation
    dans `async_chat`, `async_chat_streamly`, `async_chat_with_tools`, `async_chat_streamly_with_tools`.
  - `rag/llm/cv_model.py` — intégration dans `GeminiCV`.
  - `api/ragflow_server.py` — initialisation `PiiMaskingEngine.initialize()` au démarrage.
  - `conf/llm_factories.json` — variante `gemini-3.5-flash::pii` (`image2text`).
  - `test/unit_test/rag/llm/test_pii_masking.py` — 41 tests unitaires.
  - `docs/eurelis/features/pii-masking.md` — documentation technique complète.
  - Variables d'environnement : `PII_MASKING_ENABLED`, `PII_MASKING_PROVIDERS`,
    `PII_MASKING_ENTITIES`, `PII_MASKING_SCORE_THRESHOLD`, `PII_MASKING_SCORE_OVERRIDES`,
    `PII_MASKING_ROLES`, `PII_MASKING_LANGUAGES`, `PII_MASKING_NER`, `PII_AUDIT_LOG_ENABLED`, etc.
  - Dépendances : `presidio-analyzer>=2.2.354`, `presidio-anonymizer>=2.2.354`.

### Changed

- **Admin — refonte de la gestion des équipes** :
  - Suppression des pages `/admin/teams` et `/admin/teams/:id`.
  - `/admin/users/:id/team` — nouvelle interface double-liste (dual-listbox) pour gérer les membres
    de l'équipe d'un utilisateur (filtrage, sélection multiple, case à cocher globale).
  - `/admin/users/:id/members` — nouvelle interface double-liste pour gérer les équipes d'un
    utilisateur, avec compteur de membres dans les deux panneaux.
  - Mutations séquentielles pour éviter les deadlocks MySQL (1213) lors de sélections multiples.

### Fixed

- **`LiteLLMBase._clean_conf`** — `model_type` (champ interne RAGFlow injecté depuis l'upstream
  [#15141](https://github.com/infiniflow/ragflow/pull/15141)) n'était pas filtré avant l'appel API,
  causant une erreur `400 Bad Request` sur Bedrock (`extraneous key [model_type] is not permitted`).
  Fix : `gen_conf.pop("model_type", None)` dans `rag/llm/chat_model.py`.
- **`BedrockCV`** — implémentation de `async_chat` et `async_chat_streamly` via
  `litellm.acompletion` (l'implémentation héritée utilisait `self.async_client` non initialisé).

---

## [v0.25.6-eurelis.2-exp.4] - 2026-06-09 ⚠️ expérimental

Basé sur RAGFlow `v0.25.6` — branche `eurelis/main`.

> Première release expérimentale issue de `eurelis/main` : la branche `eurelis/feature/pii-masking` a été intégrée. Contient toutes les modifications de `exp.3`, plus :

### Changed

- **Admin — interface double-liste pour la gestion des équipes** — refonte des pages de gestion membres/équipes :
  - `/admin/users/:id/team` — dual-listbox permettant d'ajouter/retirer des membres de l'équipe d'un utilisateur (filtrage, sélection multiple, case à cocher globale).
  - `/admin/users/:id/members` — dual-listbox pour gérer les équipes auxquelles appartient un utilisateur, avec affichage du compteur de membres dans les deux panneaux.
  - Badge de rôle `normal` masqué (non informatif). Mutations séquentielles pour éviter les deadlocks MySQL (1213) lors de sélections multiples.
  - Suppression des pages `/admin/teams` et `/admin/teams/:id` (remplacées par les vues ci-dessus).

---

## [v0.25.6-eurelis.2-exp.3] - 2026-06-04 ⚠️ expérimental

Basé sur RAGFlow `v0.25.6` — branche `eurelis/feature/pii-masking` (non mergée dans `eurelis/main`).

### Fixed

- **`LiteLLMBase._clean_conf`** — cherry-pick du fix `model_type` depuis `fix/litellm-model-type-leaked-to-api` (absent du tag `v0.25.6-eurelis.2-exp.2`). `gen_conf.pop("model_type", None)` empêche l'envoi du champ interne RAGFlow à l'API Bedrock (`400 Bad Request: extraneous key [model_type] is not permitted`).

### Changed

- **Admin — suppression de la route `/admin/teams`** — la page de gestion des équipes (`/admin/teams`) et son entrée de navigation ont été retirées de l'interface admin. Les routes `/admin/users/:id/team` et `/admin/users/:id/members` restent opérationnelles.

---

## [v0.25.6-eurelis.2-exp.2] - 2026-06-01 ⚠️ expérimental

Basé sur RAGFlow `v0.25.6` — branche `eurelis/feature/pii-masking` (non mergée dans `eurelis/main`).

### Fixed

- **`LiteLLMBase._clean_conf`** — `model_type` (champ interne RAGFlow injecté dans `llm_setting` depuis l'upstream [#15141](https://github.com/infiniflow/ragflow/pull/15141)) n'était pas filtré avant l'appel API, causant une erreur `400 Bad Request` sur Bedrock (`extraneous key [model_type] is not permitted`). Fix : `gen_conf.pop("model_type", None)` dans `LiteLLMBase._clean_conf` (`rag/llm/chat_model.py`). PR upstream ouverte : [infiniflow/ragflow#15491](https://github.com/infiniflow/ragflow/pull/15491).

- **`BedrockCV`** — intégration PII masking + implémentation de `async_chat` et `async_chat_streamly` via `litellm.acompletion` (l'implémentation héritée de `Base` utilisait `self.async_client` non initialisé dans `BedrockCV`).

---

## [v0.25.6-eurelis.2-exp.1] - 2026-05-31 ⚠️ expérimental

Basé sur RAGFlow `v0.25.6` — branche `eurelis/feature/pii-masking` (non mergée dans `eurelis/main`).

### Added

- **PII Masking** — masquage automatique des données personnelles (PII) avant envoi aux LLM, via [Microsoft Presidio](https://github.com/microsoft/presidio) :
  - `rag/llm/pii_masking.py` — moteur Presidio : détection, anonymisation, réhydratation des réponses (`StreamingUnmasker`, `PiiAuditLogger`, `PiiMaskingEngine` singleton).
  - `rag/llm/chat_model.py` — hook dans `LiteLLMBase._construct_completion_args()` + réhydratation dans tous les callers (`async_chat`, `async_chat_streamly`, `async_chat_with_tools`, `async_chat_streamly_with_tools`).
  - `rag/llm/cv_model.py` — intégration dans `GeminiCV` (`async_chat` + `async_chat_streamly`) : masquage du contexte RAG (`system`) + de l'historique en un seul appel.
  - `api/ragflow_server.py` — initialisation `PiiMaskingEngine.initialize()` au démarrage.
  - `conf/llm_factories.json` — ajout de `gemini-3.5-flash::pii` (`image2text`) comme variante avec masquage.
  - `test/unit_test/rag/llm/test_pii_masking.py` — 41 tests unitaires.
  - `docs/eurelis/features/pii-masking.md` — documentation technique complète.

- **Fonctionnalités du moteur PII Masking :**
  - Détection par regex/checksum (EMAIL, PHONE, CREDIT_CARD, IBAN, IP) sans dépendance NER.
  - Détection contextuelle via spaCy NER (PERSON, LOCATION, DATE_TIME) — optionnelle, configurable par langue.
  - Actions `MASK` (remplacement par `<TYPE_N>`) et `BLOCK` (exception, requête bloquée).
  - Placeholders numérotés et cohérents entre messages : même valeur → même placeholder (`_SharedMaskingState`).
  - Réhydratation des réponses en mode streaming (sliding-window buffer, `StreamingUnmasker`).
  - Audit log configurable : niveau `summary` ou `detailed`, destination `app`/`file`/`both`, niveau INFO.
  - Champ `recognizer` dans l'audit log `detailed` (`SpacyRecognizer` vs `EmailRecognizer`, etc.).
  - Recognizers personnalisés via fichier YAML (pattern regex, deny-list, boosting contextuel).
  - Opt-in par modèle via suffix `::pii` (ex. `gemini-3.5-flash::pii`) ou ciblage par provider regex.
  - Mode "audit sans masquage" : `PII_AUDIT_LOG_ENABLED=true` + `PII_MASKING_ENABLED=false`.

- **Variables d'environnement ajoutées :** `PII_MASKING_ENABLED`, `PII_MASKING_PROVIDERS`, `PII_MASKING_ENTITIES`, `PII_MASKING_SCORE_THRESHOLD`, `PII_MASKING_SCORE_OVERRIDES`, `PII_MASKING_ROLES`, `PII_MASKING_LANGUAGES`, `PII_MASKING_NER`, `PII_MASKING_NER_MODEL_EN`, `PII_MASKING_NER_MODEL_FR`, `PII_MASKING_CUSTOM_RECOGNIZERS_FILE`, `PII_MASKING_STARTUP_FAIL`, `PII_AUDIT_LOG_ENABLED`, `PII_AUDIT_LOG_LEVEL`, `PII_AUDIT_LOG_DESTINATION`, `PII_AUDIT_LOG_FILE`.

- **Dépendances Python ajoutées :** `presidio-analyzer>=2.2.354`, `presidio-anonymizer>=2.2.354` (+ `en-core-web-sm` déjà présent via GraphRAG).

---

## [v0.25.6-eurelis.1] - 2026-05-30

Basé sur RAGFlow `v0.25.6`.

### Added

- **Gestion des équipes (admin)** — nouvelle feature `eurelis/group_work` :
  - `admin/server/routes.py` + `admin/server/services.py` — API admin pour la gestion des équipes : listing, ajout/suppression de membres, changement de rôle, validation d'invitation.
  - `web/src/pages/admin/teams.tsx` — page `/admin/teams` : liste des équipes avec compteur de membres.
  - `web/src/pages/admin/team-detail.tsx` — page `/admin/teams/:id` : détail d'une équipe et gestion de ses membres.
  - `web/src/pages/admin/user-own-team.tsx` — page `/admin/users/:id/team` : gestion des membres de l'équipe propre d'un utilisateur.
  - `web/src/pages/admin/user-team.tsx` — page `/admin/users/:id/members` : équipes auxquelles appartient un utilisateur.
  - `api/db/db_models.py` — champ `chat_permission` sur le modèle `Dialog` pour contrôler l'accès aux chats partagés.
  - `web/src/locales/eurelis/en.ts` + `fr.ts` — clés i18n Eurelis isolées de l'upstream.

### Changed

- Synchronisation upstream RAGFlow `v0.25.6` (43 commits intégrés, dont `feat(i18n): complete French translation` — notre contribution FR a été mergée dans l'upstream sous `50424df48`).
- `web/src/pages/admin/users.tsx` — refonte des boutons d'action : icônes distinctes (`LucideUsers` / `LucideLink`) pour les deux pages équipes, changement de mot de passe en première position.

### Fixed

- `web/src/components/llm-setting-items/next.tsx` — le paramètre *Creativity* du chat n'était pas sauvegardé (cherry-pick upstream PR #15243).
- `web/src/pages/agents/template-card.tsx` — descriptions des templates d'agent non affichées pour les langues non couvertes (`en`/`zh`/`de`) : fallback sur `'en'`, correction typo `hypens-auto` → `hyphens-auto`, ajout de `i18n.language` dans les dépendances du `useMemo` (PR upstream [#15370](https://github.com/infiniflow/ragflow/pull/15370)).

---

## [v0.25.4-eurelis.1] - 2026-05-17

Basé sur RAGFlow `v0.25.4`.

### Changed

- Synchronisation avec l'upstream RAGFlow `v0.25.4` (commit `86bcf9767`).

### Fixed

- `api/apps/restful_apis/chat_api.py` — suppression en cascade des fichiers uploadés en chat lors de la suppression d'une session. Les blobs orphelins dans le bucket MinIO `{user_id}-downloads` sont désormais nettoyés à la suppression de session.

---

## [v0.25.1-eurelis.3] - 2026-05-10

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

### Added

- `rag/llm/cv_model.py` — classe `BedrockCV` : implémentation `CvModel` pour le provider Bedrock via LiteLLM (préfixe `bedrock/`). Supporte les modes d'authentification AWS `access_key_secret`, `iam_role` et chaîne de credentials par défaut.
- `web/public/logo.svg` — remplacement du logo RAGFlow par le logo Eurelis avec dégradé (`#00253a` → `#cc007b` → `#ffb3d9`).

### Changed

- `web/src/layouts/components/header.tsx` — masquage des icônes Discord et GitHub dans la barre de navigation.
- `web/src/pages/home/banner.tsx`, `web/src/pages/next-search/ragflow-logo.tsx`, `web/src/pages/login-next/bg.tsx`, `web/tailwind.css` — alignement des couleurs de dégradé et de l'accent principal (`--accent-primary`) sur l'identité visuelle Eurelis.
- `api/db/joint_services/tenant_model_service.py` — accès direct aux attributs `.llm_name` / `.llm_factory` de `TenantLLM`, filtre `fid=` sur `LLMService.query`, logs debug à chaque étape du fallback IMAGE2TEXT→CHAT, normalisation de `model_type` à `image2text` après le fallback.
- `rag/llm/cv_model.py` — suppression du paramètre `base_url` inutilisé dans `BedrockCV.__init__`.
- `rag/nlp/search.py` — ajout d'un `logging.warning` lors de la détection d'un chunk parent manquant dans `retrieval_by_children`.
- `rag/advanced_rag/tree_structured_query_decomposition_retrieval.py` — passage d'un message descriptif à `logging.exception` au lieu de l'objet exception.

### Fixed

- `api/db/joint_services/tenant_model_service.py` — fallback IMAGE2TEXT→CHAT : un modèle déclaré `model_type: "chat"` avec le tag `IMAGE2TEXT` peut désormais être résolu lors de l'ingestion PDF parser.
- `api/apps/llm_app.py` — régression upstream `050113482` : la clé API Bedrock assemblée depuis les champs séparés était écrasée par la logique "existing key". Fix : écriture dans `req["api_key"]` avant la vérification.

---

## [v0.25.1-eurelis.3-exp.5] - 2026-05-10

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Added

- `web/public/logo.svg` — remplacement du logo RAGFlow par un dégradé aux couleurs Eurelis (`#00253a` → `#cc007b` → `#ffb3d9`).

### Changed

- `web/src/layouts/components/header.tsx` — masquage des icônes Discord et GitHub dans la barre de navigation (commentées).
- `api/db/joint_services/tenant_model_service.py` — accès direct aux attributs `.llm_name` / `.llm_factory` de `TenantLLM` (suppression du `.to_dict()`), filtre `fid=` sur `LLMService.query`, correspondance exacte du tag `IMAGE2TEXT`, logs debug à chaque étape du fallback. (amélioration de la PR upstream #14704)
- `rag/llm/cv_model.py` — suppression du paramètre `base_url` inutilisé dans `BedrockCV.__init__`. (amélioration de la PR upstream #14705)
- `rag/nlp/search.py` — ajout d'un `logging.warning` lors de la détection d'un chunk parent manquant dans `retrieval_by_children`. (amélioration de la PR upstream #14556)
- `rag/advanced_rag/tree_structured_query_decomposition_retrieval.py` — passage d'un message descriptif à `logging.exception` au lieu de l'objet exception. (amélioration de la PR upstream #13942)

---

## [v0.25.1-eurelis.3-exp.4] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Fixed

- `api/apps/llm_app.py` — régression upstream `050113482` : la clé API Bedrock assemblée depuis les champs séparés (`bedrock_ak`, `bedrock_sk`...) était écrasée par la logique "existing key" car `req["api_key"]` était `None`. Fix : écriture dans `req["api_key"]` avant la vérification, cohérent avec le pattern Tencent Cloud.

---

## [v0.25.1-eurelis.3-exp.3] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Added

- `rag/llm/cv_model.py` — classe `BedrockCV` : implémentation `CvModel` pour le provider Bedrock via LiteLLM (préfixe `bedrock/`). Supporte les modes d'authentification AWS `access_key_secret`, `iam_role` et chaîne de credentials par défaut. Résout l'erreur `'LiteLLMBase' object has no attribute 'describe_with_prompt'` lors de l'ingestion PDF parser avec un modèle Bedrock.

---

## [v0.25.1-eurelis.3-exp.2] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Fixed

- `api/db/joint_services/tenant_model_service.py` — normalisation de `model_type` à `image2text` après le fallback IMAGE2TEXT→CHAT : le caller (`tenant_llm_service`) instancie désormais correctement `CvModel` au lieu de `ChatModel`, résolvant l'erreur `'LiteLLMBase' object has no attribute 'describe_with_prompt'` lors de l'ingestion PDF parser.

---

## [v0.25.1-eurelis.3-exp.1] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

> **Pré-release expérimentale** de `v0.25.1-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

### Fixed

- `api/db/joint_services/tenant_model_service.py` — fallback IMAGE2TEXT → CHAT manquant : un modèle déclaré `model_type: "chat"` avec le tag `IMAGE2TEXT` peut désormais être résolu lors de l'ingestion PDF parser. Le fallback n'est accordé qu'après vérification du tag `IMAGE2TEXT` dans la table `llm` pour garantir la capacité vision.

---

## [v0.25.1-eurelis.2] - 2026-05-08

Basé sur RAGFlow `v0.25.1` (synchronisé avec upstream `nightly` — `59c35100c`).

### Changed

- Synchronisation upstream RAGFlow post-`v0.25.1` (tag `nightly`, 96 commits intégrés)

---

## [v0.25.1-eurelis.1] - 2026-05-02

Basé sur RAGFlow `v0.25.1`.

### Added

- Dépendance `zhipuai>=2.0.1` pour le support des modèles ZhipuAI (`cb70f7362`)

### Changed

- Amélioration de `tree_structured_query_decomposition_retrieval` : meilleure gestion du total et des cas limites (`3e2486ac6`)

### Fixed

- `rag/nlp/search.py` — `retrieval_by_children` : guard `None` sur le chunk parent pour éviter un `TypeError` sur les enfants orphelins — repli sur les chunks enfants en cas de parent absent de l'index (`188f825a9`)

---

## [v0.25.0-eurelis.3-exp.1] - 2026-05-02

> **Pré-release expérimentale** de `v0.25.0-eurelis.3`. Image Docker publiée pour tests ; ne pas utiliser en production.

Contient toutes les modifications de `v0.25.0-eurelis.2`, plus :

### Fixed

- `rag/nlp/search.py` — `retrieval_by_children` : guard `None` sur le chunk parent pour éviter un `TypeError` sur les enfants orphelins — repli sur les chunks enfants en cas de parent absent de l'index (`2eca7d7e2`)

---

## [v0.25.0-eurelis.2] - 2026-05-02

Basé sur RAGFlow `v0.25.0` (synchronisé avec upstream `v0.25.1`).

### Added

- Dépendance `zhipuai>=2.0.1` pour le support des modèles ZhipuAI (`111392888`)

### Changed

- Amélioration de la décomposition de requêtes en arbre (`tree_structured_query_decomposition_retrieval`) : meilleure gestion du total et des cas limites (`2eca7d7e2`)
- Synchronisation upstream RAGFlow `v0.25.1`

---

## [v0.25.0-eurelis.1] - 2026-04-21

Basé sur RAGFlow `v0.25.0`.

---

## [v0.24.0-eurelis.1] - 2026-04-06

Basé sur RAGFlow `v0.24.0`.

### Fixed

- Gestion du total dans la récupération d'informations — `tree_structured_query_decomposition_retrieval.py` (`9bba089ab`)
- Gestion des exceptions dans la méthode `research` et amélioration de la vérification de la suffisance (`33401e9e1`)
- Correction de l'initialisation de `kbinfos` dans `_retrieve_information` (`a0b7ce569`)

---

<!-- Template pour les prochaines releases :

## [vX.Y.Z-eurelis.N] - YYYY-MM-DD

Basé sur RAGFlow `vX.Y.Z`.

### Added
### Changed
### Fixed
### Removed

-->
