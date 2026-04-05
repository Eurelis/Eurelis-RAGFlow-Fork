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
      { "role": "assistant", "content": "Voici la roadmap... [ID:1][ID:2]", "id": "45d8b18e-...", "created_at": 1776759146.07 }
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
  - **`total`** — nombre total de résultats dans le moteur de recherche pour la requête

La relation est **1 document → N chunks** : `doc_aggs` regroupe les chunks par `document_id`.

---

## 2. Mécanisme des marqueurs `[ID:N]` dans le contenu

Les marqueurs `[ID:N]` visibles dans `messages[i].content` sont la clé de voûte du système de citations. Ils font le lien direct entre le texte de la réponse et les chunks de `reference`.

### Flow complet : du retrieval à la réponse

```
┌─────────────────────────────────────────────────────────────────────┐
│ 1. RETRIEVAL                                                        │
│    top_k (ex: 1024) résultats bruts récupérés dans l'index          │
│    → valid_idx (ex: 64 après filtrage par similarity_threshold)     │
│                                                                     │
│ 2. PAGINATION DES CHUNKS                                            │
│    kbinfos["chunks"] = valid_idx[0 : top_n]   (ex: top_n = 8)      │
│    kbinfos["doc_aggs"] = comptage sur valid_idx ENTIER              │
│    kbinfos["total"] = total hits dans le moteur de recherche        │
│                                                                     │
│ 3. CONSTRUCTION DU PROMPT  (generator.py:137-147)                   │
│    for i, ck in enumerate(kbinfos["chunks"][:chunks_num]):          │
│        cnt = "ID: {i}"          ← l'indice 0-based devient le [ID]  │
│        cnt += "Title: {docnm}"                                      │
│        cnt += "Content: {texte}"                                    │
│    → transmis au LLM avec l'instruction de citer via [ID:N]         │
│                                                                     │
│ 4. RÉPONSE DU LLM                                                   │
│    "À partir du 1er sept. 2026 [ID:1][ID:4], toutes les             │
│     entreprises devront recevoir les factures électroniques."        │
│                                                                     │
│ 5. POST-TRAITEMENT  (dialog_service.py:681-705)                     │
│    a. Extraction des N depuis [ID:N]                                │
│    b. Validation : N < len(kbinfos["chunks"])                       │
│    c. Mappage    : N → kbinfos["chunks"][N]["doc_id"]               │
│    d. Filtrage   : doc_aggs ← uniquement les doc_id cités           │
│                                                                     │
│ 6. RÉPONSE API                                                      │
│    messages[i].content = texte avec [ID:N] intacts                 │
│    reference[j].chunks = kbinfos["chunks"] (top_n entrées)         │
│    reference[j].doc_aggs = doc_aggs filtrés (docs cités)           │
└─────────────────────────────────────────────────────────────────────┘
```

### Règle fondamentale

> **`[ID:N]` dans `messages[i].content` correspond exactement à `reference[j].chunks[N]`**
> (indice 0-based dans le tableau `chunks`).

### Exemple de résolution avec les données réelles

Le texte de la réponse contient :

```
"À partir du 1er septembre 2026, toutes les entreprises seront tenues de recevoir
les factures électroniques. [ID:1][ID:4][ID:6]"
```

Résolution :

| Marqueur | `chunks[N].id`     | `chunks[N].document_name`                                    |
|----------|--------------------|--------------------------------------------------------------|
| `[ID:1]` | `a59a9135f1e82a71` | Je découvre la facturation électronique \_impots.gouv.fr.pdf |
| `[ID:4]` | `6973dceec8bc94b2` | Facturation électronique entre entreprises...pdf             |
| `[ID:6]` | `e285f9a58322beb1` | faq---fe\_je-decouvre-la-facturation-electronique.pdf        |

### Insertion automatique de citations

Si le LLM ne place aucun `[ID:N]` dans sa réponse, le backend insère automatiquement des
citations via `retriever.insert_citations()` (`dialog_service.py:685-692`). Cette fonction :

1. Découpe la réponse en phrases
2. Compare chaque phrase aux chunks (similarité hybride BM25 + vecteur)
3. Insère `[ID:N]` pour le chunk le plus proche de chaque phrase

Le comportement est contrôlable via `quote: true/false` dans la configuration du chatbot.

### Réparation des mauvais formats

Le backend normalise plusieurs variantes produites par certains LLMs
(`dialog_service.py:405-410`) :

| Format produit par le LLM | Normalisé en |
|---------------------------|--------------|
| `(ID: 3)`                 | `[ID:3]`     |
| `[ID: 3]`                 | `[ID:3]`     |
| `【ID: 3】`               | `[ID:3]`     |
| `ref3` / `REF 3`          | `[ID:3]`     |
| `[3]`                     | `[ID:3]`     |

---

## 3. Structure détaillée des champs

### `chunks` — Tableau d'extraits

`chunks[]` contient les `top_n` chunks récupérés et transmis au LLM, **triés par score de
similarité décroissant**. Tous les chunks du tableau sont présents dans la réponse, qu'ils
soient cités ou non par le LLM.

```typescript
interface Chunk {
  id: string;                       // Identifiant unique du chunk (ex: "9f8273c704763c0f")
  content: string;                  // Texte de l'extrait (prêt à afficher)
  document_id: string;              // Identifiant du document parent
  document_name: string;            // Nom du fichier source
  dataset_id: string;               // Identifiant de la base de connaissances
  image_id: string | null;          // "{dataset_id}-{chunk_id}" pour les documents visuels
  positions: [number, number, number, number, number][];
                                    // Tableau de rectangles : [page, x0, x1, y_top, y_bottom]
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
>
> **`image_id`** : pour les documents visuels (PDF, images), vaut
> `"{dataset_id}-{chunk_id}"`. Permet de charger la vignette du passage via l'API image.

### `doc_aggs` — Tableau de documents sources agrégés

Chaque élément représente un document **effectivement cité** dans la réponse du LLM via
`[ID:N]`, **trié par `count` décroissant**.

```typescript
interface DocAgg {
  doc_id: string;    // Identifiant du document
  doc_name: string;  // Nom du fichier
  count: number;     // Chunks de ce doc dans le pool de retrieval COMPLET (pas juste top_n)
}
```

> **Sémantique de `count`** : ce compteur est calculé sur l'ensemble des résultats du
> retrieval (`valid_idx`, potentiellement bien plus grand que `top_n`). Il reflète la
> densité de présence du document dans la base, pas seulement dans la réponse courante.
> Exemple : `count: 16` signifie que 16 chunks de ce document ont été récupérés dans le
> pool, même si seulement 4 apparaissent dans `chunks[]`.
>
> **Filtrage** : si `quote: true` (comportement par défaut), `doc_aggs` ne contient que
> les documents cités par le LLM. En l'absence de toute citation, `doc_aggs` conserve
> tous les documents retriévés (`dialog_service.py:702-705`).

---

## 4. Relation entre `chunks`, `doc_aggs` et le contenu du message

```
messages[k].content          reference[j].chunks[]          reference[j].doc_aggs[]
────────────────────          ──────────────────────          ───────────────────────
"... [ID:0] ..."     ──────►  chunks[0].document_id  ──────►  doc_aggs[?].doc_id
"... [ID:1] ..."     ──────►  chunks[1].document_id      ↕    doc_aggs[?].count
"... [ID:4] ..."     ──────►  chunks[4].document_id      └─── agrégation par document
```

Correspondances de champs :

```
chunks[i].document_id   ←→  doc_aggs[j].doc_id
chunks[i].document_name ←→  doc_aggs[j].doc_name
```

Exemple extrait de la réponse réelle (8 chunks transmis au LLM, 5 documents cités) :

```json
{
  "chunks": [
    {
      "id": "a59a9135f1e82a71",
      "document_id": "c6cdf5d4328511f18b2069a267165908",
      "document_name": "Je découvre la facturation électronique _impots.gouv.fr.pdf",
      "similarity": 0.2861,
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

Lecture : `total: 64` hits dans le moteur de recherche. `chunks[]` contient les 8 premiers
après scoring. `doc_aggs` (16 + 8 + 5 + 5 + 4 = 38) compte les chunks dans le pool élargi
pour les 5 documents que le LLM a cités. Les 26 hits restants (64 − 38) proviennent de
documents non cités, absents de `doc_aggs`.

---

## 5. Comportement en mode stream

En stream (`stream: true`), les données arrivent en plusieurs événements SSE :

```
data: {"code":0,"data":{"answer":"La réponse","reference":{},"final":false}}
data: {"code":0,"data":{"answer":" se construit","reference":{},"final":false}}
...
data: {"code":0,"data":{"answer":"","reference":{"chunks":[...],"doc_aggs":[...]},"final":true}}
data: {"code":0,"data":true}
```

| Condition                       | Action                                                                                 |
|---------------------------------|----------------------------------------------------------------------------------------|
| `final === false`               | Concaténer `data.answer` au texte affiché ; ignorer `reference` (vide)                 |
| `final === true`                | Ne **pas** concaténer `answer` (vide) ; utiliser `reference` pour afficher les sources |
| Dernier event (`data === true`) | Fin du stream, arrêter la lecture                                                      |

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

## 6. Cas particuliers

| Cas                           | Comportement                                                                                                  |
|-------------------------------|---------------------------------------------------------------------------------------------------------------|
| Aucun document trouvé         | `chunks: []`, `doc_aggs: []`, `total: 0`                                                                      |
| Requête SQL (feature SQL RAG) | `chunks` contient des entrées avec uniquement `doc_id` et `docnm_kwd` — pas de `content`, `similarity`, etc.  |
| Document de type image/visuel | `image_id` vaut `"{dataset_id}-{chunk_id}"` ; `content` peut contenir du texte OCR                            |
| `url` renseigné               | La source est une page web ; utiliser `url` comme lien direct plutôt que de naviguer vers le document interne |
| `doc_type: ""`                | Valeur courante pour les PDFs indexés sans typage explicite ; traiter comme PDF par défaut                    |
| `positions: []`               | Chunk sans localisation précise (ex: chunk synthétique ou issu du graph RAG)                                  |

---

## 7. Spécification d'affichage recommandée

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

### Citations inline dans le texte

Pour chaque `[ID:N]` présent dans `messages[i].content` :

```typescript
// Résoudre un marqueur [ID:N] vers son chunk source
function resolveChunkRef(n: number, reference: Reference): Chunk | undefined {
  return reference.chunks[n];
}

// Remplacer les [ID:N] par des liens cliquables dans le rendu
const rendered = content.replace(
  /\[ID:(\d+)\]/g,
  (_, n) => {
    const chunk = resolveChunkRef(Number(n), reference);
    if (!chunk) return "";
    return `<cite data-chunk-id="${chunk.id}">[${Number(n) + 1}]</cite>`;
  }
);
```

### Détail des chunks (au clic sur un document ou une citation)

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
- `positions[i][0]` = numéro de page (base 1) pour ouvrir le document au bon endroit
- Ne pas exposer `vector_similarity`/`term_similarity` tels quels ; convertir en pourcentages

---

## 8. Exemple complet annoté

Extrait de réponse réelle (session non-stream, 1 tour utilisateur) :

```json
{
  "code": 0,
  "data": {
    "id":      "cdd2f45e3d5911f1bd312fd2c816a7f2",
    "chat_id": "c8d26c62328e11f18b2069a267165908",
    "name":    "my_custom_user_id",
    "user_id": "66516d6a0fff11f1831fefbd69143e56",
    "create_date": "2026-04-21T10:12:13",
    "update_date": "2026-04-21T10:12:26",
    "messages": [
      {
        "role":    "assistant",
        "content": "Bonjour ! Je suis votre assistant, que puis-je faire pour vous ?"
      },
      {
        "role":    "user",
        "content": "Quelles est la roadmap prévue pour la mise en place de la facturation électronique ?",
        "id":      "45d8b18e-fb9f-4cb8-a6e7-3da33e17be5a"
      },
      {
        "role":    "assistant",
        "content": "Voici la roadmap... [ID:1][ID:2][ID:4][ID:6]\n\n...\n- 01/09/2026 : tout le monde doit savoir recevoir. [ID:1][ID:4][ID:6]\n- 01/09/2027 : les TPE/PME doivent émettre. [ID:1][ID:4][ID:6]",
        "id":         "45d8b18e-fb9f-4cb8-a6e7-3da33e17be5a",
        "created_at": 1776759146.0702586
      }
    ],
    "reference": [
      {
        "total": 64,
        "chunks": [
          { "id": "9f8273c704763c0f",  "document_id": "c5f0a1c0...", "similarity": 0.2941, "content": "..." },
          { "id": "a59a9135f1e82a71",  "document_id": "c6cdf5d4...", "similarity": 0.2861, "content": "A quelle date dois-je etre pret ?..." },
          { "id": "2504ae65e3e3345c",  "document_id": "c6e88be2...", "similarity": 0.2836, "content": "→ facturation électronique Ce référentiel..." },
          { "id": "c79df32d58db2cd9",  "document_id": "c5dbcb92...", "similarity": 0.2804, "content": "impose a toutes les entreprises..." },
          { "id": "6973dceec8bc94b2",  "document_id": "c5f0a1c0...", "similarity": 0.2797, "content": "La facture électronique va devenir..." },
          { "id": "39fe41a79866798a",  "document_id": "c5f0a1c0...", "similarity": 0.2797, "content": "impose a toutes les entreprises..." },
          { "id": "e285f9a58322beb1",  "document_id": "c62dbf06...", "similarity": 0.2781, "content": "5. Facturation électronique..." },
          { "id": "389f583c8586af52",  "document_id": "c5f0a1c0...", "similarity": 0.2684, "content": "L'annuaire de la facturation..." }
        ],
        "doc_aggs": [
          { "doc_id": "c5f0a1c0...", "doc_name": "Facturation électronique entre entreprises...pdf", "count": 16 },
          { "doc_id": "c5dbcb92...", "doc_name": "Facturation électronique _ quelles sont les PA...pdf", "count": 8 },
          { "doc_id": "c6e88be2...", "doc_name": "L'annuaire de la facturation électronique...pdf", "count": 5 },
          { "doc_id": "c62dbf06...", "doc_name": "faq---fe_je-decouvre-la-facturation-electronique.pdf", "count": 5 },
          { "doc_id": "c6cdf5d4...", "doc_name": "Je découvre la facturation électronique _impots.pdf", "count": 4 }
        ]
      }
    ]
  },
  "message": "success"
}
```

### Résolution des marqueurs dans cet exemple

Le texte `"[ID:1][ID:4][ID:6]"` dans `messages[2].content` se résout via `reference[0]` :

| Marqueur | Index | `chunks[N].id`     | Document source                                              |
|----------|-------|--------------------|--------------------------------------------------------------|
| `[ID:1]` | 1     | `a59a9135f1e82a71` | Je découvre la facturation électronique \_impots.gouv.fr.pdf |
| `[ID:4]` | 4     | `6973dceec8bc94b2` | Facturation électronique entre entreprises...pdf             |
| `[ID:6]` | 6     | `e285f9a58322beb1` | faq---fe\_je-decouvre-la-facturation-electronique.pdf        |

### Lecture des scores de similarité

Pour le chunk `a59a9135f1e82a71` (`chunks[1]`) :

| Champ               | Valeur | Interprétation                                              |
|---------------------|--------|-------------------------------------------------------------|
| `similarity`        | 0.2861 | Score hybride pondéré (seuil typique ≥ 0.2)                 |
| `vector_similarity` | 0.6728 | Forte correspondance sémantique                             |
| `term_similarity`   | 0.1203 | Faible correspondance lexicale (peu de mots communs exacts) |

Le score global étant inférieur au score vectoriel, la pondération `term_similarity` tire
le résultat vers le bas — normal pour une question reformulée différemment du texte source.

### Réconciliation `chunks` ↔ `doc_aggs`

```
chunks[] (8 entrées, top_n transmis au LLM)       doc_aggs[] (5 documents cités)
───────────────────────────────────────────        ───────────────────────────────
[0] 9f8273c7 → c5f0a1c0  ─┐                       c5f0a1c0  count:16
[4] 6973dcee → c5f0a1c0   ├──────────────────────► (4 chunks dans chunks[], cités via [ID:0,4,5,7])
[5] 39fe41a7 → c5f0a1c0   │
[7] 389f583c → c5f0a1c0  ─┘

[1] a59a9135 → c6cdf5d4  ──────────────────────── ► c6cdf5d4  count:4
[3] c79df32d → c5dbcb92  ──────────────────────── ► c5dbcb92  count:8
[2] 2504ae65 → c6e88be2  ──────────────────────── ► c6e88be2  count:5
[6] e285f9a5 → c62dbf06  ──────────────────────── ► c62dbf06  count:5
```

---

## 9. Chemins de code clés

| Responsabilité                                      | Fichier                               | Lignes  |
|-----------------------------------------------------|---------------------------------------|---------|
| Indexation `ID: N` dans le prompt                   | `rag/prompts/generator.py`            | 137–147 |
| Extraction `[ID:N]` dans la réponse                 | `api/db/services/dialog_service.py`   | 694–697 |
| Normalisation des mauvais formats                   | `api/db/services/dialog_service.py`   | 405–458 |
| Insertion automatique de citations                  | `rag/nlp/search.py`                   | 178–268 |
| Mappage N → doc_id, filtrage doc_aggs               | `api/db/services/dialog_service.py`   | 701–705 |
| Construction chunks + doc_aggs (pagination vs pool) | `rag/nlp/search.py`                   | 460–519 |
| Types TypeScript existants                          | `web/src/interfaces/database/chat.ts` | 109–151 |
