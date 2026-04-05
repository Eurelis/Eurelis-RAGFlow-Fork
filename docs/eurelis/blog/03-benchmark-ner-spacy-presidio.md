# Benchmark NER spaCy × Presidio : sm bat md, et ce n'est pas un bug

**Catégories :** IA, Python, Benchmark, NLP  
**Temps de lecture :** 10 min

---

Quand on intègre Microsoft Presidio dans un pipeline RAG, une question s'impose rapidement : quel modèle NER spaCy choisir ? Plus le modèle est grand, meilleur il est — c'est l'intuition naturelle. Les résultats de notre benchmark la contredisent partiellement, et les chiffres méritent qu'on s'y arrête.

Nous avons mesuré la qualité de détection PII (précision, rappel, F1), la latence (p50/p95) et l'empreinte mémoire pour les modèles anglais et français disponibles dans l'écosystème spaCy, sur un dataset annoté représentatif de contextes RAG en entreprise.

---

## Les modèles testés

spaCy propose quatre familles de modèles anglais et trois familles françaises, qui diffèrent par leur architecture et la richesse de leurs vecteurs de mots :

| Modèle | Architecture | Taille | Vecteurs |
|--------|-------------|--------|---------|
| `en_core_web_sm` | tok2vec (CNN) | ~15 MB | Non |
| `en_core_web_md` | tok2vec (CNN) | ~54 MB | 20 000 mots |
| `en_core_web_lg` | tok2vec (CNN) | ~560 MB | 685 000 mots |
| `en_core_web_trf` | RoBERTa (transformer) | ~440 MB | Contextuels |
| `fr_core_news_sm` | tok2vec (CNN) | ~25 MB | Non |
| `fr_core_news_md` | tok2vec (CNN) | ~46 MB | Inclus |
| `fr_core_news_lg` | tok2vec (CNN) | ~570 MB | 500 000 mots |

Les modèles `lg` et `trf` sont optionnels dans le benchmark — ils nécessitent plusieurs centaines de Mo d'espace disque. Le notebook peut être exécuté en mode léger avec uniquement `sm` et `md`.

---

## Méthodologie : mesurer ce qui compte vraiment en production

Les benchmarks NLP académiques mesurent souvent la performance sur des corpus de presse ou de Wikipedia. Notre dataset est différent : il simule les textes qu'un système RAG d'entreprise rencontre réellement.

### Dataset annoté

Nous avons construit 16 textes annotés manuellement (10 EN + 6 FR) avec leurs entités ground truth :

| Langue | Textes | Entités attendues | Difficulté |
|--------|--------|-------------------|-----------|
| Anglais | 10 | 36 | 3 easy / 4 normal / 3 hard |
| Français | 6 | 25 | 1 easy / 3 normal / 2 hard |

Trois entités sont évaluées : `PERSON`, `LOCATION`, `DATE_TIME`.

Les niveaux de difficulté reflètent les cas réels :

- **easy** — `"My name is John Smith and I live in London."` — entités isolées, contexte limpide
- **normal** — extraits de meeting notes, employee records multi-entités
- **hard** — ambiguïtés (`"Paris called to confirm the Lyon meeting on Tuesday."` — Paris est-il une ville ou un prénom ?), noms non-occidentaux (`"Hiroshi Nakamura"`, `"Abderrahim Benali"`), dates relatives (`"Q3 2023"`, `"last Monday"`)

### Protocole de mesure

Pour chaque modèle :
1. Construction de l'`AnalyzerEngine` Presidio via `NlpEngineProvider`
2. **3 passages de warmup** — élimine les effets JIT et cache OS
3. **20 répétitions** de mesure avec `time.perf_counter()`
4. Qualité calculée sur la première répétition (TP/FP/FN par entité, matching souple)
5. Mémoire : taille disque via `pathlib` + pic RAM au chargement via `tracemalloc`

Le **matching souple** tolère les spans partiels : si le modèle détecte `"John"` alors que le ground truth est `"John Smith"`, c'est comptabilisé comme un vrai positif. C'est la réalité du NER en production.

---

## Résultats anglais : la surprise du `sm`

![Qualité NER — Modèles anglais : précision, rappel et F1 par entité](../../../docs/eurelis/notebooks/../../../tmp/presidio_benchmark_imgs/cell14_out01.png)

| Modèle | F1 global | Précision | Rappel | p50 (ms) | Débit (t/s) | Taille |
|--------|-----------|-----------|--------|----------|-------------|--------|
| `en_core_web_sm` | **0.96** 🏆 | **0.97** | **0.94** | **3.3 ms** ⚡ | **300 t/s** ⚡ | 15 MB |
| `en_core_web_md` | 0.93 | 0.94 | 0.92 | 3.6 ms | 280 t/s | 54 MB |

**`en_core_web_sm` domine `en_core_web_md` sur tous les axes** : meilleur F1 (+3 points), meilleure précision, meilleur rappel, latence plus faible, et 3,5× moins lourd sur le disque.

Ce résultat contre-intuitif s'explique par la nature des entités testées. Les vecteurs de mots du modèle `md` améliorent la désambiguïsation sémantique — utile pour la tâche de classification de texte ou d'analyse de sentiments. Pour la reconnaissance d'entités nommées `PERSON`, `LOCATION` et `DATE_TIME`, le modèle CNN tok2vec du `sm` est déjà très efficace, et les 20 000 vecteurs additionnels du `md` introduisent légèrement plus de faux positifs sur ce type de dataset.

### F1 par niveau de difficulté

![F1 par difficulté — Modèles anglais](../../../docs/eurelis/notebooks/../../../tmp/presidio_benchmark_imgs/cell15_out00.png)

Les deux modèles maintiennent un excellent F1 sur les cas faciles et normaux. La dégradation sur les cas *hard* est comparable — ni `sm` ni `md` ne résout mieux les ambiguïtés de type `"Paris"` (ville ou prénom ?). Ce type d'ambiguïté contextuelle profonde requiert un modèle transformer (`trf`) ou des règles métier spécifiques.

---

## Résultats français : le rappel en question

![Qualité NER — Modèles français](../../../docs/eurelis/notebooks/../../../tmp/presidio_benchmark_imgs/cell14_out03.png)

| Modèle | F1 global | Précision | Rappel | p50 (ms) | Débit (t/s) | Taille |
|--------|-----------|-----------|--------|----------|-------------|--------|
| `fr_core_news_sm` | 0.76 | 0.85 | **0.68** | 3.3 ms | 303 t/s | 25 MB |

La précision est correcte (0.85) — ce que le modèle français détecte, c'est généralement juste. Mais le rappel de 0.68 signifie que **32% des entités attendues ne sont pas trouvées**.

Les entités manquées sont principalement :
- Des `DATE_TIME` en format non standard (`"T3 2023"`, `"21 février"`)
- Des noms de personnes peu représentés dans les corpus d'entraînement francophones (`"Abderrahim Benali"`, `"Hoa Nguyen"`)

![F1 par difficulté — Modèles français](../../../docs/eurelis/notebooks/../../../tmp/presidio_benchmark_imgs/cell15_out01.png)

La dégradation sur les cas *hard* est marquée pour le français — ce qui confirme que `fr_core_news_sm` est sous-dimensionné pour les contextes multilingues ou les noms propres non-français. Le passage au modèle `lg` devrait significativement améliorer ces cas.

---

## Latence et débit : les CNN tiennent la distance

![Latence et débit — Modèles anglais](../../../docs/eurelis/notebooks/../../../tmp/presidio_benchmark_imgs/cell17_out00.png)

Les mesures de latence révèlent à quel point les modèles CNN tok2vec de spaCy sont efficaces sur CPU :

- **p50 : 3.3 ms** pour les deux modèles anglais (sm et md)
- **p95 : 6.3–6.6 ms** — la distribution est stable, pas d'outliers significatifs
- **Débit : 280–300 textes/seconde** sur une machine de développement ARM, sans GPU

Pour comparaison, un modèle transformer (CamemBERT, RoBERTa) atteint typiquement 80–200 ms/texte, soit **25–60× plus lent**. En contexte de streaming RAG avec plusieurs dizaines de requêtes simultanées, cette différence est déterminante.

![Latence et débit — Modèles français](../../../docs/eurelis/notebooks/../../../tmp/presidio_benchmark_imgs/cell17_out02.png)

Le modèle français présente une distribution encore plus resserrée (p95 = 5.2 ms), probablement lié aux textes plus courts du dataset FR.

---

## Empreinte mémoire : ce qui compte à l'échelle

![Empreinte mémoire — tous modèles](../../../docs/eurelis/notebooks/../../../tmp/presidio_benchmark_imgs/cell19_out00.png)

Les modèles `sm` (15–25 MB) et `md` (46–54 MB) restent dans des enveloppes mémoire très raisonnables. À titre de comparaison, `en_core_web_lg` occupe 560 MB et `en_core_web_trf` environ 440 MB — sans compter la VRAM GPU pour le modèle transformer.

Pour un déploiement multi-langues (EN + FR) avec chargement en mémoire persistante :

| Combinaison | Empreinte disque | Empreinte RAM estimée |
|-------------|-----------------|----------------------|
| sm + sm | ~40 MB | ~150–200 MB |
| md + md | ~100 MB | ~300–400 MB |
| lg + lg | ~1.1 GB | ~1.5–2 GB |
| trf + lg | ~1.0 GB | ~1.2–2 GB + VRAM |

---

## Radar chart : le profil multi-critères

![Radar chart — Profil multi-critères EN : sm vs md](../../../docs/eurelis/notebooks/../../../tmp/presidio_benchmark_imgs/cell21_out00.png)

Le radar chart (quatre axes normalisés : F1 global, F1 difficile, vitesse, légèreté) confirme visuellement que `en_core_web_sm` présente un profil dominant sur tous les axes. C'est un cas rare où le modèle le plus léger est aussi le plus performant — et ce n'est pas une coïncidence : la tâche NER pour PERSON/LOCATION/DATE_TIME est bien adaptée à l'architecture CNN tok2vec.

---

## Recommandations : choisir son modèle selon son contexte

### Pour la production

```bash
# Qualité prioritaire — 8+ GB RAM disponible
PII_MASKING_NER_MODEL_EN=en_core_web_lg
PII_MASKING_NER_MODEL_FR=fr_core_news_lg
```

Les modèles `lg`, avec 685 000 vecteurs de mots pour l'anglais et 500 000 pour le français, offrent le meilleur rappel sur les noms propres peu courants et les cas ambigus — exactement les scénarios difficiles que `sm` et `md` ne gèrent pas bien.

### Pour le développement et les environnements contraints

```bash
# Valeur par défaut — excellent rapport qualité/poids
PII_MASKING_NER_MODEL_EN=en_core_web_sm   # 15 MB, F1=0.96
PII_MASKING_NER_MODEL_FR=fr_core_news_sm  # 25 MB
```

F1=0.96 en anglais pour 15 MB, c'est un rapport qualité/poids exceptionnel. Pour les contextes CI/CD, les environnements RAM-limités ou les workloads à fort débit (300+ textes/seconde sur CPU), c'est le choix optimal.

### Pour la qualité maximale (EN, GPU disponible)

```bash
PII_MASKING_NER_MODEL_EN=en_core_web_trf  # RoBERTa ~440 MB + GPU
```

Nécessite `pip install spacy[transformers]`. À réserver aux contextes où la précision sur les entités ambigues est critique et où un GPU est disponible.

### Guide de décision rapide

| Contexte | Modèle EN | Modèle FR |
|----------|-----------|-----------|
| RAM < 2 GB / CI / développement | `en_core_web_sm` | `fr_core_news_sm` |
| Production standard (4–8 GB) | `en_core_web_sm` ou `md` | `fr_core_news_md` |
| Production haute qualité (8+ GB) | `en_core_web_lg` | `fr_core_news_lg` |
| GPU disponible + qualité max (EN) | `en_core_web_trf` | `fr_core_news_lg` |

> ⚠️ Sans NER (`PII_MASKING_NER=false`), seules les entités détectables par regex sont couvertes : `EMAIL`, `PHONE_NUMBER`, `CREDIT_CARD`, `IBAN_CODE`, `IP_ADDRESS`. `PERSON` et `LOCATION` ne sont **pas** détectées.

---

## Ce que ce benchmark ne mesure pas

Notre dataset de 16 textes est représentatif mais limité. Quelques nuances importantes :

**Noms propres rares.** Les résultats sur les cas *hard* (noms non-occidentaux, ambiguïtés géographiques) seraient probablement différents avec un dataset de 1 000 textes. Notre dataset indique une tendance, pas une vérité absolue.

**Le modèle `trf` en anglais.** Nous n'avons pas pu mesurer `en_core_web_trf` dans cet environnement (pas de GPU). La littérature indique un gain de F1 de 5–10 points sur les cas ambigus, au prix d'une latence 25–60× supérieure.

**Les langues sans modèle `trf`.** Le français ne dispose pas d'équivalent transformer dans l'écosystème spaCy public. Pour des exigences de qualité maximale en français, CamemBERT via Hugging Face reste l'option — à implémenter via un recognizer custom Presidio.

---

## Reproducibilité

Le notebook complet est disponible dans `docs/eurelis/notebooks/presidio_ner_benchmark.ipynb`. Pour reproduire ces mesures :

```bash
pip install presidio-analyzer presidio-anonymizer spacy pandas matplotlib numpy
python -m spacy download en_core_web_sm
python -m spacy download en_core_web_md
python -m spacy download fr_core_news_sm
jupyter notebook docs/eurelis/notebooks/presidio_ner_benchmark.ipynb
```

Les modèles `lg` et `trf` sont commentés par défaut pour limiter les téléchargements — décommentez `EN_MODELS` et `FR_MODELS` dans la cellule de configuration pour les inclure.

---

*Cet article est le troisième d'une série sur le masquage PII dans RAGFlow. Retrouvez [l'introduction à la problématique](./01-introduction-pii-masking-presidio.md) et [les principes de mise en œuvre](./02-mise-en-oeuvre-presidio-rag.md).*

*Benchmark exécuté sur macOS ARM (Apple M-series), CPU uniquement, Python 3.11, spaCy 3.8.14, Presidio Analyzer 2.x.*
