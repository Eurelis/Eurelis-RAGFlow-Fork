# Intégration Tavily — Recherche web dans le pipeline RAG

## Vue d'ensemble

La feature `eurelis/feature/tavily` (mergée dans `eurelis/main` le 2026-04-06) intègre [Tavily](https://tavily.com/) comme source de retrieval web complémentaire à la base de connaissances RAGFlow. Les résultats Tavily sont injectés dans le même pipeline que les chunks RAG, de façon transparente pour le LLM.

---

## Composants

| Fichier                                                             | Rôle                                                                    |
|---------------------------------------------------------------------|-------------------------------------------------------------------------|
| `rag/utils/tavily_conn.py`                                          | Wrapper autour du `TavilyClient` — recherche web et formatage en chunks |
| `rag/advanced_rag/tree_structured_query_decomposition_retrieval.py` | Deep Researcher — retrieval récursive multi-sources (mode reasoning)    |
| `api/db/services/dialog_service.py`                                 | Orchestrateur du pipeline de chat — point d'injection Tavily            |

---

## Flux d'exécution

### Mode standard

```
Question utilisateur
        │
        ▼
retriever.retrieval()          ← Base de connaissances RAG
        │
        ▼
Tavily.retrieve_chunks()       ← Recherche web (si tavily_api_key configuré)
        │
        ▼
kbinfos["chunks"]              ← Fusion dans la même structure
        │
        ▼
kb_prompt(kbinfos, max_tokens) ← Formatage uniforme
        │
        ▼
kwargs["knowledge"]            ← Injection dans le prompt système
        │
        ▼
prompt_config["system"].format(**kwargs)  ← Appel LLM
```

### Mode reasoning (Deep Research)

En mode `reasoning`, le `TreeStructuredQueryDecompositionRetrieval` orchestre une recherche récursive :

1. Récupération des chunks (KB + Tavily + KG) pour la question courante
2. Vérification de la suffisance via un LLM call (`sufficiency_check`)
3. Si insuffisant → génération de sous-questions (`multi_queries_gen`) et récursion (profondeur max 3)

Tavily est appelé à **chaque niveau de récursion**, permettant une exploration web guidée par le raisonnement du LLM.

---

## La variable `{knowledge}` dans le prompt système

### Condition de déclenchement

La retrieval complète (KB + Tavily + KG) n'est déclenchée **que si `knowledge` apparaît dans les paramètres du prompt config** :

```python
# dialog_service.py:533
param_keys = [p["key"] for p in prompt_config.get("parameters", [])]

if "knowledge" in param_keys:
    # → déclenche KB retrieval + Tavily + KG
```

Sans le placeholder `{knowledge}` dans le prompt système, aucune retrieval n'est effectuée, même si une base de connaissances ou une clé Tavily est configurée.

### Construction de la valeur

```python
# dialog_service.py:644-654
knowledges = kb_prompt(kbinfos, max_tokens)
# knowledges = liste de chaînes, une par chunk

kwargs["knowledge"] = "\n------\n" + "\n\n------\n\n".join(knowledges)
# → chaîne multi-chunks séparés par des lignes de tirets
```

### Format d'un chunk injecté (`kb_prompt`)

```
ID: 0
├── Title: Titre du document ou de la page web
├── URL: https://...         ← présent uniquement pour les chunks Tavily
└── Content:
    <contenu textuel du chunk>
```

Les chunks Tavily portent le champ `url` (absent des chunks RAG classiques), qui est affiché dans le prompt et utilisé pour les citations.

### Exemple de prompt système

```
Tu es un assistant. Réponds en te basant sur les informations suivantes :

{knowledge}

Si la réponse n'est pas dans les informations fournies, dis-le clairement.
```

Au moment de l'appel LLM, `{knowledge}` est remplacé par l'ensemble des chunks formatés, qu'ils proviennent de la base de connaissances RAG ou de Tavily.

---

## Configuration

### Activer Tavily sur un assistant

Dans la configuration du dialog (assistant RAGFlow), renseigner `tavily_api_key` dans `prompt_config` :

```json
{
  "tavily_api_key": "tvly-XXXXXXXXXXXX",
  "system": "Tu es un assistant. Réponds en te basant sur :\n\n{knowledge}",
  "parameters": [
    { "key": "knowledge", "optional": false }
  ]
}
```

### Tavily sans base de connaissances

Tavily peut fonctionner **seul**, sans aucune KB attachée. Le pipeline RAG complet est déclenché dès qu'une clé Tavily est présente :

```python
# dialog_service.py:464
if not dialog.kb_ids and not dialog.prompt_config.get("tavily_api_key"):
    async for ans in async_chat_solo(...):   # ← mode sans retrieval
        yield ans
    return
# sinon → pipeline RAG complet avec Tavily
```

---

## Points de vigilance

- **`{knowledge}` obligatoire dans le prompt** : sans ce placeholder (et le paramètre `knowledge` associé), la retrieval est silencieusement ignorée même si Tavily est configuré.
- **Déduplication** : en mode Deep Research, les chunks sont dédupliqués par `chunk_id` lors de la fusion (`_async_update_chunk_info`). Les chunks Tavily reçoivent un UUID généré à la volée — pas de déduplication inter-requêtes.
- **Limite de tokens** : `kb_prompt` tronque la liste de chunks si `max_tokens * 0.97` est atteint, les chunks Tavily étant ajoutés après les chunks KB, ils sont les premiers à être éliminés en cas de saturation.
