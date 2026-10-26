# Eurelis — non-régression AILAB-45 : extraction PDF en mode layout (pièces jointes) et son repli.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Le mode layout de pypdf garde les colonnes d'un PDF tabulaire (balance comptable). S'il lève ou
# renvoie un texte vide, on retombe sur le mode par défaut ; la compaction ne touche jamais aux
# suites d'espaces internes qui portent l'alignement.

from io import BytesIO

from pypdf import PdfReader

from deepdoc.parser.eurelis_pdf_layout_text import compact_layout_text, extract_page_text
from deepdoc.parser.pdf_parser import PlainParser
from libs.pdf_fixtures import balance_pdf


class _FakePage:
    def __init__(self, layout_text=None, layout_error=None, default_text="texte par défaut"):
        self.layout_text, self.layout_error, self.default_text = layout_text, layout_error, default_text

    def extract_text(self, extraction_mode="plain", **kwargs):
        if extraction_mode != "layout":
            return self.default_text
        if self.layout_error:
            raise self.layout_error
        return self.layout_text


def test_compaction_keeps_internal_spaces():
    text = "Compte   Débiteur     Créditeur   \n\n\n\n101                  3 500,00  \n"
    assert compact_layout_text(text) == "Compte   Débiteur     Créditeur\n\n101                  3 500,00"


def test_layout_mode_is_used_when_requested():
    assert extract_page_text(_FakePage(layout_text="A      B"), layout=True) == "A      B"


def test_default_mode_without_layout_flag():
    assert extract_page_text(_FakePage(layout_text="A      B"), layout=False) == "texte par défaut"


def test_fallback_when_layout_raises():
    page = _FakePage(layout_error=ValueError("pypdf layout"))
    assert extract_page_text(page, layout=True) == "texte par défaut"


def test_fallback_when_layout_is_blank():
    assert extract_page_text(_FakePage(layout_text="   \n  \n"), layout=True) == "texte par défaut"


def test_plain_parser_default_is_unchanged_for_knowledge_bases():
    """PlainParser() sans option (ingestion KB) renvoie exactement le mode par défaut de pypdf."""
    blob = balance_pdf()
    expected = [line for page in PdfReader(BytesIO(blob)).pages for line in page.extract_text().split("\n")]
    assert [line for line, _ in PlainParser()(blob)[0]] == expected


def test_plain_parser_layout_keeps_amount_on_account_line():
    blob = balance_pdf()
    lines = [line for line, _ in PlainParser(layout=True)(blob)[0]]
    assert any("10100000" in line and "3 500 000,00" in line for line in lines), lines
