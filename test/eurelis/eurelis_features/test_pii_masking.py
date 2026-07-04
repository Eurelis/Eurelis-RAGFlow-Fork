# Eurelis — P1 : masquage PII en intégration (opt-in par modèle ::pii). Feature Eurelis.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Observabilité via le journal d'audit `ragflow.pii` (monté sur l'hôte :
# docker/ragflow-logs/pii_audit.log). Le stack de test active PII en permanence, scopé au suffixe
# ::pii (PII_MASKING_PROVIDERS=.*::pii@.*). On vérifie que :
#   - le chat AVEC modèle ::pii déclenche une détection ;
#   - le chat SANS ::pii n'en déclenche jamais ;
#   - aucune valeur PII en clair n'est journalisée.
# Skippé automatiquement si PII est désactivé (make e2e-pii-off) : le fichier d'audit est alors absent.

import time
from pathlib import Path

import httpx
import pytest

from configs import CHAT_MODEL, CHAT_MODEL_PII, HOST_ADDRESS, HTTP_TIMEOUT, VERSION
from libs.sse import stream_completions

# Sentinelle déterministe : numéro de carte valide au checksum de Luhn → CreditCardRecognizer, score 1.00.
CREDIT_CARD = "4111 1111 1111 1111"
QUESTION = f"Ma carte bancaire est {CREDIT_CARD}, peux-tu la retenir ?"

# Journal d'audit monté sur l'hôte (docker/ragflow-logs/pii_audit.log).
AUDIT_LOG = Path(__file__).resolve().parents[3] / "docker" / "ragflow-logs" / "pii_audit.log"

pytestmark = [pytest.mark.p1, pytest.mark.pii]


def _audit_lines() -> list[str]:
    return AUDIT_LOG.read_text(encoding="utf-8").splitlines() if AUDIT_LOG.exists() else []


def _complete(token: str, chat_id: str) -> str:
    """Crée une session, envoie une complétion avec du PII, renvoie le session_id."""
    with httpx.Client(
        base_url=HOST_ADDRESS,
        headers={"Authorization": f"Bearer {token}"},
        timeout=HTTP_TIMEOUT,
    ) as client:
        sid = client.post(f"/api/{VERSION}/chats/{chat_id}/sessions", json={"name": "pii"}).json()["data"]["id"]
        stream_completions(client, chat_id, QUESTION, sid)
        return sid


def _wait_new_line(since: int, needle: str, timeout: int = 30) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for line in _audit_lines()[since:]:
            if needle in line:
                return line
        time.sleep(1)
    return None


@pytest.fixture(autouse=True)
def _require_pii_stack():
    """Skip si le stack tourne sans PII (fichier d'audit absent)."""
    if not AUDIT_LOG.exists():
        pytest.skip("masquage PII inactif (fichier d'audit absent) — stack lancée avec e2e-pii-off ?")


def test_pii_chat_triggers_masking(token, ref_chat_pii_id):
    """Le chat ::pii déclenche une détection CREDIT_CARD, journalisée sans la valeur en clair."""
    before = len(_audit_lines())
    _complete(token, ref_chat_pii_id)
    line = _wait_new_line(before, f"model={CHAT_MODEL_PII}@")
    assert line is not None, "aucune détection PII journalisée pour le modèle ::pii"
    assert "CREDIT_CARD" in line, f"entité inattendue : {line}"
    assert CREDIT_CARD.replace(" ", "") not in line and "4111" not in line, "valeur de carte en clair dans l'audit !"


def test_standard_chat_is_not_masked(token, ref_chat_id):
    """Le chat standard (modèle sans ::pii) ne déclenche jamais de masquage."""
    before = len(_audit_lines())
    _complete(token, ref_chat_id)
    # Laisser le temps à une éventuelle (indésirable) écriture d'audit.
    time.sleep(3)
    new_lines = _audit_lines()[before:]
    std_hits = [ln for ln in new_lines if f"model={CHAT_MODEL}@" in ln]
    assert not std_hits, f"le modèle standard a été masqué à tort : {std_hits}"


def test_audit_never_leaks_clear_values(token, ref_chat_pii_id):
    """Aucune ligne du journal d'audit ne contient de valeur PII en clair (propriété globale)."""
    _complete(token, ref_chat_pii_id)
    time.sleep(2)
    leaks = [ln for ln in _audit_lines() if "4111" in ln]
    assert not leaks, f"fuite de valeur PII dans l'audit : {leaks}"
