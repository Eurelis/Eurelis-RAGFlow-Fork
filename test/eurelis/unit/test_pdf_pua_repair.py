# Eurelis — non-régression AILAB-26 : chiffres PDF encodés en zone privée Unicode (PUA), réparés via pypdfium2.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Certains PDF comptables (polices Type 3, ToUnicode vers U+E000–U+F8FF, vrai texte en ActualText)
# sortaient de pypdf avec des symboles à la place des montants. On garde le texte aligné de pypdf
# (AILAB-45) et on n'y remplace que les caractères PUA, par une table déduite de pypdfium2.

from io import BytesIO

import pytest
from pypdf import PdfReader

from deepdoc.parser import eurelis_pdf_layout_text as pua
from deepdoc.parser.eurelis_pdf_layout_text import (
    PuaTextRepairer,
    build_pua_map,
    extract_page_text,
    extract_pages_text,
    pua_ratio,
)
from deepdoc.parser.pdf_parser import PlainParser
from libs.pdf_fixtures import BALANCE_ROWS, PUA_GLYPHS, balance_pdf, pua_balance_pdf, simple_text_pdf

ZERO, ONE, TWO, COMMA, MINUS = (PUA_GLYPHS[c] for c in "012,-")


def _encode(text: str) -> str:
    return text.translate(str.maketrans(PUA_GLYPHS))


class _Page:
    """Page pypdf factice : texte du mode par défaut et du mode layout."""

    def __init__(self, default_text, layout_text=None):
        self.default_text, self.layout_text = default_text, layout_text

    def extract_text(self, extraction_mode="plain", **kwargs):
        return self.layout_text if extraction_mode == "layout" else self.default_text


class _Repairer(PuaTextRepairer):
    """Texte pypdfium2 imposé, sans ouvrir de document."""

    def __init__(self, reference=None, error=None):
        super().__init__(source=b"")
        self.reference, self.error, self.calls = reference, error, 0

    def _pdfium_page_text(self, page_index):
        self.calls += 1
        if self.error:
            raise self.error
        return self.reference


# --- Table de correspondance ---------------------------------------------------------------------


def test_pua_ratio_ignores_whitespace():
    assert pua_ratio(f"A{ZERO}      \n   ") == 0.5
    assert pua_ratio("   ") == 0.0


def test_map_is_built_from_aligned_texts():
    mapping = build_pua_map(f"Total {ONE} {TWO}{ZERO}{COMMA}{ZERO}", "Total 1 20,0")
    assert mapping == {ONE: "1", TWO: "2", ZERO: "0", COMMA: ","}


def test_map_ignores_whitespace_differences():
    assert build_pua_map(f"A  {ONE}\n{TWO}", "A 12") == {ONE: "1", TWO: "2"}


def test_map_refuses_different_lengths():
    assert build_pua_map(f"A {ONE}{TWO}", "A 1") is None


def test_map_refuses_ambiguous_glyph():
    assert build_pua_map(f"{ONE}{ONE}", "12") is None


def test_map_refuses_misaligned_texts():
    assert build_pua_map(f"Charges {ONE}", "Produits 1") is None


def test_map_tolerates_rare_non_pua_differences():
    """U+02BC (pypdf) contre U+2019 (pypdfium2) : écart isolé constaté sur les PDF du ticket."""
    assert build_pua_map(f"chiffre dʼaffaires de la société {ONE}", "chiffre d’affaires de la société 1") == {ONE: "1"}


def test_map_skips_glyph_unresolved_by_reference():
    assert build_pua_map(f"{ONE}{TWO}", f"1{TWO}") == {ONE: "1"}


# --- Réparation d'une page -----------------------------------------------------------------------


def test_healthy_page_is_untouched_and_pdfium_not_opened():
    repairer = _Repairer(reference="ne doit pas servir")
    assert repairer.repair("Capital   3 500 000,00", _Page("Capital 3 500 000,00"), 0) == "Capital   3 500 000,00"
    assert repairer.calls == 0


def test_page_below_threshold_is_untouched():
    text = "Rapport annuel de gestion, exercice clos " + MINUS  # 1 caractère PUA sur ~40
    repairer = _Repairer(reference="ne doit pas servir")
    assert repairer.repair(text, _Page(text), 0) == text
    assert repairer.calls == 0


def test_layout_text_keeps_its_alignment():
    layout = f"Capital           {_encode('3 500 000,00')}       {_encode('-3 500 000,00')}"
    page = _Page(default_text=f"Capital\n{_encode('3 500 000,00')}\n{_encode('-3 500 000,00')}", layout_text=layout)
    repaired = _Repairer(reference="Capital 3 500 000,00 -3 500 000,00").repair(layout, page, 0, layout=True)
    assert repaired == "Capital           3 500 000,00       -3 500 000,00"


def test_default_mode_text_is_repaired():
    text = f"Banque {_encode('245 118,84')}"
    assert _Repairer(reference="Banque 245 118,84").repair(text, _Page(text), 0) == "Banque 245 118,84"


def test_raw_pdfium_text_when_alignment_fails():
    text = f"Banque {_encode('245 118,84')}"
    repairer = _Repairer(reference="Banque\n245 118,84 (texte réordonné)")
    assert repairer.repair(text, _Page(text), 0) == "Banque\n245 118,84 (texte réordonné)"
    assert repairer.raw_pages == 1


def test_text_kept_when_pdfium_does_not_help():
    text = _encode("245 118,84")
    assert _Repairer(reference=text).repair(text, _Page(text), 0) == text


def test_text_kept_when_pdfium_raises():
    text = _encode("245 118,84")
    assert _Repairer(error=RuntimeError("pdfium")).repair(text, _Page(text), 0) == text


def test_text_kept_when_source_is_not_a_pdf():
    text = _encode("245 118,84")
    assert PuaTextRepairer(b"pas un PDF").repair(text, _Page(text), 0) == text


# --- PDF synthétique encodé comme ceux du ticket -------------------------------------------------


def test_synthetic_pdf_reproduces_the_defect():
    """Sans correctif, pypdf ne rend aucun chiffre des montants (garde-fou de la fixture)."""
    page = PdfReader(BytesIO(pua_balance_pdf())).pages[0]
    text = extract_page_text(page, layout=True)
    assert pua_ratio(text) > 0.3
    assert "3 500 000,00" not in text


@pytest.mark.parametrize("layout", [True, False])
def test_plain_parser_restores_amounts(layout):
    text = "\n".join(line for line, _ in PlainParser(layout=layout)(pua_balance_pdf())[0])
    assert pua_ratio(text) == 0.0
    for account, _label, *amounts in BALANCE_ROWS:
        assert account in text
        for amount in filter(None, amounts):
            assert amount in text, f"{amount!r} absent :\n{text}"


def test_plain_parser_layout_keeps_amount_on_account_line_and_under_its_column():
    """Non-régression AILAB-45 sur un PDF réparé : montant sur la ligne du compte, sous « Créditeur »."""
    lines = [line for line, _ in PlainParser(layout=True)(pua_balance_pdf())[0]]
    header = next(ln for ln in lines if "Débiteur" in ln and "Créditeur" in ln)
    row = next(ln for ln in lines if "10100000" in ln)
    edge = row.index("3 500 000,00") + len("3 500 000,00")
    columns = {col: header.index(col) + len(col) for col in ("Débiteur", "Créditeur", "Sld N-1")}
    assert min(columns, key=lambda col: abs(columns[col] - edge)) == "Créditeur", "\n".join(lines)


@pytest.mark.parametrize("make_pdf", [balance_pdf, simple_text_pdf])
@pytest.mark.parametrize("layout", [True, False])
def test_healthy_pdfs_are_strictly_unchanged(make_pdf, layout, monkeypatch):
    """PDF sains : texte identique à l'extraction pypdf seule, et pypdfium2 jamais ouvert."""
    monkeypatch.setattr(PuaTextRepairer, "_pdfium_page_text", lambda *a: pytest.fail("pypdfium2 ouvert sur un PDF sain"))
    blob = make_pdf()
    expected = [extract_page_text(p, layout) for p in PdfReader(BytesIO(blob)).pages]
    assert list(extract_pages_text(PdfReader(BytesIO(blob)), blob, layout=layout)) == expected


def test_page_range_targets_the_right_pdfium_page(monkeypatch):
    """L'indice de page transmis à pypdfium2 est absolu (from_page pris en compte)."""
    seen = []
    monkeypatch.setattr(PuaTextRepairer, "_pdfium_page_text", lambda self, index: seen.append(index) or "")
    blob = pua_balance_pdf()
    list(extract_pages_text(PdfReader(BytesIO(blob)), blob, from_page=0, to_page=1))
    assert seen == [0]


def test_pdfium_document_is_closed(monkeypatch):
    closed = []
    original_close = PuaTextRepairer.close
    monkeypatch.setattr(PuaTextRepairer, "close", lambda self: closed.append(self._doc is not None) or original_close(self))
    blob = pua_balance_pdf()
    list(extract_pages_text(PdfReader(BytesIO(blob)), blob))
    assert closed == [True]


def test_lock_is_shared_with_deepdoc():
    import sys

    from deepdoc.parser import pdf_parser

    assert sys.modules[pua._LOCK_KEY_PDFIUM] is sys.modules[pdf_parser.LOCK_KEY_pdfplumber]
