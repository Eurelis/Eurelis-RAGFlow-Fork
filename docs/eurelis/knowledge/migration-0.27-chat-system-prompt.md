---
title: "Note de migration RAGFlow 0.27.x — prompts système des assistants de chat"
type: knowledge
status: reference
date: 2026-09-06
---

# Note de migration RAGFlow 0.27.x — prompts système des assistants de chat

Migration de configuration nécessaire sur une base existante après passage du fork sur RAGFlow `v0.27.x` : les assistants de chat qui conservent le **prompt système par défaut** (section « Voici la base de connaissances : `{knowledge}` ») répondent sans consulter la base documentaire dès que le niveau de raisonnement est différent de « Naive ». Cette note explique le mécanisme, comment identifier les assistants concernés, et comment réécrire leur prompt.

> Note sœur pour le sous-système des modèles : [`migration-0.27-model-registration.md`](migration-0.27-model-registration.md). Variables et paramètres d'un assistant : [`chat-app-variable-configuration.md`](chat-app-variable-configuration.md).

---

## 1. Ce qui change en 0.27 côté chat

Trois évolutions upstream se combinent.

| Changement | Avant (`v0.26.x`) | Après (`v0.27.x`) |
|---|---|---|
| Bouton « thinking » de la zone de saisie | Toggle booléen, **éteint** par défaut, non mémorisé. | Sélecteur de niveau Naive / Low / Medium / High / Ultra (`0`..`4`), mémorisé dans le `localStorage` du navigateur, **`Low` par défaut** (`web/src/utils/authorization-util.ts`, `getThinkingLevel`). |
| Chemin backend quand le raisonnement est actif | `DeepResearcher` : recherche pilotée par le backend, bloc `<retrieving>` visible. | `rag_agent` (`api/db/services/dialog_service.py`) : un **modèle externe** reçoit un prompt de routage et les outils `rag` / `summarize_document`. C'est lui qui décide d'appeler ou non le retrieval. Le bloc « Thinking » contient les logs agentiques. |
| Prompt système du dialogue en mode raisonnement | Ignoré. | Depuis le commit `146765f32` (#18927, repris dans le fork), le prompt système configuré est rendu par `_render_reasoning_system_prompt` et **préfixé au prompt de routage**. Le placeholder `{knowledge}` y est remplacé par une **chaîne vide**. |

Conséquence : un utilisateur qui n'a jamais touché au sélecteur envoie `reasoning=1` et passe par `rag_agent`, alors qu'en `0.26` il passait par le RAG classique.

---

## 2. Le problème avec le template par défaut

Le prompt système proposé par défaut à la création d'un assistant (`web/src/locales/fr.ts`, clé `chat.systemMessage`) se termine par :

```text
Lorsque tout le contenu de la base de connaissances est sans rapport avec la question,
votre réponse doit inclure la phrase "La réponse que vous cherchez ne se trouve pas dans
la base de connaissances !" […]
      Voici la base de connaissances : {knowledge}
      Ce qui précède est la base de connaissances.
```

En mode raisonnement, le modèle externe reçoit ce texte avec `{knowledge}` vide, suivi du prompt de routage « call the `rag` tool for any question that needs evidence ». Il voit une base de connaissances **explicitement vide**, obéit à la consigne du template et répond sans appeler `rag`.

### Symptômes observés

- **Réponse non ancrée** : le modèle répond de connaissance générale, pose des questions de précision, ou écrit « La réponse que vous cherchez ne se trouve pas dans la base de connaissances ! » alors que la base contient l'information. Observé sur l'assistant « Cyber Support » (gpt-5) : *« La base fournie ne contient qu'une mention générique : "Ce qui précède est la base de connaissances." »*.
- **Bloc « Thinking » invisible** : sans appel d'outil, aucun log agentique n'est produit. Le message persisté commence par `<think></think>` et le front masque les blocs vides (commit upstream `2611ea5bd`, #18608).
- **Log serveur** (`logs/ragflow_server.log`) :

```text
[Tool loop] Deciding what to do next (step 1); available tools: rag, summarize_document
[Tool loop] Answering directly at step 1 — no tool needed.
```

Le même assistant en niveau « Naive » (`reasoning=0`) répond correctement avec citations `[ID:n]` : le chemin `async_chat` fait toujours le retrieval avant d'appeler le modèle.

### Ce que ce n'est pas

- Ce n'est pas une perte du raisonnement natif du modèle. gpt-5 via l'API Chat Completions d'OpenAI ne renvoie pas de `reasoning_content` : il n'y a jamais eu de raisonnement natif à afficher pour ce modèle.
- Ce n'est pas lié aux marqueurs `<think>` du flux (corrigé par ailleurs, voir §7).

---

## 3. Identifier les assistants concernés

Tout assistant dont le prompt système contient encore le placeholder `{knowledge}` et qui est rattaché à au moins une base :

```sql
SELECT id, name, tenant_id, llm_id
FROM dialog
WHERE status = '1'
  AND JSON_UNQUOTE(JSON_EXTRACT(prompt_config, '$.system')) LIKE '%{knowledge}%'
  AND JSON_LENGTH(kb_ids) > 0;
```

Sur la base de développement au 2026-09-06 : 6 assistants sur 8 concernés.

Les assistants sans base (`kb_ids = []`) ne sont pas affectés par ce mécanisme, `rag_agent` n'ayant rien à interroger.

---

## 4. Migration : réécrire le prompt système

### Principe

Supprimer la section « base de connaissances » du prompt, et exprimer les consignes d'ancrage sans référence à un bloc de contexte inséré dans le prompt. Le prompt devient valable pour les deux chemins :

- **Niveau Naive** (`async_chat`) : le retrieval est déclenché par la présence du paramètre `knowledge` dans `prompt_config.parameters`, pas par le placeholder. Quand le template ne contient pas `{knowledge}`, les passages retrouvés sont **automatiquement concaténés** à la fin du prompt système (`dialog_service.py`, bloc « auto-append » après `prompt_config["system"].format(...)`).
- **Niveaux Low à Ultra** (`rag_agent`) : le prompt est préfixé au prompt de routage sans plus laisser croire que la base est vide. Le modèle externe appelle `rag`, et le prompt est aussi transmis au composeur de la réponse finale (`RAGTools.system_prompt`).

### Ce qu'il faut conserver

| Élément | Action |
|---|---|
| `prompt_config.parameters` contenant `{"key": "knowledge", "optional": false}` | **Conserver.** C'est lui qui active le retrieval en mode Naive. |
| Phrase d'absence « La réponse que vous cherchez ne se trouve pas dans la base de connaissances ! » | Conserver si le front ou le Shield la détecte, mais la conditionner aux **documents** et non au « contenu de la base ». |
| Placeholder `{knowledge}` et phrases « Voici la base de connaissances » / « Ce qui précède est la base de connaissances » | **Supprimer.** |
| Autres variables `{xxx}` déclarées dans `parameters` | Conserver, elles sont rendues dans les deux chemins. |

### Exemple : prompt réécrit pour « Cyber Support »

```text
Vous êtes l'assistant de support cyber de l'organisation. Vous aidez les équipes à retrouver
rapidement les informations opérationnelles de la base documentaire interne : contacts et
astreintes, procédures de gestion d'incident et de crise, rôles et responsabilités, consignes
de sécurité.

Règles :
- Répondez uniquement à partir des documents de la base documentaire. Ne complétez jamais avec
  des connaissances générales ni avec des contacts, numéros ou procédures inventés.
- Listez les données trouvées de façon précise et complète (noms, rôles, adresses, numéros,
  disponibilités), en conservant leur formulation d'origine.
- Si les documents ne contiennent pas l'information demandée, dites-le clairement en incluant
  la phrase : "La réponse que vous cherchez ne se trouve pas dans la base de connaissances !"
  puis proposez, si utile, une trame à compléter en la signalant explicitement comme telle.
- Tenez compte de l'historique de la discussion et répondez dans la langue de l'utilisateur.
```

---

## 5. Procédure

### Via l'interface

Chat → assistant → *Paramètres* → onglet *Prompt* → remplacer le champ « Système ». Ne pas retirer la variable `knowledge` de la liste des paramètres. Enregistrer. Aucun redémarrage : le dialogue est relu à chaque requête.

### Via SQL (base de développement, ou lot d'assistants)

Sauvegarder d'abord la configuration complète :

```bash
docker exec docker-mysql-1 mysql --default-character-set=utf8mb4 -u root -pinfini_rag_flow rag_flow -N -r \
  -e "SELECT prompt_config FROM dialog WHERE id='<dialog_id>';" > prompt_config.<dialog_id>.backup.json
```

Puis remplacer uniquement la clé `system` (le reste de `prompt_config` est préservé par `JSON_SET`) :

```sql
UPDATE dialog
SET prompt_config = JSON_SET(prompt_config, '$.system', '<nouveau prompt, apostrophes échappées \'>')
WHERE id = '<dialog_id>';
```

Toujours passer `--default-character-set=utf8mb4` au client MySQL du conteneur : sans cette option, les accents du prompt sont mal encodés à la lecture et à l'écriture.

---

## 6. Vérification

Rejouer la même question sur l'assistant migré aux deux extrémités du sélecteur :

| Niveau | Attendu dans le flux SSE | Attendu dans le log |
|---|---|---|
| `0` Naive | pas de `start_to_think`, réponse avec citations `[ID:n]` | `LLMBundle.async_chat_streamly_delta used_tokens` |
| `4` Ultra | `start_to_think`, bloc think rempli de logs `[Agentic RAG] …`, puis réponse citée | `[Tool loop] Step 1: running rag...` puis `The rag tool produced the final answer — done.` |

Résultat sur « Cyber Support » après migration (question « Quels sont nos contacts en cas de crise cyber ») : niveau 0 et niveau 4 renvoient tous deux la liste CSIRT citée. Le niveau 4 a duré environ 4 minutes avec gpt-5 : c'est le coût du mode `deep_research`, pas un dysfonctionnement.

Le script `test/eurelis/shield_contract/test_completions_reasoning.py` fige le contrat SSE des niveaux `0` et `1`, mais ne vérifie pas l'ancrage de la réponse.

---

## 7. Limites et suites

- **Correctif de fond non fait** : la vraie cause est `_render_reasoning_system_prompt` qui rend `{knowledge}` en chaîne vide. Remplacer ce vide par une mention du type « la base documentaire est interrogée via l'outil `rag` », ou ne pas préfixer un prompt contenant `{knowledge}`, corrigerait tous les assistants sans migration. Aucun commit ni PR upstream ne traite ce point au 2026-09-05. À proposer à l'upstream depuis le fork perso (voir le workflow de contribution).
- **Le routage reste probabiliste** : même avec un prompt sain, le modèle externe peut décider de répondre sans appeler `rag` (observé sur « Hello »). Pour le Shield, qui envoie le niveau sous forme de chaîne `"0"`..`"4"`, le niveau `"0"` est le seul qui garantit un retrieval systématique.
- **Correctifs upstream repris dans le fork** (cherry-picks `-x`, 2026-09-06) : `146765f32` (#18927, prompt système dans le routage, à l'origine du symptôme), `f300b154b` (#18983, repli sur le RAG classique quand le modèle n'a pas de tool-calling), `ef8b42488` (#19216, marqueurs `<think>` du flux), `867e4187e` (#19015, plus de `tools=[]`), `c9db6d3ab` (#19010, listes Markdown).
- **Correctifs upstream en attente de la prochaine synchro** : `175742590` (#19016, la recherche agentique ignorait les réglages de retrieval de l'assistant), `d0e22f4df` (#19209, streaming final non coupé par le budget de recherche), `880876f60` (#19112). Ils reposent sur le refactor `862ee95df` absent de `v0.27.1` et ne se cherry-pickent pas proprement.
