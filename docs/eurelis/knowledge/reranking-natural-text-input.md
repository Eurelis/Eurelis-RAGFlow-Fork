---
title: "Reranking sur le texte naturel des chunks (choix Eurelis)"
type: knowledge
status: reference
date: 2026-07-15
---

# Reranking sur le texte naturel des chunks (choix Eurelis)

Le fork Eurelis transmet aux rerankers le **texte naturel** des chunks — mise en
forme conservée, tableaux HTML compris — et non la version tokenisée utilisée par
l'upstream. Ce document explique le constat, la mesure, la modification et ses
corollaires.

> **En bref.** Nourrir un reranker neuronal avec du texte tokenisé (`content_ltks`)
> effondre ses scores (facteur ~10 à ~90 mesuré sur du contenu FR), le rend
> quasi inopérant et force un `similarity_threshold` artificiellement bas. Passer
> le texte naturel (`content_with_weight`) restaure des scores exploitables et un
> seuil normal (~0,2).

---

## 1. Le comportement upstream

Dans `rag/nlp/search.py`, `Dealer.rerank_by_model` construit les documents envoyés
au reranker à partir de `content_ltks` — le contenu **tokenisé** par
`rag_tokenizer` (minusculisé, stemmé, accents éclatés, ponctuation supprimée).

Exemple, la phrase :

```
Pour se protéger d'une attaque par déni de service distribué (DDoS)...
```

devient, en `content_ltks` :

```
pour se prot é ger d une attaqu par d é ni de servic distribu é ddos ...
```

« protéger » → `prot é ger` (3 tokens), « déni » → `d é ni`, « attaque » → `attaqu`.
Un reranker neuronal, entraîné sur du langage naturel, score très mal ce charabia.

---

## 2. La mesure

Sur de vrais chunks d'une base francophone, même chunk pertinent, deux entrées :

| Requête | `content_with_weight` (naturel) | `content_ltks` (upstream) | Facteur |
|---|---|---|---|
| « fréquence des sauvegardes / rétention » | 0,548 | 0,021 | ~26× |
| « assureur cyber / délai de notification » | 0,314 | 0,033 | ~10× |
| « RTO / RPO des systèmes » | 0,847 | 0,009 | ~94× |

Avec `content_ltks`, **aucun** chunk ne dépasse 0,2 (le reranker note tout ~0) : la
remontée était en réalité portée par la similarité mots-clés du blend, pas par le
reranker. Avec le texte naturel, le reranker classe correctement et un seuil de
0,2 fonctionne.

---

## 3. La modification

`rag/nlp/search.py` — `Dealer.rerank_by_model` construit désormais une liste
`rerank_docs` à partir de `content_with_weight` (repli sur la forme tokenisée si
le champ est absent) :

```python
natural = sres.field[i].get("content_with_weight") or " ".join(tks)
rerank_docs.append(remove_redundant_spaces(natural))
...
vtsim, _ = rerank_mdl.similarity(query, rerank_docs)
```

- `ins_tw` / `token_similarity` (le signal mots-clés `tksim` du blend) restent
  **inchangés** — seule l'entrée du reranker change.
- La **troncature** à la fenêtre du modèle reste la responsabilité du connecteur
  (comme Jina, Voyage, Cohere natif qui tronquent déjà chez eux), et non de
  `search.py`. Voir le connecteur `BedrockRerank` dans `rag/llm/rerank_model.py`
  (`doc_max_tokens` : Cohere Rerank v3.5 ~2k de sa fenêtre 4k partagée, Amazon
  Rerank v1 8k).

---

## 4. Corollaire : ne pas nettoyer le balisage HTML

On pourrait penser qu'il faut stripper le HTML des tableaux avant le rerank. **C'est
faux.** Test sur la même base (chunk annuaire de contacts, tableau HTML) :

| Entrée reranker (Cohere Rerank 3.5) | Score | Rang |
|---|---|---|
| Texte naturel **avec HTML** | 0,131 | 2 |
| Texte **strippé** (HTML retiré) | 0,069 | 10 |

Cohere Rerank 3.5 **exploite la structure du tableau** — les en-têtes
`<th>Contact activation</th>`, `<th>Prestataire</th>` sont un signal sémantique.
Les aplatir dégrade le classement. On transmet donc le `content_with_weight` **brut**.

---

## 5. Impact et divergence upstream

- **Fichier upstream modifié** : `rag/nlp/search.py` (diff minimal, un bloc dans
  `rerank_by_model`). Divergence à surveiller lors des rebases upstream.
- **Universel** : le changement bénéficie à **tous** les rerankers externes
  (Cohere, Jina, Voyage, NVIDIA, Bedrock…), pas seulement Bedrock.
- **Effet de bord positif** : permet de remonter `similarity_threshold` à une
  valeur normale et rend le poids `vector_similarity_weight` de nouveau
  interprétable.

---

## Voir aussi

- Connecteur reranker Bedrock : `rag/llm/rerank_model.py` (`BedrockRerank`).
- Guide pratique de mise en œuvre du reranking (choix du modèle, réglage des
  paramètres) : espace Confluence AILAB → dossier *User Guide*.
- [Configuration des modèles LLM par tenant](./llm-default-configuration.md).
