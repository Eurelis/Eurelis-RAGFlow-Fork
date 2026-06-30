---
title: "Spec — Contrôle de la profondeur de récursion Deep Research par chatbot"
type: feature
status: proposed
date: 2026-05-27
reviewed: 2026-06-28
---

# Spec — Contrôle de la profondeur de récursion Deep Research par chatbot

**Auteur** : Eurelis  
**Branche cible** : `eurelis/feature/deep-research-depth`

---

## Contexte

### Le mode reasoning de RAGFlow

Lorsque l'option `reasoning` est activée sur un chatbot, RAGFlow déclenche un pipeline d'orchestration appelé **Deep Research** (`DeepResearcher`, `TreeStructuredQueryDecompositionRetrieval`). Ce pipeline ne délègue pas le raisonnement au modèle — il implémente une boucle de retrieval itérative côté plateforme :

```
Question utilisateur
      │
      ▼
[Retrieval initial]
      │
      ▼
[Sufficiency check]  ← appel LLM : les docs sont-ils suffisants ?
      │ Non
      ▼
[Multi-query decomposition]  ← appel LLM : génère N sous-questions
      │
      ▼
[Retrieval récursif par sous-question]  ← jusqu'à depth fois
      │
      ▼
[Génération finale]
```

### Problème de consommation

La profondeur de récursion est actuellement **hardcodée à `depth=3`** dans :

- `rag/advanced_rag/tree_structured_query_decomposition_retrieval.py` — méthode `research(depth=3)`
- `api/db/services/dialog_service.py` — appel `reasoner.research(...)` sans paramètre depth

**Impact token au pire cas** (depth=3, 2 sous-questions par niveau) :

| Niveau | Retrievals | Appels LLM intermédiaires |
|--------|-----------|---------------------------|
| 0 | 1 | 1 sufficiency check |
| 1 | 2 | 2 sufficiency checks + 1 decomposition |
| 2 | 4 | 4 sufficiency checks + 2 decompositions |
| **Total** | **7** | **10 appels LLM** avant génération finale |

Chaque appel LLM intermédiaire inclut les chunks récupérés en contexte. La consommation réelle peut être **5 à 10× supérieure** à un échange simple.

### Demandes communautaires associées

- [#15206](https://github.com/infiniflow/ragflow/issues/15206) — reasoning trop lent, demande de modèle plus léger
- [#11990](https://github.com/infiniflow/ragflow/issues/11990) — budget token configurable avant opérations coûteuses
- [#15083](https://github.com/infiniflow/ragflow/issues/15083) — boucles infinies avec Qwen3 en mode thinking

---

## Objectif

Permettre de configurer la profondeur de récursion du Deep Research **par chatbot**, avec une valeur par défaut conservée à `3` pour préserver le comportement actuel.

---

## Solution proposée

### Principe

Ajouter un champ `research_depth` (entier, 1–3) dans `prompt_config` du chatbot. Ce champ est lu dans `dialog_service.py` et transmis à `DeepResearcher.research()`.

**Valeur par défaut : `3`** — aucun changement de comportement pour les chatbots existants.

### Sémantique des valeurs

| Valeur | Comportement |
|--------|-------------|
| `1` | 1 retrieval + 1 sufficiency check. Si insuffisant : 1 decomposition + N retrievals finaux. Pas de récursion. |
| `2` | Profondeur intermédiaire. Récursion sur 1 niveau de sous-questions. |
| `3` | Comportement actuel (défaut). Récursion complète sur 3 niveaux. |

---

## Implémentation technique

### 1. Schéma `prompt_config` — `api/db/db_models.py`

Ajouter `research_depth` dans le `default` du champ `prompt_config` du modèle `Dialog` :

```python
# Avant
prompt_config = JSONField(
    null=False,
    default={
        "system": "",
        "prologue": "Hi! I'm your assistant. What can I do for you?",
        "parameters": [],
        "empty_response": "Sorry! No relevant content was found in the knowledge base!",
    },
)

# Après
prompt_config = JSONField(
    null=False,
    default={
        "system": "",
        "prologue": "Hi! I'm your assistant. What can I do for you?",
        "parameters": [],
        "empty_response": "Sorry! No relevant content was found in the knowledge base!",
        "research_depth": 3,
    },
)
```

> **Note** : Pas de migration DB nécessaire — `prompt_config` est un champ JSON. Les chatbots existants sans `research_depth` reçoivent `3` via `.get("research_depth", 3)`.

---

### 2. Transmission au pipeline — `api/db/services/dialog_service.py`

Lire `research_depth` depuis `prompt_config` et le passer à `reasoner.research()` :

```python
# Localisation : ~ligne 710, après l'instanciation de DeepResearcher

research_depth = prompt_config.get("research_depth", 3)

# ...

task = asyncio.create_task(
    reasoner.research(
        kbinfos,
        questions[-1],
        questions[-1],
        depth=research_depth,   # ← ajout
        callback=callback,
    )
)
```

---

### 3. Frontend — paramètre dans les settings du chatbot

Ajouter un contrôle numérique (slider ou input 1–3) dans le panneau de configuration du chatbot, **visible uniquement lorsque `reasoning` est activé**.

**Fichiers concernés** (à identifier selon la structure UI existante) :
- `web/src/pages/next-chats/chat/app-settings/chat-settings.tsx` — ajout du champ
- `web/src/pages/next-chats/chat/app-settings/use-chat-setting-schema.tsx` — ajout dans le schéma Zod

**Schéma Zod** :

```typescript
// Dans use-chat-setting-schema.tsx
research_depth: z.number().int().min(1).max(3).default(3).optional(),
```

**Rendu UI** (conditionnel sur `reasoning === true`) :

```
┌─ Reasoning ──────────────────────────────────────────┐
│  [✓] Enable reasoning                                 │
│                                                       │
│  Research depth   [1] ── [2] ── [●3]                 │
│  ↑ Nombre de niveaux de récursion (1 = économique,   │
│    3 = complet). Défaut : 3.                          │
└───────────────────────────────────────────────────────┘
```

---

### 4. API REST — aucun changement breaking

Le champ `research_depth` est inclus dans `prompt_config` existant, déjà exposé dans les endpoints chatbot (`GET /api/v1/dialog`, `PUT /api/v1/dialog`). Pas de nouvel endpoint nécessaire.

Les appels API qui passent `reasoning: true` sans `research_depth` utilisent la valeur par défaut (`3`).

---

## Fichiers modifiés

| Fichier | Type de modification |
|---------|---------------------|
| `api/db/db_models.py` | Ajout de `research_depth: 3` dans le default de `prompt_config` |
| `api/db/services/dialog_service.py` | Lecture de `research_depth` + passage à `reasoner.research()` |
| `web/src/pages/next-chats/chat/app-settings/chat-settings.tsx` | Ajout du contrôle UI conditionnel |
| `web/src/pages/next-chats/chat/app-settings/use-chat-setting-schema.tsx` | Ajout du champ dans le schéma Zod |

**Fichiers non modifiés** :
- `rag/advanced_rag/tree_structured_query_decomposition_retrieval.py` — signature `research(depth=3)` conservée telle quelle
- `rag/prompts/generator.py` — aucun changement

---

## Tests

- [ ] Chatbot existant sans `research_depth` → comportement identique (depth=3)
- [ ] Chatbot avec `research_depth: 1` → 1 seul niveau de récursion, pas de sous-questions récursives
- [ ] Chatbot avec `research_depth: 2` → 2 niveaux, récursion interrompue au niveau 2
- [ ] `reasoning: false` → `research_depth` ignoré, champ UI masqué
- [ ] API `PUT /api/v1/dialog` avec `prompt_config.research_depth: 1` → persisté et utilisé

---

## Impact attendu sur les tokens

| Depth | Retrievals (pire cas) | LLM intermédiaires | Estimation réduction vs depth=3 |
|-------|-----------------------|--------------------|---------------------------------|
| 3 (défaut) | 7 | 10 | — |
| 2 | 3 | 4 | ~60% |
| 1 | 1+N | 2 | ~80% |

*N = nombre de sous-questions générées par le decomposition (typiquement 2–3).*
