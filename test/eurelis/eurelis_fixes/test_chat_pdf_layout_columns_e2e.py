# Eurelis — P1 (AILAB-45) : les PDF joints au chat gardent leur disposition en colonnes.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Régression gardée : `FileService.parse` (pièces jointes chat/agent) lisait les PDF par
# `page.extract_text()` en mode par défaut. Sur une balance comptable, chaque montant sortait sur sa
# propre ligne, détaché de son en-tête : le modèle ne savait plus si un montant était Débiteur,
# Créditeur ou solde N-1 (prod Synerga : 100 soldes créditeurs saisis en positif, Excel déséquilibré).
# Les pièces jointes passent désormais en mode `layout` de pypdf ; l'ingestion des bases de
# connaissances (`PlainParser()` sans option) reste en mode par défaut.
#
# Le texte transmis au modèle est celui que renvoie `FileService.parse` : on l'exécute DANS le
# conteneur sous test (docker exec), sur des PDF synthétiques générés ici (aucune donnée client).

import base64
import json

import pytest

from libs.container import docker_py, skip_reason
from libs.pdf_fixtures import BALANCE_ROWS, SIMPLE_TEXT_LINES, balance_pdf, scanned_pdf, simple_text_pdf

pytestmark = [pytest.mark.p1]

# Snippet exécuté dans le conteneur : pour chaque PDF (base64 sur stdin), le texte des pièces jointes
# (FileService.parse, sans l'en-tête « Content as following ») et les lignes de l'ingestion KB
# (PlainParser par défaut) comparées au mode par défaut de pypdf.
_PARSE_IN_CONTAINER = """
import base64, json, sys
from io import BytesIO
from pypdf import PdfReader
from api.db.services.file_service import FileService
from deepdoc.parser.pdf_parser import PlainParser

out = {}
for name, b64 in json.load(sys.stdin).items():
    blob = base64.b64decode(b64)
    attachment = FileService.parse(name + ".pdf", blob, False, tenant_id="eurelis-e2e")
    kb_lines = [line for line, _ in PlainParser()(blob)[0]]
    default_lines = [l for p in PdfReader(BytesIO(blob)).pages for l in p.extract_text().split("\\n")]
    out[name] = {
        "attachment": attachment.split("Content as following: \\n", 1)[-1],
        "kb_unchanged": kb_lines == default_lines,
    }
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def parsed():
    reason = skip_reason()
    if reason:
        pytest.skip(reason)
    pdfs = {"balance": balance_pdf(), "simple": simple_text_pdf(), "scanned": scanned_pdf()}
    payload = json.dumps({k: base64.b64encode(v).decode() for k, v in pdfs.items()})
    # Import de l'API + parsing sous émulation amd64 : large marge.
    return json.loads(docker_py(_PARSE_IN_CONTAINER, stdin=payload, timeout=300).splitlines()[-1])


def _right_edge(line: str, token: str) -> int:
    start = line.index(token)
    return start + len(token)


def _nearest_column(text: str, amount: str) -> str:
    """En-tête de colonne dont le bord droit est le plus proche de celui du montant (montants alignés à droite)."""
    lines = text.split("\n")
    header = next((ln for ln in lines if "Débiteur" in ln and "Créditeur" in ln), None)
    assert header, f"en-têtes Débiteur/Créditeur absents d'une même ligne — colonnes perdues :\n{text}"
    row = next((ln for ln in lines if amount in ln), None)
    assert row, f"montant {amount!r} introuvable :\n{text}"
    edge = _right_edge(row, amount)
    columns = ("Débiteur", "Créditeur", "Sld N-1")
    return min(columns, key=lambda col: abs(_right_edge(header, col) - edge))


@pytest.mark.parametrize("account,label,debit,credit,previous", BALANCE_ROWS)
def test_amounts_stay_under_their_column_header(parsed, account, label, debit, credit, previous):
    """Chaque montant reste aligné sous son en-tête (Débiteur / Créditeur / Sld N-1) et sur la ligne du compte."""
    text = parsed["balance"]["attachment"]
    for amount, column in ((debit, "Débiteur"), (credit, "Créditeur"), (previous, "Sld N-1")):
        if not amount:
            continue
        row = next(ln for ln in text.split("\n") if amount in ln)
        assert account in row, f"{amount!r} détaché de la ligne du compte {account} : {row!r}"
        assert _nearest_column(text, amount) == column, f"{amount!r} ({label}) n'est pas aligné sous « {column} » :\n{text}"


def test_credit_amount_is_under_creditor_header(parsed):
    """Cas du ticket : le capital (créditeur, sans signe) est sous « Créditeur », pas sous « Débiteur »."""
    assert _nearest_column(parsed["balance"]["attachment"], "3 500 000,00") == "Créditeur"


def test_simple_text_pdf_keeps_its_sentences(parsed):
    """Un PDF de texte simple garde ses phrases intactes et dans l'ordre."""
    text = parsed["simple"]["attachment"]
    flat = " ".join(text.split())
    positions = [flat.find(line) for line in SIMPLE_TEXT_LINES]
    assert all(p >= 0 for p in positions), f"phrase manquante :\n{text}"
    assert positions == sorted(positions), f"ordre des phrases altéré :\n{text}"


def test_scanned_pdf_yields_no_text(parsed):
    """Un PDF scanné (sans couche texte) reste sans texte : le repli ne fabrique rien."""
    assert parsed["scanned"]["attachment"].strip() == ""


@pytest.mark.parametrize("name", ["balance", "simple", "scanned"])
def test_knowledge_base_ingestion_is_unchanged(parsed, name):
    """L'ingestion KB (PlainParser par défaut) lit toujours le mode par défaut de pypdf."""
    assert parsed[name]["kb_unchanged"]
