# Eurelis — configuration des tests de non-régression (endpoints, credentials, modèles Ollama).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.

import os

# --- Endpoints (surchargables par variables d'environnement) --------------------------------
# Adresses vues depuis l'HÔTE (où tourne pytest).
HOST_ADDRESS = os.getenv("HOST_ADDRESS", "http://localhost:9380")      # API Quart RAGFlow
ADMIN_ADDRESS = os.getenv("ADMIN_ADDRESS", "http://localhost:9381")    # serveur admin Flask
VERSION = "v1"

# URL d'Ollama vue depuis le CONTENEUR ragflow (réseau Docker), pas depuis l'hôte : c'est le
# serveur RAGFlow qui appelle Ollama lors de la validation/inférence.
OLLAMA_INTERNAL_URL = os.getenv("OLLAMA_INTERNAL_URL", "http://ollama:11434")

# --- Utilisateur de test --------------------------------------------------------------------
EMAIL = os.getenv("EURELIS_TEST_EMAIL", "qa@eurelis.test")
NICKNAME = "qa"
# Second utilisateur, pour les tests d'équipe (chats partagés).
TEAMMATE_EMAIL = os.getenv("EURELIS_TEAMMATE_EMAIL", "qa-teammate@eurelis.test")
TEAMMATE_NICKNAME = "qa-teammate"

# --- Administrateur (serveur Flask :9381) ---------------------------------------------------
ADMIN_EMAIL = os.getenv("EURELIS_ADMIN_EMAIL", "admin@ragflow.io")
ADMIN_PASSWORD_PLAIN = os.getenv("EURELIS_ADMIN_PASSWORD", "admin")
# Mot de passe "123" chiffré RSA avec la clé publique RAGFlow (stable, même codebase).
# Vérifié empiriquement contre l'image eurelis/ragflow:v0.26.1-eurelis.3.
PASSWORD = (
    "ctAseGvejiaSWWZ88T/m4FQVOpQyUvP+x7sXtdv3feqZACiQleuewkUi35E16wSd5C5QcnkkcV9cYc8TKPTRZlxa"
    "ppDuirxghxoOvFcJxFU4ixLsDfN33jCHRoDUW81IH9zjij/vaw8IbVyb6vuwg6MX6inOEBRRzVbRYxXOu1wkWY6S"
    "sI8X70oF9aeLFp/PzQpjoe/YbSqpTq8qqrmHzn9vO+yvyYyvmDsphXeX8f7fp9c7vUsfOCkM+gHY3PadG+QHa7KI"
    "7mzTKgUTZImK6BZtfRBATDTthEUbbaTewY4H0MnWiCeeDhcbeQao6cFy1To8pE3RpmxnGnS8BsBn8w=="
)

# --- Modèles locaux Ollama (préchargés par `make e2e-models`) -------------------------------
OLLAMA_PROVIDER = "Ollama"
OLLAMA_INSTANCE = "local"
CHAT_MODEL = os.getenv("EURELIS_CHAT_MODEL", "qwen2.5:0.5b")
EMBED_MODEL = os.getenv("EURELIS_EMBED_MODEL", "nomic-embed-text")
EMBED_DIM = 768  # dimension des vecteurs nomic-embed-text
# Modèle de vision (image2text) — palier optionnel « extraction de contenu par LLM » (opt-in).
# Local (Ollama) par défaut ; bascule sur OpenAI cloud si OPENAI_API_KEY est présent (inférence
# distante → pas de pression mémoire locale sur ES).
VISION_MODEL = os.getenv("EURELIS_VISION_MODEL", "moondream")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_PROVIDER = "OpenAI"
OPENAI_INSTANCE = "cloud"
OPENAI_VISION_MODEL = os.getenv("EURELIS_OPENAI_VISION_MODEL", "gpt-5.4-mini")

# Variante avec masquage PII : le suffixe "::pii" active le masquage (opt-in par modèle) ;
# il est retiré avant l'appel Ollama, qui reçoit donc le vrai modèle CHAT_MODEL.
PII_MODEL_SUFFIX = "::pii"
CHAT_MODEL_PII = f"{CHAT_MODEL}{PII_MODEL_SUFFIX}"

def model_ref(model_name: str) -> str:
    """Référence RAGFlow d'un modèle : model@instance@provider."""
    return f"{model_name}@{OLLAMA_INSTANCE}@{OLLAMA_PROVIDER}"

# --- Bedrock réel (palier opt-in, AILAB-22) ---------------------------------------------------
# Test e2e de non-troncature des réponses longues : nécessite de vrais credentials AWS Bedrock
# (appel cloud payant, ~1 réponse longue par run). Skippé si EURELIS_BEDROCK_TEST_AK/SK absents.
BEDROCK_PROVIDER = "Bedrock"
BEDROCK_INSTANCE = "e2e"
BEDROCK_TEST_AK = os.getenv("EURELIS_BEDROCK_TEST_AK")
BEDROCK_TEST_SK = os.getenv("EURELIS_BEDROCK_TEST_SK")
BEDROCK_TEST_REGION = os.getenv("EURELIS_BEDROCK_TEST_REGION", "eu-west-1")
BEDROCK_TEST_CHAT_MODEL = os.getenv("EURELIS_BEDROCK_TEST_CHAT_MODEL", "eu.anthropic.claude-opus-4-8")

def bedrock_ref() -> str:
    """Référence RAGFlow du modèle chat Bedrock du palier opt-in : model@instance@provider."""
    return f"{BEDROCK_TEST_CHAT_MODEL}@{BEDROCK_INSTANCE}@{BEDROCK_PROVIDER}"

# --- Reranker mock (service mock-rerank du compose de test, API Jina-compatible) -------------
# Sert uniquement à valider le logging token_type="rerank" de bout en bout (câblage chat/search),
# pas la qualité du reranking.
RERANK_PROVIDER = "Jina"
RERANK_INSTANCE = "mock"
RERANK_MODEL = "jina-reranker-v2-base-multilingual"
RERANK_API_BASE = os.getenv("EURELIS_RERANK_API_BASE", "http://mock-rerank:8080/rerank")

def rerank_ref() -> str:
    """Référence RAGFlow du reranker mock : model@instance@provider."""
    return f"{RERANK_MODEL}@{RERANK_INSTANCE}@{RERANK_PROVIDER}"

# --- Jeu de données de référence (créé par seed.py, consommé par les tests) -----------------
REF_DATASET_NAME = "eurelis-ref"
REF_CHAT_NAME = "eurelis-ref-chat"           # chat SANS masquage PII (modèle standard)
REF_CHAT_PII_NAME = "eurelis-ref-chat-pii"   # chat AVEC masquage PII (modèle suffixé ::pii)
REF_SEARCH_NAME = "eurelis-ref-search"       # Search App de référence (contrat Shield feature 028)
REF_QUERY = "Qu'est-ce que RAGFlow et que fait Eurelis ?"  # question adaptée au doc de référence
REF_DOC_NAME = "eurelis-ref.txt"
REF_DOC_TEXT = (
    "RAGFlow est un moteur RAG open source. Eurelis maintient un fork avec supervision "
    "des modèles, statistiques de consommation de tokens, masquage PII et connecteur sitemap."
)

# --- Divers ---------------------------------------------------------------------------------
# Timeout généreux : appels LLM/embedding sous émulation amd64 (Apple Silicon).
HTTP_TIMEOUT = int(os.getenv("EURELIS_HTTP_TIMEOUT", "120"))
# Délai max d'attente du parse d'un document (secondes).
PARSE_TIMEOUT = int(os.getenv("EURELIS_PARSE_TIMEOUT", "300"))
