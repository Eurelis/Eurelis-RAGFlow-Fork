---
title: "Feature : PII Masking (Presidio)"
type: feature
status: implemented
date: 2026-05-31
branch: "eurelis/feature/pii-masking"
reviewed: 2026-06-28
---

# Feature : PII Masking (Presidio)

---

## Objectif

Détecter et masquer automatiquement les données personnelles (PII — Personally Identifiable Information) présentes dans les messages utilisateur **avant** qu'ils ne soient transmis au LLM, afin de satisfaire aux exigences RGPD et de minimisation des données.

Les LLM providers (OpenAI, Anthropic, AWS Bedrock, etc.) ne doivent jamais recevoir en clair des données telles que noms, emails, numéros de téléphone, numéros de carte bancaire, etc.

---

## Périmètre

| Bloc | Description | Phase |
|------|-------------|-------|
| Module `pii_masking.py` | Détection + masquage via Presidio Python | MVP |
| Intégration `chat_model.py` | Hook dans `LiteLLMBase._construct_completion_args()` | MVP |
| Masquage input + réhydratation réponse | Remplacement des placeholders dans la réponse LLM avant retour client | MVP |
| Configuration par variable d'env | Toggle `PII_MASKING_ENABLED`, langues, entités | MVP |
| Audit log configurable | Journalisation des PII détectés (sans valeur originale), niveau et destination configurables | MVP |
| Coexistence direct/masqué — Option A (suffixe `::pii`) | Même modèle disponible en direct et masqué via convention de nommage | MVP |
| Streaming unmask — sliding window | Démasquage des réponses en flux (non-streaming + streaming) | MVP |
| Coexistence direct/masqué — Option B (flag `Dialog.pii_masking`) | Activation du masquage par conversation, sans doublon de modèle | v1 |
| Toggle par tenant | Activer/désactiver le masquage par tenant | v1 |
| Support multilingue FR | Modèle spaCy `fr_core_news_lg` | v1 |

---

## Architecture technique

### Approche retenue : Presidio en bibliothèque Python (Option B)

RAGFlow utilise déjà LiteLLM **comme bibliothèque Python** (`litellm.acompletion()`), pas comme proxy HTTP. On intègre donc Presidio directement dans le processus Python, sans service externe supplémentaire.

```
[Message utilisateur]
        │
        ▼
┌───────────────────────┐
│   dialog_service.py   │  ← orchestration
└──────────┬────────────┘
           │ history (messages)
           ▼
┌───────────────────────┐
│    llm_service.py     │  ← LLMBundle
│    LiteLLMBase        │
│  _construct_          │
│  completion_args()    │
│          │            │
│  mask_pii_in_messages()  ← POINT D'INJECTION
│          │            │
└──────────┬────────────┘
           │ messages masqués
           ▼
┌───────────────────────┐
│  litellm.acompletion  │
└──────────┬────────────┘
           │
           ▼
     [LLM Provider]
     (ne voit jamais les PII)
```

### Fichiers créés / modifiés

```
rag/llm/
├── pii_masking.py                      ← NOUVEAU : moteur Presidio + StreamingUnmasker + PiiAuditLogger
rag/llm/chat_model.py                   ← MODIFIÉ : hook dans LiteLLMBase (+ strip suffixe ::pii)
api/ragflow_server.py                   ← MODIFIÉ : init PiiMaskingEngine au démarrage
conf/pii_custom_recognizers.yaml        ← NOUVEAU : recognizers personnalisés (optionnel)
pyproject.toml                          ← MODIFIÉ : dépendances Presidio
docker/.env                             ← MODIFIÉ : variables de configuration

# Option B (v1) uniquement :
api/db/db_models.py                     ← MODIFIÉ : champ pii_masking sur Dialog
api/apps/dialog_app.py                  ← MODIFIÉ : exposition du champ via API
web/src/                                ← MODIFIÉ : UI toggle dans les settings du dialog
```

---

## Flux de données détaillé

### Masquage input + réhydratation réponse

```
Input :  "Mon email est john@example.com, je m'appelle Jean Dupont"
                │
                ▼  AnalyzerEngine.analyze()
         [EMAIL_ADDRESS @ 14-30], [PERSON @ 46-57]
                │
                ▼  AnonymizerEngine.anonymize()
                    mapping : {"<EMAIL_ADDRESS_1>": "john@example.com",
                               "<PERSON_1>": "Jean Dupont"}
Masqué : "Mon email est <EMAIL_ADDRESS_1>, je m'appelle <PERSON_1>"
                │
                ▼  → LLM (ne voit que les placeholders)

Réponse LLM : "J'ai bien noté votre email <EMAIL_ADDRESS_1>."
                │
                ▼  unmask_text() / StreamingUnmasker
                    lookup mapping
Output : "J'ai bien noté votre email john@example.com."
                │
                ▼  → Client (valeur originale restaurée)
```

### Unmasking en mode streaming

```
Input masqué → LLM
                │
                ▼  Stream de chunks
        "J'ai bien " → flush immédiat → client
        "noté votre email " → flush immédiat → client
        "<" → début de placeholder potentiel → buffering
        "EMAIL" → buffering
        "_ADDRESS_1>" → placeholder complet détecté
                │
                ▼  lookup dans mapping
        "john@example.com" → flush → client
        "." → flush immédiat → client
```

---

## Initialisation au démarrage

### Séquence de démarrage RAGFlow

Le chargement des modèles Presidio/spaCy s'insère dans `api/ragflow_server.py`, après l'init des plugins et avant le démarrage HTTP :

```python
# api/ragflow_server.py (main block)

settings.init_settings()
init_web_db()
init_web_data()
RuntimeConfig.init_env()
RuntimeConfig.init_config(...)
GlobalPluginManager.load_plugins()

# ← INSERTION ICI
from rag.llm.pii_masking import PiiMaskingEngine
PiiMaskingEngine.initialize()               # no-op si PII_MASKING_ENABLED=false et PII_AUDIT_LOG_ENABLED=false
# ← FIN INSERTION

logging.info(f"RAGFlow server is ready after {time.time() - start_ts}s initialization.")
app.run(...)
```

### Classe `PiiMaskingEngine` — singleton de démarrage

```python
class PiiMaskingEngine:
    """
    Singleton thread-safe. Charge les modèles spaCy et initialise
    les engines Presidio une seule fois au démarrage du serveur.
    Toutes les opérations de masquage passent par cette instance.
    """
    _instance: "PiiMaskingEngine | None" = None
    _lock = threading.Lock()

    def __init__(self, analyzer: AnalyzerEngine, anonymizer: AnonymizerEngine):
        self.analyzer = analyzer
        self.anonymizer = anonymizer

    @classmethod
    def initialize(cls) -> None:
        """
        Appelé une seule fois au démarrage. Charge les modèles pour
        toutes les langues définies dans PII_MASKING_LANGUAGES.
        - Si PII_MASKING_ENABLED=false ET PII_AUDIT_LOG_ENABLED=false → no-op immédiat.
        - En cas d'erreur de chargement :
            - PII_MASKING_STARTUP_FAIL=true → lève une exception, serveur ne démarre pas.
            - PII_MASKING_STARTUP_FAIL=false (défaut) → log error, désactive silencieusement le masquage.
        """
        ...

    @classmethod
    def get(cls) -> "PiiMaskingEngine":
        """
        Retourne le singleton initialisé.
        Lève RuntimeError si initialize() n'a pas été appelé.
        """
        if cls._instance is None:
            raise RuntimeError(
                "PiiMaskingEngine not initialized. "
                "Call PiiMaskingEngine.initialize() at server startup."
            )
        return cls._instance

    @classmethod
    def is_available(cls) -> bool:
        """True si le moteur est chargé et opérationnel."""
        return cls._instance is not None
```

### Comportement selon la configuration

```
PII_MASKING_ENABLED=false ET PII_AUDIT_LOG_ENABLED=false
    → initialize() retourne immédiatement (no-op)
    → Aucun import spaCy/Presidio, zéro overhead démarrage

PII_MASKING_ENABLED=true OU PII_AUDIT_LOG_ENABLED=true
  ET PII_MASKING_NER=false (défaut)
    → Presidio initialisé avec recognizers regex/checksum uniquement
    → Aucun modèle spaCy chargé
    → Log : "PiiMaskingEngine initialized (NER disabled — regex/checksum only)"

PII_MASKING_ENABLED=true OU PII_AUDIT_LOG_ENABLED=true
  ET PII_MASKING_NER=true
    → Chargement du modèle spaCy pour chaque langue dans PII_MASKING_LANGUAGES
      - "en" → PII_MASKING_NER_MODEL_EN  (défaut : en_core_web_lg)
      - "fr" → PII_MASKING_NER_MODEL_FR  (défaut : fr_core_news_lg)
    → Composants inutiles exclus au chargement : tagger, parser, lemmatizer
    → Log : "Loading spaCy model en_core_web_lg (excluding: tagger, parser, lemmatizer)…"
    → Log : "PiiMaskingEngine initialized in 3.2s (NER enabled, languages: en)"

Erreur de chargement spaCy (modèle absent, OOM, …)
    PII_MASKING_STARTUP_FAIL=true         → RuntimeError → serveur ne démarre pas
    PII_MASKING_STARTUP_FAIL=false (défaut) → logging.error + _instance reste None
                                              → is_available() = False
                                              → masquage silencieusement désactivé
```

### Logs de démarrage attendus

NER activé (`PII_MASKING_NER=true`) :
```
INFO  ragflow_server  PII masking enabled (languages: en, entities: PERSON,EMAIL_ADDRESS,PHONE_NUMBER,CREDIT_CARD,IBAN_CODE,IP_ADDRESS)
INFO  ragflow_server  NER enabled — loading spaCy model en_core_web_lg (excluding: tagger, parser, lemmatizer)…
INFO  ragflow_server  PiiMaskingEngine initialized in 3.4s (NER: en_core_web_lg, custom recognizers: 2)
```

NER désactivé (`PII_MASKING_NER=false`) :
```
INFO  ragflow_server  PII masking enabled (languages: en, entities: EMAIL_ADDRESS,PHONE_NUMBER,CREDIT_CARD,IBAN_CODE,IP_ADDRESS)
INFO  ragflow_server  NER disabled — spaCy not loaded (PERSON, LOCATION, DATE_TIME detection unavailable)
INFO  ragflow_server  PiiMaskingEngine initialized in 0.1s (regex/checksum only, custom recognizers: 0)
```

PII masking désactivé :
```
INFO  ragflow_server  PII masking disabled — PiiMaskingEngine skipped
```

### Intégration dans le hook `_construct_completion_args`

Le hook est implémenté via `apply_pii_masking()` qui retourne un 3-tuple :

```python
# rag/llm/chat_model.py — LiteLLMBase._construct_completion_args()

pii_mapping: dict = {}
try:
    from rag.llm.pii_masking import PiiBlockedException, apply_pii_masking
    history, effective_model_name, pii_mapping = apply_pii_masking(
        history=history,
        model_name=self.model_name,
        prefix=self.prefix,
        provider=str(self.provider),
    )
except PiiBlockedException:
    raise
except Exception as _pii_exc:
    logging.warning(f"PII masking error (continuing without masking): {_pii_exc}")

# ...
return completion_args, pii_mapping   # ← 2-tuple propagé aux callers
```

Les callers (`async_chat`, `async_chat_streamly`, `async_chat_with_tools`, `async_chat_streamly_with_tools`) déballent le tuple et réhydratent la réponse :

```python
# Non-streaming
completion_args, pii_mapping = self._construct_completion_args(...)
ans = response.choices[0].message.content
if pii_mapping:
    from rag.llm.pii_masking import unmask_text
    ans = unmask_text(ans, pii_mapping)

# Streaming
_pii_unmasker = StreamingUnmasker(pii_mapping) if pii_mapping else None
async for chunk in response:
    chunk = _pii_unmasker.process_chunk(chunk) if _pii_unmasker else chunk
    if chunk:
        yield chunk
if _pii_unmasker:
    tail = _pii_unmasker.flush()
    if tail:
        yield tail
```

> Les engines `AnalyzerEngine` et `AnonymizerEngine` sont thread-safe (stateless par appel) — pas de lock nécessaire dans le hot path.

---

## Module `rag/llm/pii_masking.py`

### Interface publique

```python
from dataclasses import dataclass, field
from typing import AsyncIterator

@dataclass
class DetectedEntity:
    entity_type: str    # "EMAIL_ADDRESS", "PERSON", …
    start: int          # position de début dans le texte original
    end: int            # position de fin
    score: float        # score de confiance Presidio (0.0–1.0)
    placeholder: str    # "<EMAIL_ADDRESS_1>", "<PERSON_2>", … (numéroté)
    recognizer: str = ""  # "SpacyRecognizer" pour NER, "EmailRecognizer" pour regex, etc.

@dataclass
class MaskingResult:
    masked_text: str
    mapping: dict[str, str]          # {"<EMAIL_ADDRESS_1>": "john@...", "<PERSON_1>": "Jean Dupont"}
    entities: list[DetectedEntity]   # détail complet des entités trouvées

class PiiMaskingEngine:
    def mask_messages(
        self,
        messages: list[dict],
        language: str = "en",
        roles_to_mask: list[str] | None = None,  # défaut: ["user"]
        mask: bool = True,
    ) -> tuple[list[dict], dict[str, str], dict[str, list[DetectedEntity]]]:
        """
        Masque les PII dans une liste de messages au format OpenAI.
        Retourne :
          - messages masqués
          - mapping {placeholder → valeur originale} pour la réhydratation
          - entities_by_role {role → [DetectedEntity]} (rôle correct pour l'audit log)
        Un seul _SharedMaskingState est partagé entre tous les messages :
        même valeur → même placeholder numéroté dans tous les rôles.
        """
        ...

    def _mask_text(
        self,
        text: str,
        language: str = "en",
        mask: bool = True,
        shared_state: "_SharedMaskingState | None" = None,
    ) -> MaskingResult:
        """Analyse et anonymise un texte unique."""
        ...

def apply_pii_masking(
    history: list[dict],
    model_name: str,
    prefix: str,
    provider: str,
) -> tuple[list[dict], str, dict[str, str]]:
    """
    Point d'entrée appelé depuis LiteLLMBase._construct_completion_args().
    Retourne (masked_history, effective_model_name, mapping).
    - effective_model_name : suffixe ::pii strippé.
    - mapping : {placeholder → valeur originale}, vide si masquage non appliqué.
    """
    ...

def unmask_text(text: str, mapping: dict[str, str]) -> str:
    """Remplace tous les placeholders dans text par leurs valeurs originales."""
    ...

class StreamingUnmasker:
    """
    Transforme un stream de chunks en remplaçant les placeholders PII
    par leurs valeurs originales au fil de la réception.
    Utilise un sliding window pour gérer les placeholders fragmentés.
    """
    MAX_PLACEHOLDER_LEN = 60

    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping
        self.buffer = ""

    def process_chunk(self, chunk: str) -> str:
        """Retourne la partie du chunk prête à être émise (démasquée)."""
        ...

    def flush(self) -> str:
        """Libère le buffer en fin de stream."""
        ...

async def unmask_stream(
    stream: AsyncIterator[str],
    mapping: dict[str, str],
) -> AsyncIterator[str]:
    """Wrapper async autour de StreamingUnmasker pour les générateurs RAGFlow."""
    unmasker = StreamingUnmasker(mapping)
    async for chunk in stream:
        out = unmasker.process_chunk(chunk)
        if out:
            yield out
    tail = unmasker.flush()
    if tail:
        yield tail

class PiiAuditLogger:
    """
    Journalise les événements de détection PII sans jamais exposer
    les valeurs originales ni les mappings placeholder→valeur.
    Niveau : INFO (logger Python "ragflow.pii" + fichier dédié si configuré).
    """
    def log_detection(
        self,
        entities: list[DetectedEntity],
        conversation_id: str | None = None,
        message_role: str = "user",
        model: str | None = None,
    ) -> None:
        """
        Émet un log structuré par entité détectée.
        Ne logue jamais la valeur originale ni le mapping.
        message_role reflète le rôle réel du message (user, system, …).
        """
        ...
```

### Algorithme StreamingUnmasker

```
buffer = ""

Pour chaque chunk reçu :
  buffer += chunk

  TANT QUE buffer non vide :
    SI buffer ne commence pas par '<' :
      Trouver le prochain '<'
      SI aucun '<' → flush tout le buffer → output
      SINON → flush jusqu'au '<', conserver le reste
    SINON (buffer commence par '<') :
      Chercher '>' dans buffer
      SI pas de '>' trouvé :
        SI len(buffer) > MAX_PLACEHOLDER_LEN → flush le premier char (faux positif)
        SINON → attendre le prochain chunk (BREAK)
      SI '>' trouvé :
        candidate = buffer jusqu'au '>' inclus
        SI candidate dans mapping → output += mapping[candidate]
        SINON → output += candidate (placeholder inconnu, passthrough)
        buffer = reste après '>'

À la fin du stream :
  Remplacer les placeholders restants dans buffer via mapping
  flush le buffer restant → output
```

---

## Configuration

### Variables d'environnement (docker/.env)

```env
# ── Masquage ──────────────────────────────────────────────────────────────────

# Active le masquage PII avant envoi au LLM
PII_MASKING_ENABLED=false

# Ciblage des modèles — liste de patterns regex (Java/Python re) séparés par des virgules
# Chaque pattern est testé contre la chaîne "model_name@factory" au sens RAGFlow
# (ex: "gpt-4o@OpenAI", "claude-3-5-sonnet-20241022@Anthropic", "llama3@Ollama")
#
# Vide ou absent → aucun modèle masqué (opt-in explicite requis)
#
# Exemples de patterns :
#   .*@OpenAI              → tous les modèles OpenAI
#   .*@Anthropic           → tous les modèles Anthropic
#   .*@Bedrock             → tous les modèles AWS Bedrock
#   gpt-4.*@OpenAI         → GPT-4 et variantes uniquement
#   (?!.*@Ollama).*        → tout sauf Ollama (blacklist via negative lookahead)
#
# Valeur recommandée en production (tous les providers cloud) :
# PII_MASKING_PROVIDERS=.*@OpenAI,.*@Anthropic,.*@Bedrock,.*@Azure-OpenAI,.*@Gemini,.*@Groq,.*@DeepSeek
PII_MASKING_PROVIDERS=

# Langues supportées pour la détection (comma-separated)
# Valeurs possibles : en, fr
# Note : chaque langue nécessite son modèle spaCy téléchargé
PII_MASKING_LANGUAGES=en

# Entités à masquer et action associée (MASK ou BLOCK)
# Format : ENTITY_TYPE:ACTION,ENTITY_TYPE:ACTION,...
# MASK  → remplace par un placeholder (<EMAIL_ADDRESS>, <PERSON>, …)
# BLOCK → rejette la requête avec HTTP 400 si l'entité est détectée
PII_MASKING_ENTITIES=PERSON:MASK,EMAIL_ADDRESS:MASK,PHONE_NUMBER:MASK,CREDIT_CARD:MASK,IBAN_CODE:MASK,IP_ADDRESS:MASK

# Seuil de confiance global (0.0–1.0) en dessous duquel une détection est ignorée
# Un seuil élevé réduit les faux positifs mais augmente les faux négatifs
PII_MASKING_SCORE_THRESHOLD=0.7

# Seuils par type d'entité — surchargent PII_MASKING_SCORE_THRESHOLD pour ce type
# Format : ENTITY_TYPE:SCORE,ENTITY_TYPE:SCORE,...
# Exemple : PERSON plus strict (faux positifs fréquents sur prénoms communs)
PII_MASKING_SCORE_OVERRIDES=PERSON:0.85,CREDIT_CARD:0.6

# Rôles des messages à masquer (comma-separated)
# "user" uniquement par défaut — ne pas masquer "system" ni "assistant"
PII_MASKING_ROLES=user

# Comportement si le chargement des modèles échoue au démarrage
# true  : le serveur refuse de démarrer — garanti que le masquage est actif ou le serveur s'arrête
# false (défaut) : log error + masquage silencieusement désactivé — le serveur démarre quand même
PII_MASKING_STARTUP_FAIL=false

# ── NER (spaCy) ───────────────────────────────────────────────────────────────

# Active la détection par NER (Natural Entity Recognition via spaCy)
# Requis pour détecter : PERSON, LOCATION, DATE_TIME
# Si false : seuls les recognizers regex/checksum sont actifs (EMAIL, PHONE, CREDIT_CARD…)
#            les modèles spaCy ne sont pas chargés (démarrage plus rapide, image plus légère)
# Si true  : les modèles spaCy sont chargés au démarrage selon les langues configurées
PII_MASKING_NER=false

# Modèle spaCy à utiliser pour l'anglais
# Valeurs : en_core_web_sm (défaut, déjà installé via pyproject.toml) | en_core_web_md | en_core_web_lg (précis, ~750 MB)
# Note : en_core_web_trf (transformers) requiert PyTorch — non recommandé sans GPU
PII_MASKING_NER_MODEL_EN=en_core_web_sm

# Modèle spaCy à utiliser pour le français (si "fr" dans PII_MASKING_LANGUAGES)
# Valeurs : fr_core_news_sm | fr_core_news_md | fr_core_news_lg (défaut)
PII_MASKING_NER_MODEL_FR=fr_core_news_lg

# ── Audit log ─────────────────────────────────────────────────────────────────

# Active la journalisation des détections PII (indépendant de PII_MASKING_ENABLED)
# Peut être activé seul pour un mode "audit sans masquage"
PII_AUDIT_LOG_ENABLED=false

# Niveau de détail des logs
# "summary"  : type d'entité + nombre détecté par message (recommandé en prod)
# "detailed" : type + nombre + position (start/end) + score de confiance (debug)
PII_AUDIT_LOG_LEVEL=summary

# Destination des logs
# "app"      : via le logger Python applicatif (logger "ragflow.pii", niveau INFO)
# "file"     : fichier dédié (chemin défini par PII_AUDIT_LOG_FILE)
# "both"     : les deux destinations
PII_AUDIT_LOG_DESTINATION=app

# Chemin du fichier de log dédié (si PII_AUDIT_LOG_DESTINATION=file ou both)
# Rotation à configurer via logrotate ou handler Python RotatingFileHandler
PII_AUDIT_LOG_FILE=/ragflow/logs/pii_audit.log
```

### Entités Presidio built-in

La colonne **Mécanisme** indique si l'entité dépend de spaCy (NER) ou fonctionne sans modèle (Regex/Checksum).

| Entité | Exemples | Mécanisme | Seuil recommandé | Action par défaut |
|--------|----------|-----------|-----------------|-------------------|
| `EMAIL_ADDRESS` | john@example.com | Regex | 1.0 (certain) | MASK |
| `PHONE_NUMBER` | +33 6 12 34 56 78 | Regex | 0.75 | MASK |
| `CREDIT_CARD` | 4111 1111 1111 1111 | Regex + Luhn | 0.6 | MASK |
| `IBAN_CODE` | FR76 3000 6000 0112 | Regex + checksum | 0.6 | MASK |
| `IP_ADDRESS` | 192.168.1.1 | Regex | 0.95 | MASK |
| `MEDICAL_LICENSE` | — | Regex | 0.7 | MASK |
| `SSN` (US) | 123-45-6789 | Regex | 0.85 | MASK |
| `NRP` | numéros de passeport | Regex | 0.85 | MASK |
| `PERSON` | Jean Dupont | **spaCy NER** | **0.85** | MASK |
| `LOCATION` | Paris, 75008 | **spaCy NER** | 0.7 | optionnel |
| `DATE_TIME` | 12/03/1985 | **spaCy NER** | 0.85 | optionnel |

> **Factory names RAGFlow disponibles** (valeurs `@factory` dans `PII_MASKING_PROVIDERS`) :
> `OpenAI`, `Anthropic`, `Azure-OpenAI`, `Bedrock`, `Gemini`, `Groq`, `DeepSeek`, `Ollama`,
> `Tongyi-Qianwen`, `Moonshot`, `xAI`, `Cohere`, `NVIDIA`, `TogetherAI`, `SILICONFLOW`,
> `OpenRouter`, `ZHIPU-AI`, `MiniMax`, `DeepInfra`, `GPUStack`, `Upstage`, `NovitaAI`, …

> **Important** : les entités marquées **spaCy NER** ne sont actives que si `PII_MASKING_NER=true`. Si `PII_MASKING_NER=false` (défaut), elles sont silencieusement ignorées même si présentes dans `PII_MASKING_ENTITIES` — aucun modèle spaCy n'est chargé, l'image Docker reste allégée (~750 MB économisés par langue).

### Recognizers personnalisés

En complément des entités built-in, `pii_masking.py` expose un mécanisme de **recognizers custom** pour détecter des patterns métier spécifiques.

#### Définition via fichier YAML

La liste des recognizers custom est définie dans un fichier YAML chargé au démarrage par `PiiMaskingEngine` :

```env
# Chemin vers le fichier de recognizers personnalisés
# Si absent ou vide, aucun recognizer custom n'est chargé
PII_MASKING_CUSTOM_RECOGNIZERS_FILE=/ragflow/conf/pii_custom_recognizers.yaml
```

Format du fichier YAML :

```yaml
# /ragflow/conf/pii_custom_recognizers.yaml

recognizers:
  # Recognizer par pattern regex
  - name: "EurelisEmployeeId"
    supported_entity: "EURELIS_EMPLOYEE_ID"
    type: "pattern"
    patterns:
      - name: "eurelis_id_pattern"
        regex: "ERL-\\d{6}"
        score: 1.0
    language: "en"   # ou "fr", ou liste ["en", "fr"]
    action: "MASK"   # MASK ou BLOCK

  # Recognizer par liste de valeurs exactes (deny-list)
  - name: "InternalProjectNames"
    supported_entity: "INTERNAL_PROJECT"
    type: "deny_list"
    deny_list:
      - "Projet Orion"
      - "Operation Nightfall"
      - "RAGFlow-Internal"
    action: "BLOCK"

  # Recognizer par pattern avec contexte (booste le score si mots-clés proches)
  - name: "FrenchSSN"
    supported_entity: "FR_SSN"
    type: "pattern"
    patterns:
      - name: "fr_ssn"
        regex: "\\b[12]\\s?\\d{2}\\s?\\d{2}\\s?\\d{2}\\s?\\d{3}\\s?\\d{3}\\s?\\d{2}\\b"
        score: 0.5
    context:
      - "numéro de sécurité sociale"
      - "sécu"
      - "NIR"
    # Le score passe à 0.85 si un mot de contexte est trouvé à ±10 tokens
    language: "fr"
    action: "MASK"
```

#### Types de recognizers

| Type | Mécanisme | Quand l'utiliser |
|------|-----------|-----------------|
| `pattern` | Regex avec score fixe | Formats structurés (IDs internes, codes métier) |
| `deny_list` | Correspondance exacte (insensible à la casse) | Listes connues à l'avance (noms de projets, codes secrets) |
| `pattern` + `context` | Regex + boost de score par mots-clés proches | Patterns ambigus qui deviennent certains avec contexte |

#### Chargement et validation au démarrage

`PiiMaskingEngine.initialize()` :
1. Charge le fichier YAML si `PII_MASKING_CUSTOM_RECOGNIZERS_FILE` est défini
2. Valide chaque recognizer (regex compilable, champs requis présents)
3. Enregistre les recognizers dans l'`AnalyzerEngine`
4. En cas d'erreur de validation → log warning + recognizer ignoré (non bloquant)
5. Loggue le nombre de recognizers custom chargés :
   ```
   INFO  ragflow_server  PiiMaskingEngine: 3 custom recognizers loaded (EurelisEmployeeId, InternalProjectNames, FrenchSSN)
   ```

---

## Coexistence direct et masqué pour un même modèle

Un même modèle-fournisseur doit pouvoir être utilisé à la fois en appel direct (sans masquage) et à travers le PII masking selon le contexte d'usage. Deux approches sont spécifiées : l'Option A est retenue pour le MVP, l'Option B pour la v1.

### Option A — Suffixe `::pii` sur le nom du modèle *(MVP)*

> **Approche retenue pour le MVP.** Cohérente avec les conventions existantes de RAGFlow (suffixe `___LocalAI`, `___HuggingFace`, etc.).

#### Principe

L'administrateur tenant enregistre deux entrées de modèle pour le même provider :

| Entrée dans RAGFlow | Comportement | `PII_MASKING_PROVIDERS` |
|---------------------|-------------|------------------------|
| `gpt-4o@OpenAI` | Appel direct, aucun masquage | ne matche pas |
| `gpt-4o::pii@OpenAI` | Masquage PII activé | `.*::pii@.*` |

Le suffixe `::pii` est strippé avant l'appel LiteLLM — le provider reçoit bien `gpt-4o`, pas `gpt-4o::pii`.

#### Configuration `PII_MASKING_PROVIDERS`

Pour cibler uniquement les entrées suffixées :

```env
# Masquer uniquement les modèles enregistrés avec le suffixe ::pii
PII_MASKING_PROVIDERS=.*::pii@.*

# Ou restreindre à un provider spécifique :
PII_MASKING_PROVIDERS=.*::pii@OpenAI,.*::pii@Anthropic,.*::pii@Bedrock
```

#### Implémentation dans le hook

```python
# rag/llm/chat_model.py — LiteLLMBase._construct_completion_args()

PII_MODEL_SUFFIX = "::pii"

# Construire la cible de matching AVANT stripping
raw_model_name = self.model_name.removeprefix(self.prefix)
match_target = f"{raw_model_name}@{self.provider}"   # ex: "gpt-4o::pii@OpenAI"

# Vérifier la whitelist
providers_filter = os.getenv("PII_MASKING_PROVIDERS", "").strip()
should_mask = bool(providers_filter) and any(
    re.fullmatch(p.strip(), match_target)
    for p in providers_filter.split(",") if p.strip()
)

# Stripper le suffixe ::pii du model_name envoyé à LiteLLM
effective_model_name = self.model_name
if raw_model_name.endswith(PII_MODEL_SUFFIX):
    effective_model_name = self.prefix + raw_model_name[: -len(PII_MODEL_SUFFIX)]

completion_args = {
    "model": effective_model_name,   # ← gpt-4o (sans ::pii)
    "messages": masked_history if should_mask else history,
    ...
}
```

#### Expérience utilisateur

Dans l'UI RAGFlow (Settings → Models), l'administrateur voit deux entrées :
```
OpenAI  │  gpt-4o          │  Chat  │  Enabled   ← direct
OpenAI  │  gpt-4o::pii     │  Chat  │  Enabled   ← avec masquage PII
```

Il assigne `gpt-4o::pii` aux Dialogs/Agents qui traitent des données sensibles, et `gpt-4o` aux autres.

#### Limites

- La liste des modèles présente des doublons — à documenter pour les administrateurs
- Le suffixe `::pii` est une convention : aucune validation empêche de l'utiliser sans activer `PII_MASKING_ENABLED`

---

### Option B — Champ `pii_masking` sur `Dialog` *(v1)*

> **Approche v1.** Plus propre architecturalement : un seul modèle enregistré, le masquage est une propriété de la conversation.

#### Principe

Le masquage est activé au niveau du `Dialog` (la conversation configurée), pas du modèle. Un même `gpt-4o@OpenAI` peut être utilisé avec ou sans masquage selon la conversation.

```
Dialog "Support client"   → llm=gpt-4o@OpenAI, pii_masking=true
Dialog "Analyse interne"  → llm=gpt-4o@OpenAI, pii_masking=false
```

#### Changements de schéma

```python
# api/db/db_models.py — modèle Dialog
class Dialog(DataBaseModel):
    ...
    pii_masking = BooleanField(default=False, help_text="Enable PII masking for this dialog")
```

Migration SQL :
```sql
ALTER TABLE dialog ADD COLUMN pii_masking TINYINT(1) NOT NULL DEFAULT 0;
```

#### Transmission jusqu'au hook

Le flag `pii_masking` du Dialog doit être propagé jusqu'à `_construct_completion_args()` via les `kwargs` :

```
dialog_service.async_chat(dialog, messages)
    → dialog.pii_masking → True
    → llm_bundle.async_chat_streamly(..., pii_masking=True)
    → LiteLLMBase._construct_completion_args(..., pii_masking=True)
    → should_mask = kwargs.get("pii_masking", False)
```

Si `pii_masking=True` dans kwargs, le masquage est appliqué **indépendamment** de `PII_MASKING_PROVIDERS` (le flag dialog prime).

#### Changements frontend

Ajouter un toggle dans les settings du Dialog :

```
[x] Activer le masquage PII
    Les données personnelles dans les messages seront masquées
    avant envoi au LLM. Voir la documentation RGPD.
```

#### Avantages sur Option A

| Critère | Option A (suffixe) | Option B (Dialog flag) |
|---------|-------------------|----------------------|
| Doublons dans la liste modèles | Oui | Non |
| Granularité | Par modèle | Par conversation |
| Complexité implémentation | Faible | Moyenne |
| Lisibilité pour l'admin | Faible (nommage implicite) | Élevée (UI explicite) |
| Migration DB | Non | Oui |

---

## Audit Log

### Principe de sécurité

Le log PII **ne doit jamais contenir** :
- La valeur originale (`john@example.com`, `Jean Dupont`, …)
- Le mapping placeholder → valeur originale
- Le texte masqué (qui pourrait être partiellement réversible)

Il contient uniquement des **métadonnées de détection** permettant l'audit de conformité.

### Format des entrées de log

#### Mode `summary` (production)

```
[2026-05-31T14:32:11Z] [ragflow.pii] INFO pii_detected conversation_id=abc123 role=user entities=EMAIL_ADDRESS:1,PERSON:2 total=3 model=gpt-4o@OpenAI
```

Champs :
| Champ | Description |
|-------|-------------|
| `conversation_id` | Identifiant de la conversation (si disponible, sinon `unknown`) |
| `role` | Rôle du message (`user`) |
| `entities` | `TYPE:count` pour chaque type détecté |
| `total` | Nombre total d'entités dans le message |

#### Mode `detailed` (debug)

```
[2026-05-31T14:32:11Z] [ragflow.pii] INFO pii_detected conversation_id=abc123 role=user entity_type=EMAIL_ADDRESS placeholder=<EMAIL_ADDRESS_1> start=14 end=30 score=0.99 recognizer=EmailRecognizer model=gpt-4o@OpenAI
[2026-05-31T14:32:11Z] [ragflow.pii] INFO pii_detected conversation_id=abc123 role=system entity_type=PERSON placeholder=<PERSON_1> start=46 end=57 score=0.85 recognizer=SpacyRecognizer model=gpt-4o@OpenAI
```

> **Note** : `role` reflète le rôle réel du message — `system` pour les détections dans le contexte RAG, `user` pour les messages utilisateur. Les placeholders sont numérotés (`_1`, `_2`, …) et cohérents entre messages : la même valeur reçoit le même placeholder quel que soit le rôle.

Champs supplémentaires :
| Champ | Description |
|-------|-------------|
| `placeholder` | Placeholder généré (`<EMAIL_ADDRESS>`, `<PERSON>`, …) — sans la valeur originale |
| `start` / `end` | Position de l'entité dans le message original |
| `score` | Score de confiance Presidio (0.0–1.0) |
| `recognizer` | Nom du recognizer Presidio ayant détecté l'entité (`EmailRecognizer`, `SpacyRecognizer`, …) |

> **Note** : `start`/`end` et `placeholder` suffisent à un auditeur pour vérifier qu'une entité a été masquée, sans révéler la valeur originale.

### Mode "audit sans masquage"

Si `PII_AUDIT_LOG_ENABLED=true` et `PII_MASKING_ENABLED=false`, Presidio tourne en **analyse seule** (pas d'anonymisation). Utile pour mesurer la présence de PII dans les conversations existantes sans modifier le comportement.

```
PII_MASKING_ENABLED=false
PII_AUDIT_LOG_ENABLED=true   # ← détecte et log, mais ne masque pas
PII_AUDIT_LOG_LEVEL=summary
```

### Intégration dans le point d'injection

L'audit est géré dans `apply_pii_masking()`, qui appelle `engine.audit_logger.log_detection()` une fois par rôle présent dans `entities_by_role` :

```python
# rag/llm/pii_masking.py — apply_pii_masking()

masked_history, mapping, entities_by_role = engine.mask_messages(
    messages=history,
    language=language,
    roles_to_mask=roles,
    mask=masking_enabled,  # False = mode audit seul, messages non modifiés
)

if audit_enabled and entities_by_role:
    for role, entities in entities_by_role.items():
        engine.audit_logger.log_detection(
            entities=entities,
            message_role=role,   # "user", "system", …
            model=match_target,
        )
```

> En mode `PII_MASKING_ENABLED=false` + `PII_AUDIT_LOG_ENABLED=true` : Presidio analyse mais n'anonymise pas. Les messages retournés sont inchangés, les logs de détection sont émis.

---

## Dépendances Python

```toml
# pyproject.toml — dépendances ajoutées
"presidio-analyzer>=2.2.354",
"presidio-anonymizer>=2.2.354",

# Modèle spaCy anglais — déjà déclaré comme wheel dans pyproject.toml (utilisé aussi par GraphRAG)
"en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl"

# Modèles plus larges (NER précis) — à télécharger manuellement si besoin :
# → uv run python -m spacy download en_core_web_lg  (~750 MB)
# Français (si PII_MASKING_LANGUAGES contient "fr") :
# → uv run python -m spacy download fr_core_news_lg  (~550 MB)
```

> **Note Docker** : `en_core_web_sm` est inclus via `uv sync`. Les modèles `lg` doivent être téléchargés dans l'image (`RUN python -m spacy download en_core_web_lg`) si NER haute précision est requis. Prévoir +1 GB d'espace image par modèle large.

---

## Point d'injection dans `chat_model.py`

```python
# rag/llm/chat_model.py — classe LiteLLMBase

def _construct_completion_args(self, history, stream: bool, tools: bool, **kwargs):
    # --- PII MASKING (Eurelis) ---
    effective_model_name = self.model_name
    pii_mapping: dict = {}
    try:
        from rag.llm.pii_masking import PiiBlockedException, apply_pii_masking
        history, effective_model_name, pii_mapping = apply_pii_masking(
            history=history,
            model_name=self.model_name,
            prefix=self.prefix,
            provider=str(self.provider),
        )
    except PiiBlockedException:
        raise
    except Exception as _pii_exc:
        logging.warning(f"PII masking error (continuing without masking): {_pii_exc}")
    # --- END PII MASKING ---

    completion_args = {
        "model": effective_model_name,  # ::pii strippé si présent
        "messages": history,
        ...
    }
    return completion_args, pii_mapping  # 2-tuple : les callers réhydratent la réponse
```

---

## Intégration GeminiCV (modèles Gemini natifs)

Les modèles Gemini dans la factory **Gemini** (`model_type: image2text`) utilisent le client Google genai natif (`GeminiCV`) et non LiteLLMBase. L'intégration PII masking a été ajoutée directement dans `rag/llm/cv_model.py`.

**Spécificités :**
- Le `system` (contexte RAG, potentiellement large) et l'`history` sont **combinés** en un seul appel `apply_pii_masking`, puis re-séparés pour `_form_history`.
- Le suffixe `::pii` est strippé dans `__init__` avant l'appel API Gemini.
- `self._original_model_name` conserve le nom avec suffixe pour le matching provider.
- En mode streaming, `StreamingUnmasker` est utilisé chunk par chunk + `flush()` en fin de stream.

**Configuration identique :**
```env
PII_MASKING_PROVIDERS=.*::pii@.*
# ou pour tous les modèles Gemini :
# PII_MASKING_PROVIDERS=.*@Gemini
```

> **Note performance** : avec un contexte RAG de plusieurs dizaines de KB, Presidio analyse l'intégralité à chaque requête. Si les performances sont critiques, considérer `PII_MASKING_ROLES=user` (ne masque pas le `system`).

---

## Cas limites et comportements attendus

| Situation | Comportement |
|-----------|-------------|
| `PII_MASKING_ENABLED=false` | Pass-through total, zéro overhead |
| Aucun PII détecté | Messages retournés inchangés, mapping vide |
| Même PII plusieurs fois dans un message | Même placeholder numéroté (`<EMAIL_ADDRESS_1>` × 2) — déduplication via `_SharedMaskingState` |
| Même PII dans user + system | Même placeholder dans les deux messages — `_SharedMaskingState` partagé sur toute la requête |
| Deux PII distincts du même type | `<EMAIL_ADDRESS_1>` et `<EMAIL_ADDRESS_2>` — compteur par type |
| PII dans message `system` | Non masqué (role non inclus dans `PII_MASKING_ROLES`) |
| PII dans message `assistant` (historique) | Non masqué par défaut |
| Faux positif (ex: prénom commun) | Masqué → `<PERSON>` → LLM répond normalement |
| Placeholder fragmenté sur 2 chunks | Géré par sliding window (buffering) |
| Chunk `<` sans `>` suivant (< MAX_LEN) | Buffer en attente du prochain chunk |
| Erreur Presidio (exception) | Log warning + fallback pass-through (ne pas bloquer le chat) |
| Mode `BLOCK` sur entité détectée | Lever une exception métier → réponse HTTP 400 avec message explicite |
| Modèle `gpt-4o::pii@OpenAI` | `::pii` strippé → LiteLLM reçoit `gpt-4o`, masquage appliqué |
| Modèle `gpt-4o@OpenAI` avec `PII_MASKING_PROVIDERS=.*::pii@.*` | No match → appel direct sans masquage |
| Suffixe `::pii` sans `PII_MASKING_ENABLED=true` | Suffixe strippé quand même (safe), mais masquage non appliqué — à documenter |
| Dialog `pii_masking=true` + `PII_MASKING_ENABLED=false` | Le flag dialog est ignoré si le moteur global est désactivé (v1) |

---

## Tests

### Tests unitaires (`test/unit_test/rag/llm/test_pii_masking.py`)

- `test_mask_email` : email simple → `<EMAIL_ADDRESS_N>` (numéroté)
- `test_mask_person` : prénom + nom → `<PERSON_N>`
- `test_mask_multiple_same_type` : 2 emails distincts → deux placeholders numérotés différents
- `test_no_pii` : texte sans PII → retour inchangé, mapping vide
- `test_mask_messages_user_only` : seul le rôle `user` est masqué
- `test_mask_disabled` : `PII_MASKING_ENABLED=false` → pass-through
- `test_streaming_unmasker_complete` : placeholder reçu en un chunk
- `test_streaming_unmasker_fragmented` : placeholder fragmenté sur 3 chunks
- `test_streaming_unmasker_false_positive` : `<` sans `>` suivant → libéré après MAX_LEN
- `test_streaming_unmasker_no_pii` : texte sans placeholder → pass-through immédiat
- `test_streaming_unmasker_flush` : placeholder partiel en fin de stream

- `test_audit_log_summary` : détection de 2 entités → log `summary` correct (type + count, sans valeur)
- `test_audit_log_detailed` : mode `detailed` → log contient `start`, `end`, `score`, `placeholder`
- `test_audit_log_no_original_value` : vérifier qu'aucun log ne contient la valeur originale (email, nom)
- `test_audit_log_disabled` : `PII_AUDIT_LOG_ENABLED=false` → aucun log émis
- `test_audit_only_mode` : `PII_MASKING_ENABLED=false` + `PII_AUDIT_LOG_ENABLED=true` → messages non modifiés, log émis
- `test_audit_log_destination_file` : mode `file` → log écrit dans `PII_AUDIT_LOG_FILE`
- `test_audit_log_destination_app` : mode `app` → log émis via logger `ragflow.pii`
- `test_audit_log_no_pii` : texte sans PII → aucun log émis
- `test_engine_initialize_loads_models` : `initialize()` avec `PII_MASKING_ENABLED=true` → singleton créé, `is_available()=True`
- `test_engine_initialize_noop` : `PII_MASKING_ENABLED=false` + `PII_AUDIT_LOG_ENABLED=false` → `initialize()` no-op, `is_available()=False`
- `test_engine_initialize_fail_startup_true` : modèle spaCy manquant + `PII_MASKING_STARTUP_FAIL=true` → `RuntimeError` levée
- `test_engine_initialize_fail_startup_false` : modèle manquant + `PII_MASKING_STARTUP_FAIL=false` → pas d'exception, `is_available()=False`
- `test_engine_singleton` : deux appels `initialize()` → même instance retournée
- `test_engine_get_before_init` : `get()` sans `initialize()` → `RuntimeError`
- `test_engine_thread_safe` : `initialize()` appelé depuis plusieurs threads simultanément → une seule instance créée
- `test_score_threshold_filters_low_confidence` : détection avec score < seuil → entité ignorée
- `test_score_threshold_global` : seuil global `0.8` → entités sous 0.8 non masquées
- `test_score_override_per_entity` : seuil PERSON=0.85 + détection à 0.80 → PERSON ignoré, EMAIL non ignoré
- `test_custom_recognizer_pattern` : recognizer regex custom → entité détectée et masquée
- `test_custom_recognizer_deny_list` : recognizer deny-list → valeur exacte détectée
- `test_custom_recognizer_context_boost` : regex + contexte → score boosté au-dessus du seuil
- `test_custom_recognizer_invalid_yaml` : YAML malformé → warning log + recognizer ignoré, démarrage non bloqué
- `test_custom_recognizer_bad_regex` : regex invalide dans YAML → warning log + recognizer ignoré
- `test_ner_disabled_no_spacy_loaded` : `PII_MASKING_NER=false` → spaCy non importé, `PERSON` dans `PII_MASKING_ENTITIES` ignoré silencieusement
- `test_ner_enabled_loads_spacy` : `PII_MASKING_NER=true` → modèle `PII_MASKING_NER_MODEL_EN` chargé, `PERSON` détecté
- `test_ner_model_en_override` : `PII_MASKING_NER_MODEL_EN=en_core_web_sm` → modèle sm chargé à la place de lg
- `test_ner_model_fr` : `PII_MASKING_LANGUAGES=fr` + `PII_MASKING_NER=true` → `PII_MASKING_NER_MODEL_FR` chargé
- `test_ner_excludes_unused_components` : modèle chargé avec `exclude=[tagger, parser, lemmatizer]` → composants absents du pipeline
- `test_providers_empty_no_masking` : `PII_MASKING_PROVIDERS=` vide → aucun modèle masqué
- `test_providers_exact_match` : pattern `.*@OpenAI` → match `gpt-4o@OpenAI`, no-match `gpt-4o@Ollama`
- `test_providers_model_pattern` : pattern `gpt-4.*@OpenAI` → match `gpt-4o@OpenAI`, no-match `gpt-3.5-turbo@OpenAI`
- `test_providers_multiple_patterns` : `.*@OpenAI,.*@Anthropic` → match les deux providers
- `test_providers_negative_lookahead` : `(?!.*@Ollama).*` → match tout sauf Ollama
- `test_providers_invalid_regex` : pattern regex invalide → log warning + pattern ignoré, pas d'exception
- `test_suffix_pii_stripped_from_model_name` : `gpt-4o::pii@OpenAI` → LiteLLM appelé avec `gpt-4o`, masquage activé
- `test_suffix_pii_match_target_includes_suffix` : le matching regex se fait sur `gpt-4o::pii@OpenAI` (avec suffixe), pas sur `gpt-4o@OpenAI`
- `test_suffix_pii_without_masking_enabled` : suffixe `::pii` strippé même si `PII_MASKING_ENABLED=false`
- `test_no_suffix_no_masking` : `gpt-4o@OpenAI` avec `PII_MASKING_PROVIDERS=.*::pii@.*` → no match, appel direct
- `test_dialog_flag_pii_masking_true` : `kwargs["pii_masking"]=True` → masquage appliqué indépendamment de `PII_MASKING_PROVIDERS` (v1)
- `test_dialog_flag_pii_masking_false` : `kwargs["pii_masking"]=False` → pas de masquage même si modèle matche la whitelist (v1)

### Tests d'intégration

- Appel complet `LiteLLMBase` avec mock `litellm.acompletion` : vérifier que les messages envoyés sont masqués
- Variable `PII_MASKING_ENABLED=true` + message avec email → vérifier le payload envoyé au LLM
- `PII_AUDIT_LOG_ENABLED=true` + message avec PII → vérifier la présence et le contenu du log (sans valeur originale)

---

## Diagnostic et logs

### Logs visibles au niveau INFO (défaut serveur)

| Log | Signification |
|-----|---------------|
| `PiiMaskingEngine initialized in X.Xs (NER: en_core_web_sm)` | Démarrage OK |
| `PII masking disabled — PiiMaskingEngine skipped` | `PII_MASKING_ENABLED=false` |
| `pii_masking: processing 'gemini-3.5-flash::pii@Gemini' (masking=True audit=True)` | Masquage actif sur la requête |
| `pii_masking: done — N placeholder(s), entities_by_role={'user': [...]}` | Résultat du masquage |
| `pii_masking: skipped — engine not initialized` | WARN — `initialize()` non appelé |

### Activer les logs DEBUG

Pour voir les décisions de filtrage (`skipped — X does not match providers filter`) :

```env
LOG_LEVELS=rag.llm.pii_masking=DEBUG
```

---

## Risques et limitations

| Risque | Mitigation |
|--------|-----------|
| Faux négatifs (PII non détecté) | Presidio n'est pas infaillible ; documenter comme "best effort", pas comme garantie absolue |
| Impact performance | Presidio ajoute ~50-200ms par message selon la longueur. Acceptable ; à mesurer |
| Taille image Docker (+1 GB) | Modèles embarqués dans l'image Docker via `RUN python -m spacy download` dans le Dockerfile |
| Temps de démarrage allongé | Premier démarrage : +3–8s par modèle spaCy chargé. Logué explicitement pour visibilité |
| Multilingue imparfait | Le détecteur de langue automatique est moins précis ; recommander de fixer la langue |
| Unmasking partiel | Si le LLM paraphrase un placeholder, le démasquage échoue silencieusement (passthrough) |
| Confidentialité du mapping | Le mapping `placeholder → valeur originale` vit en mémoire le temps de la requête — ne jamais le logger |
| Fuite de valeur dans les logs | `PiiAuditLogger` ne logue jamais la valeur originale — à auditer dans les reviews |
| Rotation des fichiers de log | Sans rotation, `pii_audit.log` peut croître indéfiniment — configurer `RotatingFileHandler` ou logrotate |
| Log activé sans masquage | Le mode "audit only" révèle la présence de PII mais ne les masque pas — documenter clairement ce mode |
| Seuil trop bas → faux positifs | `PERSON` avec seuil 0.5 masquera des mots communs — recommander 0.85 minimum |
| Seuil trop haut → faux négatifs | `CREDIT_CARD` avec seuil 0.9 peut rater des numéros légèrement ambigus — recommander 0.6 |
| Recognizer custom regex catastrophique | Une regex trop générale peut masquer du contenu légitime à grande échelle — valider dans un environnement de test avant activation |
| YAML recognizers rechargé à chaud | Non supporté : toute modification du fichier YAML nécessite un redémarrage du serveur |
| Suffixe `::pii` mal compris | Un admin peut nommer un modèle `::pii` sans activer le masquage — ajouter un warning au démarrage si suffixe détecté mais `PII_MASKING_ENABLED=false` |
| Migration Dialog (Option B) | La migration ALTER TABLE doit être non-destructive (DEFAULT 0) et testée sur les données existantes |

---

## Références

- [Microsoft Presidio — GitHub](https://github.com/microsoft/presidio)
- [Presidio — Python quickstart](https://microsoft.github.io/presidio/getting_started/)
- [LiteLLM — PII Masking v2 (proxy guardrails)](https://docs.litellm.ai/docs/proxy/guardrails/pii_masking_v2)
- [spaCy — modèles disponibles](https://spacy.io/models)
