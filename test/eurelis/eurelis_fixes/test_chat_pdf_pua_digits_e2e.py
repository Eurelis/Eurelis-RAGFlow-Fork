# Eurelis — P1 (AILAB-26) : les montants des PDF à glyphes PUA (Type 3 + ActualText) sont lus.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Régression gardée : sur les PDF comptables Diligentia (« 3-Heights PDF Optimization API »), les
# polices Type 3 envoient les chiffres vers la zone privée Unicode (U+E000–U+F8FF) et le vrai texte
# n'est porté que par ActualText. pypdf l'ignore : le modèle recevait libellés et symboles illisibles
# à la place des montants (prod Synerga SM-33, 9 729 caractères PUA sur 10 pages).
# Le texte aligné de pypdf (AILAB-45) est conservé, seuls les caractères PUA sont remplacés grâce à
# pypdfium2. Couvre les pièces jointes (FileService.parse) et l'ingestion KB « Naïf » (PlainParser()).
#
# Exécuté DANS le conteneur sous test (docker exec), sur un PDF synthétique (aucune donnée client).

import base64
import json

import pytest

from libs.container import docker_py, skip_reason
from libs.pdf_fixtures import BALANCE_ROWS, balance_pdf, pua_balance_pdf, simple_text_pdf

pytestmark = [pytest.mark.p1]

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
        "kb": "\\n".join(kb_lines),
        "kb_unchanged": kb_lines == default_lines,
    }
print(json.dumps(out))
"""

_AMOUNTS = [amount for _account, _label, *amounts in BALANCE_ROWS for amount in amounts if amount]


def _pua_count(text: str) -> int:
    return sum(0xE000 <= ord(c) <= 0xF8FF for c in text)


@pytest.fixture(scope="module")
def parsed():
    reason = skip_reason()
    if reason:
        pytest.skip(reason)
    pdfs = {"pua_balance": pua_balance_pdf(), "balance": balance_pdf(), "simple": simple_text_pdf()}
    payload = json.dumps({k: base64.b64encode(v).decode() for k, v in pdfs.items()})
    # Import de l'API + parsing sous émulation amd64 : large marge.
    return json.loads(docker_py(_PARSE_IN_CONTAINER, stdin=payload, timeout=300).splitlines()[-1])


def test_attachment_has_no_private_use_characters(parsed):
    text = parsed["pua_balance"]["attachment"]
    assert _pua_count(text) == 0, f"{_pua_count(text)} caractères PUA transmis au modèle :\n{text!r}"


@pytest.mark.parametrize("amount", _AMOUNTS)
def test_attachment_amount_is_readable(parsed, amount):
    assert amount in parsed["pua_balance"]["attachment"], parsed["pua_balance"]["attachment"]


def test_attachment_amount_stays_on_account_line_under_creditor(parsed):
    """Non-régression AILAB-45 sur un PDF réparé : le capital reste sur sa ligne, sous « Créditeur »."""
    lines = parsed["pua_balance"]["attachment"].split("\n")
    header = next(ln for ln in lines if "Débiteur" in ln and "Créditeur" in ln)
    row = next((ln for ln in lines if "3 500 000,00" in ln), None)
    assert row and "10100000" in row, "\n".join(lines)
    edge = row.index("3 500 000,00") + len("3 500 000,00")
    columns = {col: header.index(col) + len(col) for col in ("Débiteur", "Créditeur", "Sld N-1")}
    assert min(columns, key=lambda col: abs(columns[col] - edge)) == "Créditeur", "\n".join(lines)


def test_knowledge_base_plain_parser_reads_amounts(parsed):
    """Ingestion KB « Naïf » (PlainParser par défaut) : même défaut, même correctif."""
    text = parsed["pua_balance"]["kb"]
    assert _pua_count(text) == 0 and all(amount in text for amount in _AMOUNTS), text


@pytest.mark.parametrize("name", ["balance", "simple"])
def test_healthy_pdfs_knowledge_base_ingestion_is_unchanged(parsed, name):
    """PDF sains : PlainParser par défaut lit toujours exactement le mode par défaut de pypdf."""
    assert parsed[name]["kb_unchanged"]
