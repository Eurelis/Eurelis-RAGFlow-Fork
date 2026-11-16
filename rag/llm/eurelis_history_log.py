# Eurelis — journaux [HISTORY] des modèles de chat : images base64 tronquées (AILAB-52).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# `Base` et `LiteLLMBase` journalisent tout l'historique envoyé au modèle. Avec les pages de PDF
# scannés transmises en images, chaque requête écrivait 2 à 3 Mo de base64 dans les logs. On remplace
# chaque image (data URI, ou base64 nu des blocs Anthropic/Gemini) par un résumé de sa taille.

import json
import re

_KEEP = 48  # début conservé (type MIME et premiers octets)
_MIN_LEN = 256
_BASE64 = re.compile(r"[A-Za-z0-9+/=\r\n]+")


def _is_base64_blob(value: str) -> bool:
    if value.startswith("data:") and ";base64," in value[:100]:
        return True
    return len(value) >= 1024 and _BASE64.fullmatch(value[:512]) is not None and _BASE64.fullmatch(value[-512:]) is not None


def truncate_data_uris(value):
    """Copie de `value` (dict, list, str…) où les images base64 sont résumées ; le reste est inchangé."""
    if isinstance(value, str):
        if len(value) >= _MIN_LEN and _is_base64_blob(value):
            return f"{value[:_KEEP]}…[base64 tronqué, {len(value)} caractères]"
        return value
    if isinstance(value, dict):
        return {k: truncate_data_uris(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [truncate_data_uris(v) for v in value]
    return value


def history_for_log(history, indent: int) -> str:
    return json.dumps(truncate_data_uris(history), ensure_ascii=False, indent=indent)
