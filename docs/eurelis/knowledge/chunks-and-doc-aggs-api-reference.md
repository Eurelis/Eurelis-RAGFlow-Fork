# Relation `chunks` et `doc_aggs` dans les réponses de l'API Chat

**Audience :** développeurs frontend  
**Endpoints concernés :** `POST /chats/{chat_id}/completions`, `POST /chats/{chat_id}/sessions/{session_id}/completions`  
**Date :** 2026-04-21

---

## 1. Vue d'ensemble

La réponse de l'endpoint session retourne l'intégralité de la conversation dans `data.messages`, et les sources RAG dans `data.reference` :

```json
{
  "code": 0,
  "data": {
    "id": "cdd2f45e3d5911f1bd312fd2c816a7f2",
    "chat_id": "c8d26c62328e11f18b2069a267165908",
    "name": "my_custom_user_id",
    "messages": [
      { "role": "assistant", "content": "Bonjour ! Je suis votre assistant..." },
      { "role": "user",      "content": "Quelles est la roadmap...", "id": "45d8b18e-..." },
      { "role": "assistant", "content": "Voici la roadmap...", "id": "45d8b18e-...", "created_at": 1776759146.07 }
    ],
    "reference": [
      {
        "chunks":   [...],
        "doc_aggs": [...],
        "total":    64
      }
    ]
  }
}
```

Points structurels importants :

- **`data.reference` est un tableau**. Chaque élément correspond à un tour de l'assistant ayant utilisé le RAG. L'indice 0 correspond au premier tour RAG (ici `messages[2]`).
- Le message d'accueil initial de l'assistant (sans RAG) n'a pas d'entrée dans `reference`.
- Chaque entrée de `reference` contient :
  - **`chunks`** — les extraits de texte individuels récupérés dans la base de connaissances
  - **`doc_aggs`** — une agrégation par document source, avec le nombre de chunks candidats
  - **`total`** — nombre total de chunks candidats lors du retrieval (avant filtrage par citation)

La relation est **1 document → N chunks** : `doc_aggs` regroupe les chunks par `document_id`.

---

## 2. Structure détaillée des champs

### `chunks` — Tableau d'extraits

Chaque élément correspond à un passage de texte indexé, **trié par score de similarité décroissant**.

```typescript
interface Chunk {
  id: string;                       // Identifiant unique du chunk (ex: "9f8273c704763c0f")
  content: string;                  // Texte de l'extrait (prêt à afficher)
  document_id: string;              // Identifiant du document parent
  document_name: string;            // Nom du fichier source
  dataset_id: string;               // Identifiant de la base de connaissances
  image_id: string | null;          // "{dataset_id}-{chunk_id}" pour les documents visuels
  positions: [number, number, number, number, number][];
                                    // Tableau de positions : [page, x0, x1, y_top, y_bottom]
  url: string | null;               // URL source (null pour les fichiers locaux)
  similarity: number;               // Score global [0, 1]
  vector_similarity: number;        // Score sémantique (embeddings) [0, 1]
  term_similarity: number;          // Score lexical (BM25) [0, 1]
  doc_type: string;                 // Type de document ; peut être "" pour les PDFs
}
```

> **`positions`** : chaque sous-tableau décrit un rectangle dans le document source —
> `[numéro_page, x_gauche, x_droite, y_haut, y_bas]`. Un même chunk peut couvrir
> plusieurs rectangles (ex: texte sur deux colonnes ou plusieurs pages).

> **`image_id`** : pour les documents visuels (PDF, images), vaut
> `"{dataset_id}-{chunk_id}"`. Permet de charger la vignette du passage via l'API image.

### `doc_aggs` — Tableau de documents sources agrégés

Chaque élément représente un document dont au moins un chunk a été retenu, **trié par `count` décroissant**.

```typescript
interface DocAgg {
  doc_id: string;    // Identifiant du document
  doc_name: string;  // Nom du fichier
  count: number;     // Nombre de chunks candidats de ce document dans le pool de retrieval
}
```

> **Sémantique de `count`** : ce compteur représente le nombre de chunks de ce document
> dans le **pool de retrieval complet** (limité par `top_n`), et non le nombre de chunks
> présents dans le tableau `chunks` (qui ne contient que les chunks effectivement cités).
> Exemple : `count: 16` signifie que 16 chunks de ce document ont été récupérés au total,
> même si seulement 4 apparaissent dans `chunks`.

> **Invariant garanti par le backend** : si `quote: true` est activé dans la config du
> chatbot (comportement par défaut), `doc_aggs` ne contient que les documents
> **effectivement cités** dans la réponse du LLM (marqueurs `[ID:N]`). Si aucun document
> n'est explicitement cité, `doc_aggs` contient tous les documents retriévés.

---

## 3. Relation entre `chunks` et `doc_aggs`

```
chunks[i].document_id   ←→  doc_aggs[j].doc_id
chunks[i].document_name ←→  doc_aggs[j].doc_name
```

Exemple extrait de la réponse réelle (8 chunks cités, 5 documents sources) :

```json
{
  "chunks": [
    {
      "id": "a59a9135f1e82a71",
      "document_id": "c6cdf5d4328511f18b2069a267165908",
      "document_name": "Je découvre la facturation électronique _impots.gouv.fr.pdf",
      "similarity": 0.2861,
      "vector_similarity": 0.6728,
      "term_similarity": 0.1203,
      "content": "A quelle date dois-je etre pret ?..."
    },
    {
      "id": "e285f9a58322beb1",
      "document_id": "c62dbf06328511f18b2069a267165908",
      "document_name": "faq---fe_je-decouvre-la-facturation-electronique.pdf",
      "similarity": 0.2781,
      "content": "5.1 Quel est le calendrier de l'obligation..."
    }
  ],
  "doc_aggs": [
    { "doc_id": "c5f0a1c0328511f18b2069a267165908",
      "doc_name": "Facturation électronique entre entreprises... .pdf",
      "count": 16 },
    { "doc_id": "c5dbcb92328511f18b2069a267165908",
      "doc_name": "Facturation électronique _ quelles sont les Plateformes Agréées... .pdf",
      "count": 8 },
    { "doc_id": "c6e88be2328511f18b2069a267165908",
      "doc_name": "L'annuaire de la facturation électronique... .pdf",
      "count": 5 },
    { "doc_id": "c62dbf06328511f18b2069a267165908",
      "doc_name": "faq---fe_je-decouvre-la-facturation-electronique.pdf",
      "count": 5 },
    { "doc_id": "c6cdf5d4328511f18b2069a267165908",
      "doc_name": "Je découvre la facturation électronique _impots.gouv.fr.pdf",
      "count": 4 }
  ],
  "total": 64
}
```

Lecture : `total: 64` chunks ont été récupérés au total lors du retrieval. `doc_aggs`
en liste 5 documents cités avec leurs comptes respectifs (16 + 8 + 5 + 5 + 4 = 38 chunks
parmi les cités). Les 26 chunks restants (64 − 38) proviennent de documents non cités par
le LLM, absents de `doc_aggs`.

`doc_aggs` est une table de lookup permettant d'afficher une liste de sources sans itérer
sur tous les chunks.

---

## 4. Comportement en mode stream

En stream (`stream: true`), les données arrivent en plusieurs événements SSE :

```
data: {"code":0,"data":{"answer":"La réponse","reference":{},"final":false}}
data: {"code":0,"data":{"answer":" se construit","reference":{},"final":false}}
...
data: {"code":0,"data":{"answer":"","reference":{"chunks":[...],"doc_aggs":[...]},"final":true}}
data: {"code":0,"data":true}
```

| Condition | Action |
|-----------|--------|
| `final === false` | Concaténer `data.answer` au texte affiché ; ignorer `reference` (vide) |
| `final === true` | Ne **pas** concaténer `answer` (vide) ; utiliser `reference` pour afficher les sources |
| Dernier event (`data === true`) | Fin du stream, arrêter la lecture |

En mode **non-stream**, la réponse unique retourne le tableau `data.messages` complet et
`data.reference` indexé par tour RAG.

Exemple de traitement TypeScript (mode stream) :

```typescript
let answer = "";
let reference: Reference | null = null;

for await (const event of streamEvents) {
  if (event.data === true) break;

  const { answer: chunk, reference: ref, final } = event.data;

  if (!final) {
    answer += chunk;
    updateAnswerUI(answer);
  } else {
    reference = ref;
    updateSourcesUI(reference);
  }
}
```

---

## 5. Cas particuliers

| Cas | Comportement |
|-----|--------------|
| Aucun document trouvé | `chunks: []`, `doc_aggs: []`, `total: 0` |
| Requête SQL (feature SQL RAG) | `chunks` contient des entrées avec uniquement `doc_id` et `docnm_kwd` — pas de `content`, `similarity`, etc. |
| Document de type image/visuel | `image_id` vaut `"{dataset_id}-{chunk_id}"` ; `content` peut contenir du texte OCR |
| `url` renseigné | La source est une page web ; utiliser `url` comme lien direct plutôt que de naviguer vers le document interne |
| `doc_type: ""`  | Valeur courante pour les PDFs indexés sans typage explicite ; traiter comme PDF par défaut |
| `positions: []` | Chunk sans localisation précise (ex: chunk synthétique ou issu du graph RAG) |

---

## 6. Spécification d'affichage recommandée

### Panneau "Sources"

Utiliser `doc_aggs` (plus léger) pour la liste initiale des sources.

```
┌─────────────────────────────────────────────────────────────────┐
│ Sources (5)                                                     │
├─────────────────────────────────────────────────────────────────┤
│ 📄 Facturation électronique entre entreprises...pdf  [16 chunks]│
│ 📄 Facturation électronique _ quelles sont les PA...pdf [8]     │
│ 📄 L'annuaire de la facturation électronique...pdf      [5]     │
│ 📄 faq---fe_je-decouvre-la-facturation-electronique.pdf [5]     │
│ 📄 Je découvre la facturation électronique _impots.pdf  [4]     │
└─────────────────────────────────────────────────────────────────┘
```

- Le `count` sert d'indicateur de pertinence relative entre documents
- Lier chaque ligne à la liste filtrée : `chunks.filter(c => c.document_id === doc.doc_id)`

### Détail des chunks (au clic sur un document)

```
┌─────────────────────────────────────────────────────────────────┐
│ Je découvre la facturation électronique — Extrait 1 (28,6 %)   │
├─────────────────────────────────────────────────────────────────┤
│ "A quelle date dois-je etre pret ?                              │
│  Toutes les entreprises, quelle que soit leur taille, sont      │
│  concernées par la réforme dès le 1er septembre 2026..."        │
│                                                                 │
│ Pertinence sémantique : 67,3 %   Lexicale : 12,0 %             │
└─────────────────────────────────────────────────────────────────┘
```

- Trier les chunks d'un document par `similarity` décroissant
- Afficher `content` tel quel (peut contenir du Markdown selon la config)
- `positions[i]` permet d'ouvrir le document à la bonne page (si viewer intégré) :
  `positions[0][0]` = numéro de page (base 1)
- Ne pas exposer les labels techniques `vector_similarity`/`term_similarity` tels quels ;
  convertir en pourcentages

---

## 7. Exemple complet annoté

Extrait de réponse réelle (session non-stream, 1 tour utilisateur) :

```json
{
  "code": 0,
  "data": {
    "id":      "cdd2f45e3d5911f1bd312fd2c816a7f2",   // session_id
    "chat_id": "c8d26c62328e11f18b2069a267165908",
    "name":    "my_custom_user_id",                   // identifiant côté client
    "user_id": "66516d6a0fff11f1831fefbd69143e56",
    "create_date": "2026-04-21T10:12:13",
    "update_date": "2026-04-21T10:12:26",
    "messages": [
      {
        "role":    "assistant",
        "content": "Bonjour ! Je suis votre assistant, que puis-je faire pour vous ?"
        // pas d'id ni de created_at → message d'accueil, aucune entrée dans reference
      },
      {
        "role":    "user",
        "content": "Quelles est la roadmap prévue pour la mise en place de la facturation électronique ?",
        "id":      "45d8b18e-fb9f-4cb8-a6e7-3da33e17be5a"
      },
      {
        "role":       "assistant",
        "content":    "Voici la « roadmap » officielle... [ID:1][ID:2]...",
        "id":         "45d8b18e-fb9f-4cb8-a6e7-3da33e17be5a", // même id que la question
        "created_at": 1776759146.0702586
      }
    ],
    "reference": [
      // référence[0] → premier tour RAG = messages[2]
      {
        "total": 64,         // chunks récupérés au total lors du retrieval
        "chunks": [
          {
            "id":              "a59a9135f1e82a71",
            "content":         "A quelle date dois-je etre pret ?...",
            "dataset_id":      "7285cc7c328511f18b2069a267165908",
            "document_id":     "c6cdf5d4328511f18b2069a267165908",
            "document_name":   "Je découvre la facturation électronique _impots.gouv.fr.pdf",
            "doc_type":        "",            // vide = PDF sans typage explicite
            "image_id":        "7285cc7c328511f18b2069a267165908-a59a9135f1e82a71",
            "url":             null,          // fichier local, pas d'URL externe
            "similarity":      0.2861,        // score global = combinaison des deux ci-dessous
            "vector_similarity": 0.6728,      // similarité cosinus (embedding)
            "term_similarity": 0.1203,        // BM25
            "positions": [
              [2, 38, 246, 563, 580],         // [page, x0, x1, y_top, y_bottom]
              [2, 38, 540, 598, 615],
              [2, 40, 538, 619, 634]
              // ... autres rectangles couverts par ce chunk
            ]
          }
          // ... 7 autres chunks
        ],
        "doc_aggs": [
          // trié par count décroissant = document le plus représenté en premier
          {
            "doc_id":   "c5f0a1c0328511f18b2069a267165908",
            "doc_name": "Facturation électronique entre entreprises _ une obligation...pdf",
            "count":    16   // 16 chunks de ce doc dans le pool retrieval (4 présents dans chunks[])
          },
          {
            "doc_id":   "c5dbcb92328511f18b2069a267165908",
            "doc_name": "Facturation électronique _ quelles sont les Plateformes Agréées...pdf",
            "count":    8
          },
          {
            "doc_id":   "c6e88be2328511f18b2069a267165908",
            "doc_name": "L'annuaire de la facturation électronique _ pivot de la transmission...pdf",
            "count":    5
          },
          {
            "doc_id":   "c62dbf06328511f18b2069a267165908",
            "doc_name": "faq---fe_je-decouvre-la-facturation-electronique.pdf",
            "count":    5
          },
          {
            "doc_id":   "c6cdf5d4328511f18b2069a267165908",
            "doc_name": "Je découvre la facturation électronique _impots.gouv.fr.pdf",
            "count":    4   // 4 chunks dans pool, 1 dans chunks[] → très pertinent mais peu couvrant
          }
        ]
      }
    ]
  },
  "message": "success"
}
```

### Lecture des scores de similarité

Pour le chunk `a59a9135f1e82a71` :

| Champ | Valeur | Interprétation |
|-------|--------|----------------|
| `similarity` | 0.2861 | Score hybride pondéré (seuil typique ≥ 0.2) |
| `vector_similarity` | 0.6728 | Forte correspondance sémantique |
| `term_similarity` | 0.1203 | Faible correspondance lexicale (peu de mots communs exacts) |

Le score global étant inférieur au score vectoriel, cela indique que la pondération
`term_similarity` tire le score vers le bas — ce qui est normal pour une question
reformulée différemment du texte source.

### Réconciliation `chunks` ↔ `doc_aggs`

```
chunks[] (8 entrées, cités par le LLM)          doc_aggs[] (5 documents)
─────────────────────────────────────           ──────────────────────────────
9f8273c704763c0f → c5f0a1c0...  ─┐             c5f0a1c0...  count:16
6973dceec8bc94b2 → c5f0a1c0...   ├──────────►  (4 chunks présents dans chunks[])
39fe41a79866798a → c5f0a1c0...   │
389f583c8586af52 → c5f0a1c0...  ─┘

a59a9135f1e82a71 → c6cdf5d4...  ─────────────► c6cdf5d4...  count:4
c79df32d58db2cd9 → c5dbcb92...  ─────────────► c5dbcb92...  count:8
2504ae65e3e3345c → c6e88be2...  ─────────────► c6e88be2...  count:5
e285f9a58322beb1 → c62dbf06...  ─────────────► c62dbf06...  count:5
```

---

## 8. Chemins de code clés

| Responsabilité | Fichier | Lignes |
|---|---|---|
| Endpoint API | `api/apps/restful_apis/chat_api.py` | 940–1016 |
| Construction chunks + doc_aggs | `rag/nlp/search.py` | 466–519 |
| Filtrage par citation (quote) | `api/db/services/dialog_service.py` | 681–705 |
| Formatage final des chunks | `rag/prompts/generator.py` | 40–63 |
| Structuration réponse | `api/db/services/conversation_service.py` | 69–110 |
| Types TypeScript existants | `web/src/interfaces/database/chat.ts` | 109–151 |
