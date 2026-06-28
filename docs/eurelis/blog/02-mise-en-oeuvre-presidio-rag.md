---
title: "Presidio en pratique : implémenter le masquage PII dans un pipeline RAG"
type: blog
status: published
tags: ["IA", "Python", "Sécurité", "RAG"]
reading_time: "12 min"
---

# Presidio en pratique : implémenter le masquage PII dans un pipeline RAG

---

Dans le [premier article de cette série](./01-introduction-pii-masking-presidio.md), nous avons présenté la problématique du masquage PII dans les pipelines RAG et justifié le choix de Microsoft Presidio. Dans cet article, nous rentrons dans le code.

L'objectif : comprendre les briques fondamentales du masquage — détection, anonymisation, placeholders cohérents, réhydratation simple et streaming — avec des exemples extraits de notre démonstrateur technique, exécutable de manière autonome sans RAGFlow.

---

## Les deux composants Presidio à comprendre d'abord

Presidio adopte une architecture découplée en deux composants indépendants :

- **`AnalyzerEngine`** — détecte les entités PII dans le texte et retourne des `RecognizerResult` (type, position, score de confiance 0.0–1.0). Il ne modifie rien.
- **`AnonymizerEngine`** — reçoit le texte et les résultats d'analyse, applique des opérateurs de transformation configurables, et retourne le texte anonymisé.

Ce découplage est précieux en production : on peut interroger l'`AnalyzerEngine` seul pour auditer les détections sans toucher au texte.

---

## Étape 1 — Détection avec l'AnalyzerEngine

```python
from presidio_analyzer import AnalyzerEngine

analyzer = AnalyzerEngine()

texte = "Bonjour, je suis Alice Martin, mon email est alice@example.com et mon téléphone le +33 6 12 34 56 78."

resultats = analyzer.analyze(
    text=texte,
    language="en",
    entities=["EMAIL_ADDRESS", "PHONE_NUMBER", "PERSON"],
)

for r in sorted(resultats, key=lambda x: x.start):
    extrait = texte[r.start:r.end]
    print(f"[{r.entity_type:20s}] score={r.score:.2f}  valeur={extrait!r}")
```

**Sortie :**
```
[EMAIL_ADDRESS       ] score=1.00  valeur='alice@example.com'
[PHONE_NUMBER        ] score=0.75  valeur='+33 6 12 34 56 78'
```

> ⚠️ Sans modèle NER, l'entité `PERSON` (Alice Martin) n'est pas détectée. Les regex seules couvrent : `EMAIL_ADDRESS`, `PHONE_NUMBER`, `IP_ADDRESS`, `CREDIT_CARD`, `IBAN_CODE`. Pour les noms propres, il faut activer spaCy — voir Étape 5.

---

## Étape 2 — Anonymisation avec l'AnonymizerEngine

L'`AnonymizerEngine` propose plusieurs opérateurs, configurables par type d'entité :

| Opérateur | Effet | Réversible ? |
|-----------|-------|-------------|
| `replace` | Remplace par un label fixe `<EMAIL>` | ✅ Oui (si on garde le mapping) |
| `mask` | Masque partiellement avec `*` | ❌ Non |
| `hash` | SHA-256 irréversible | ❌ Non |
| `redact` | Suppression totale | ❌ Non |
| `custom` | Fonction lambda — pour les placeholders numérotés | ✅ Oui |

```python
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

anonymizer = AnonymizerEngine()

operateurs = {
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "<EMAIL>"}),
    "PHONE_NUMBER":  OperatorConfig("mask", {"masking_char": "*", "chars_to_mask": 10, "from_end": False}),
}

resultat = anonymizer.anonymize(
    text=texte,
    analyzer_results=resultats,
    operators=operateurs,
)

print(resultat.text)
# → "Bonjour, je suis Alice Martin, mon email est <EMAIL> et mon téléphone le **********4 56 78."
```

---

## Étape 3 — Placeholders numérotés et cohérents (le cœur de la réhydratation)

Le `replace` simple (`<EMAIL>`) ne suffit pas en production : si l'utilisateur mentionne deux adresses email différentes, on perd l'information de quelle valeur correspond à quel placeholder.

La solution : des **placeholders numérotés et cohérents** via un opérateur `custom` et un `PlaceholderMapper` :

```python
from collections import defaultdict
from typing import Dict

class PlaceholderMapper:
    """Garantit que la même valeur PII reçoit toujours le même placeholder."""

    def __init__(self):
        self._counters: Dict[str, int] = defaultdict(int)
        self._value_to_placeholder: Dict[str, str] = {}
        self.placeholder_to_value: Dict[str, str] = {}  # ← clé de la réhydratation

    def get_or_create(self, entity_type: str, value: str) -> str:
        if value in self._value_to_placeholder:
            return self._value_to_placeholder[value]  # même valeur = même placeholder
        self._counters[entity_type] += 1
        placeholder = f"<{entity_type}_{self._counters[entity_type]}>"
        self._value_to_placeholder[value] = placeholder
        self.placeholder_to_value[placeholder] = value
        return placeholder
```

En utilisant ce mapper comme opérateur `custom` :

```python
mapper = PlaceholderMapper()

def make_operator(entity_type: str):
    return OperatorConfig("custom", {
        "lambda": lambda x: mapper.get_or_create(entity_type, x)
    })

operateurs_custom = {
    "EMAIL_ADDRESS": make_operator("EMAIL_ADDRESS"),
    "PERSON":        make_operator("PERSON"),
}
```

**Résultat sur un texte avec occurrences multiples :**

```
Texte : "Alice a envoyé un email à alice@example.com. Bob a aussi écrit à alice@example.com."

Masqué : <PERSON_2> a envoyé un email à <EMAIL_ADDRESS_1>. <PERSON_1> a aussi écrit à <EMAIL_ADDRESS_1>.

Mapping :
  <EMAIL_ADDRESS_1> → 'alice@example.com'   ← une seule occurrence, même valeur
  <PERSON_1>        → 'Bob'
  <PERSON_2>        → 'Alice'
```

👉 `alice@example.com` apparaît deux fois dans le texte mais n'a qu'**un seul placeholder** — propriété essentielle pour que le LLM puisse raisonner de façon cohérente sur les entités.

---

## Étape 4 — Masquage multi-messages avec état partagé

Dans un pipeline RAG, le contexte LLM est une liste de messages (system + user + assistant). Le `PlaceholderMapper` doit être **instancié une fois et partagé** sur l'ensemble des messages — y compris le contexte documentaire injecté dans le prompt system.

```python
messages = [
    {"role": "system",    "content": "Customer John Smith (john@acme.com) filed complaint #4521 on March 3rd."},
    {"role": "user",      "content": "Can you summarize John Smith's complaint?"},
    {"role": "assistant", "content": "I can see John Smith filed a complaint."},
]

mapper = PlaceholderMapper()  # partagé sur tous les messages

def mask_message(content: str) -> str:
    results = analyzer.analyze(text=content, language="en", entities=["PERSON", "EMAIL_ADDRESS", "DATE_TIME"])
    anonymized = anonymizer.anonymize(text=content, analyzer_results=results, operators=operateurs_custom)
    return anonymized.text

masked_messages = [
    {**msg, "content": mask_message(msg["content"])}
    for msg in messages
]
```

**Résultat :**
```
[SYSTEM]    Customer <PERSON_1> (<EMAIL_ADDRESS_1>) filed complaint #4521 on <DATE_TIME_1>.
[USER]      Can you summarize <PERSON_1>'s complaint?   ← même PERSON_1 !
[ASSISTANT] I can see <PERSON_1> filed a complaint.     ← même PERSON_1 !
```

Le placeholder `<PERSON_1>` apparaît de façon cohérente dans les trois rôles de la conversation — ce qui permet au LLM de comprendre qu'il s'agit du même individu, sans jamais voir son nom réel.

---

## Étape 5 — Activer la NER spaCy pour détecter PERSON et LOCATION

Les regex ne détectent pas les noms propres libres. Il faut configurer un modèle NER :

```python
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

nlp_config = {
    "nlp_engine_name": "spacy",
    "models": [
        {"lang_code": "en", "model_name": "en_core_web_sm"},
        {"lang_code": "fr", "model_name": "fr_core_news_sm"},
    ]
}

provider = NlpEngineProvider(nlp_configuration=nlp_config)
nlp_engine = provider.create_engine()
analyzer_nlp = AnalyzerEngine(
    nlp_engine=nlp_engine,
    supported_languages=["en", "fr"],
)
```

**Comparaison sans / avec NER :**

```
Texte : "Contact Alice Dupont at alice.dupont@company.fr before the meeting in Bordeaux."

Sans NER :
  [EMAIL_ADDRESS] 'alice.dupont@company.fr'  score=1.00
  ← PERSON et LOCATION non détectés

Avec spaCy en_core_web_sm :
  [PERSON      ] 'Alice Dupont'              score=0.85
  [EMAIL_ADDRESS] 'alice.dupont@company.fr'  score=1.00
  [LOCATION    ] 'Bordeaux'                  score=0.85
```

Dans RAGFlow, cela se configure via les variables d'environnement :
```bash
PII_MASKING_NER=true
PII_MASKING_NER_MODEL_EN=en_core_web_sm
PII_MASKING_NER_MODEL_FR=fr_core_news_sm
```

---

## Étape 6 — Réhydratation simple

La réhydratation remplace les placeholders dans la réponse LLM par leurs valeurs originales. Un détail d'implémentation critique : **trier par longueur décroissante** pour éviter que `<PERSON_1>` soit remplacé avant `<PERSON_10>`.

```python
def unmask_text(text: str, mapping: Dict[str, str]) -> str:
    result = text
    # Tri par longueur décroissante : <PERSON_10> remplacé avant <PERSON_1>
    for placeholder in sorted(mapping.keys(), key=len, reverse=True):
        result = result.replace(placeholder, mapping[placeholder])
    return result

reponse_llm = "<PERSON_1> filed complaint on <DATE_TIME_1>. Reach her at <EMAIL_ADDRESS_1>."
reponse_finale = unmask_text(reponse_llm, mapper.placeholder_to_value)
# → "Alice Martin filed complaint on March 3rd. Reach her at alice.martin@acme.com."
```

---

## Étape 7 — Réhydratation en streaming (le cas épineux)

En mode streaming SSE, le LLM envoie des chunks de texte au fil de l'eau. Un placeholder peut être **coupé entre deux chunks** :

```
chunk 1 : "Bonjour <PERS"
chunk 2 : "ON_1>, votre "
chunk 3 : "email est <EMAIL_ADDRESS"
chunk 4 : "_1>."
```

Le `StreamingUnmasker` gère ce cas via un **buffer à fenêtre glissante** : il retient l'émission dès qu'un `<` potentiellement ouvert est détecté en fin de buffer, et libère le contenu sûr immédiatement.

```python
class StreamingUnmasker:
    def __init__(self, mapping: Dict[str, str], max_placeholder_len: int = 40):
        self.mapping = mapping
        self._max_ph_len = max_placeholder_len
        self._buffer = ""

    def process_chunk(self, chunk: str) -> str:
        self._buffer += chunk
        safe_end = len(self._buffer)

        # Cherche un < potentiellement ouvert en fin de buffer
        last_open = self._buffer.rfind("<")
        if last_open != -1:
            suffix = self._buffer[last_open:]
            # Si ce < n'a pas encore de > fermant, retenir la fin
            if ">" not in suffix and len(suffix) <= self._max_ph_len:
                safe_end = last_open

        safe_part = self._buffer[:safe_end]
        self._buffer = self._buffer[safe_end:]
        return unmask_text(safe_part, self.mapping) if safe_part else ""

    def flush(self) -> str:
        """Appelé en fin de stream pour vider le buffer résiduel."""
        remaining = self._buffer
        self._buffer = ""
        return unmask_text(remaining, self.mapping)
```

**Simulation :**
```
chunk 1: reçu='Bonjour <PERS'          → émis='Bonjour '              (buffer en attente)
chunk 2: reçu='ON_1>, votre '          → émis='Alice Martin, votre '  (réhydraté ✅)
chunk 3: reçu='email est <EMAIL_ADDR'  → émis='email est '            (buffer en attente)
chunk 4: reçu='ESS_1>.'               → émis='alice@example.com.'    (réhydraté ✅)
```

---

## Étape 8 — Configuration avancée : MASK / BLOCK et seuils par entité

Dans RAGFlow, le comportement du masquage est configurable par variables d'environnement :

```bash
PII_MASKING_ENTITIES=PERSON:MASK,EMAIL_ADDRESS:MASK,CREDIT_CARD:BLOCK
PII_MASKING_SCORE_THRESHOLD=0.7
PII_MASKING_SCORE_OVERRIDES=PERSON:0.85,CREDIT_CARD:0.5
```

L'action `BLOCK` lève une exception avant l'envoi au LLM si l'entité est détectée — c'est le mode "refus de traitement" pour les données hautement sensibles (cartes bancaires, numéros de sécurité sociale) :

```python
# Test BLOCK — message contenant un numéro de carte
# "Paiement par carte 4111 1111 1111 1111."
# → ✅ PiiBlockedException : CREDIT_CARD detected — requête refusée

# Test MASK — message standard
# "Je suis Bob Smith, mon email est bob@test.com."
# → "<PERSON_1>, mon email est <EMAIL_ADDRESS_1>."
```

---

## Étape 9 — Recognizers métier pour les identifiants propriétaires

Presidio permet d'enregistrer des recognizers custom pour les patterns non couverts nativement :

```python
from presidio_analyzer import Pattern, PatternRecognizer

customer_id_recognizer = PatternRecognizer(
    supported_entity="CUSTOMER_ID",
    patterns=[Pattern(name="customer_id", regex=r"\bCLI-[0-9]{8}\b", score=0.9)],
    context=["client", "customer", "account", "compte"],  # boost si le contexte correspond
)

employee_id_recognizer = PatternRecognizer(
    supported_entity="EMPLOYEE_ID",
    patterns=[Pattern(name="employee_id", regex=r"\bEMP-[0-9]{5}\b", score=0.95)],
)

analyzer.registry.add_recognizer(customer_id_recognizer)
analyzer.registry.add_recognizer(employee_id_recognizer)
```

**Résultat :**
```
"Le compte client CLI-12345678 est géré par l'employé EMP-98765."

→ [CUSTOMER_ID ] 'CLI-12345678'  score=1.00   (boosté par le contexte "client")
→ [EMPLOYEE_ID ] 'EMP-98765'     score=0.95
```

Les mots contextuels (`client`, `customer`) font passer le score de 0.9 à 1.0 — permettant des seuils de confiance plus conservateurs sans perdre les détections légitimes.

---

## Le scénario complet bout-en-bout

Voici ce que traverse une conversation RAG complète dans notre implémentation :

```
1. CONVERSATION ORIGINALE (côté client)
   [SYSTEM] Dossier employé : Marie Curie, marie.curie@eurelis.com, +33 7 89 01 23 45
   [USER]   Quelle est l'adresse email de Marie Curie ?

2. CONVERSATION MASQUÉE (envoyée au LLM)
   [SYSTEM] Dossier employé : <PERSON_1>, <EMAIL_ADDRESS_1>, <PHONE_NUMBER_1>
   [USER]   Quelle est l'adresse email de <PERSON_2> ?

3. MAPPING PII — stocké localement, jamais transmis
   <PERSON_1>        → 'Marie Curie'
   <EMAIL_ADDRESS_1> → 'marie.curie@eurelis.com'
   <PHONE_NUMBER_1>  → '+33 7 89 01 23 45'
   <PERSON_2>        → 'Marie Curie'   ← même valeur détectée à deux endroits

4. RÉPONSE LLM BRUTE
   "L'email de <PERSON_1> est <EMAIL_ADDRESS_1>."

5. RÉPONSE RÉHYDRATÉE (affichée à l'utilisateur)
   "L'email de Marie Curie est marie.curie@eurelis.com."
```

---

## Récapitulatif des composants et leur rôle dans RAGFlow

| Composant | Rôle | Variable RAGFlow |
|-----------|------|-----------------|
| `AnalyzerEngine` | Détecte les entités (regex + NER) | `PII_MASKING_ENTITIES` |
| `AnonymizerEngine` + opérateur custom | Génère les placeholders numérotés | — |
| `PlaceholderMapper` | Cohérence inter-messages | — |
| `ConfigurableMasker` | Seuils par entité + MASK/BLOCK | `PII_MASKING_SCORE_THRESHOLD` |
| `unmask_text()` | Réhydratation simple | — |
| `StreamingUnmasker` | Réhydratation streaming SSE | `PII_MASKING_*` |
| `PatternRecognizer` custom | Entités métier propriétaires | `PII_MASKING_CUSTOM_RECOGNIZERS_FILE` |
| `NlpEngineProvider` (spaCy) | NER — PERSON, LOCATION, ORG | `PII_MASKING_NER_MODEL_EN/FR` |

---

## Pour aller plus loin

Le notebook complet est disponible dans le fork Eurelis de RAGFlow : `docs/eurelis/notebooks/presidio_demo.ipynb`. Il peut être exécuté de manière autonome avec uniquement `presidio-analyzer`, `presidio-anonymizer` et `spacy`.

Dans le troisième article de cette série, nous mesurons l'impact du choix du modèle NER spaCy sur la qualité de détection, la latence et l'empreinte mémoire — avec des résultats qui réservent quelques surprises.

**→ [Benchmark NER spaCy — sm bat md, vraiment ?](./03-benchmark-ner-spacy-presidio.md)**

---

*Code source : `rag/llm/pii_masking.py` — fork Eurelis RAGFlow, branche `eurelis/main`.*
