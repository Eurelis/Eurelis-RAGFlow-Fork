# Eurelis — extraction texte PDF en mode « layout » (colonnes conservées, AILAB-45) et réparation des glyphes PUA (AILAB-26).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# `page.extract_text()` (mode par défaut de pypdf) perd la disposition en colonnes : sur une balance
# comptable, le modèle ne peut plus savoir si un montant est Débiteur, Créditeur ou solde N-1. Le mode
# `layout` aligne le texte avec des espaces. Il ne sert qu'aux pièces jointes (FileService.parse) :
# l'ingestion des bases de connaissances garde le mode par défaut (découpage et index inchangés).
#
# Coût : ×3,3 en caractères mais ~+10 % en tokens (cl100k) sur une balance de 11 pages, les suites
# d'espaces étant peu coûteuses. On retire seulement ce qui ne porte pas l'alignement : espaces en fin
# de ligne et lignes vides en série. Les suites d'espaces internes sont conservées.
#
# AILAB-26 — glyphes en zone privée Unicode (PUA, U+E000 à U+F8FF). Certains producteurs (« 3-Heights
# PDF Optimization API », réimpression PDFium) convertissent les polices en Type 3 dont la table
# ToUnicode envoie les chiffres vers la PUA ; le vrai texte n'est conservé que dans des balises
# `/Span <</ActualText …>> BDC`. pypdf ignore ActualText : les montants sortent en symboles illisibles.
# pypdfium2 (déjà présent, dépendance de pdfplumber) honore ActualText mais perd l'alignement, donc le
# correctif d'AILAB-45. Sur une page atteinte, on garde le texte aligné de pypdf et on n'y remplace que
# les caractères PUA, via une table déduite du document lui-même en alignant, blancs retirés, le texte
# pypdf (mode par défaut) et le texte pypdfium2. Si l'alignement échoue, repli sur le texte brut de
# pypdfium2 (chiffres justes, colonnes perdues). Pages saines : strictement inchangées.

import logging
import re
import sys
import threading
from io import BytesIO

_BLANK_LINE_RUN = re.compile(r"\n{3,}")
_WHITESPACE = re.compile(r"\s+")

# Au-delà de cette proportion de caractères PUA (blancs exclus), la page est jugée atteinte.
PUA_RATIO_THRESHOLD = 0.05
# Écarts tolérés hors PUA entre les deux extracteurs (ex. U+02BC « ʼ » chez pypdf, U+2019 « ’ » chez
# pypdfium2) ; au-delà, les deux textes ne sont pas alignés et la table serait fausse.
_MAX_NON_PUA_MISMATCH = 0.05

# pdfium n'est pas thread-safe : même verrou que les appels pdfplumber/pypdfium2 de deepdoc.
_LOCK_KEY_PDFIUM = "global_shared_lock_pdfplumber"
if _LOCK_KEY_PDFIUM not in sys.modules:
    sys.modules[_LOCK_KEY_PDFIUM] = threading.Lock()


def compact_layout_text(text: str) -> str:
    """Retire les espaces en fin de ligne et ramène les lignes vides consécutives à une seule."""
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANK_LINE_RUN.sub("\n\n", text).strip("\n")


def extract_page_text(page, layout: bool = False) -> str:
    """Texte d'une page pypdf ; en mode layout, repli sur le mode par défaut si erreur ou texte vide."""
    if layout:
        try:
            text = compact_layout_text(page.extract_text(extraction_mode="layout", layout_mode_space_vertically=False))
            if text.strip():
                return text
        except Exception:
            logging.warning("PDF layout text extraction failed, falling back to default mode", exc_info=True)
    return page.extract_text()


def is_pua(char: str) -> bool:
    return 0xE000 <= ord(char) <= 0xF8FF


def pua_ratio(text: str) -> float:
    """Proportion de caractères PUA parmi les caractères non blancs (le mode layout est riche en espaces)."""
    chars = _WHITESPACE.sub("", text or "")
    return sum(map(is_pua, chars)) / len(chars) if chars else 0.0


def build_pua_map(pua_text: str, reference_text: str) -> dict[str, str] | None:
    """Table {caractère PUA: caractère réel} par alignement, blancs retirés, ou None si non alignables.

    Non alignables : longueurs différentes, un même caractère PUA lu de deux façons, ou trop d'écarts
    hors PUA. Un caractère PUA que la référence ne résout pas non plus est laissé tel quel.
    """
    source, reference = _WHITESPACE.sub("", pua_text), _WHITESPACE.sub("", reference_text)
    if len(source) != len(reference):
        return None
    mapping: dict[str, str] = {}
    non_pua = mismatches = 0
    for char, real in zip(source, reference):
        if is_pua(char):
            if not is_pua(real) and mapping.setdefault(char, real) != real:
                return None
        else:
            non_pua += 1
            mismatches += char != real
    if non_pua and mismatches / non_pua > _MAX_NON_PUA_MISMATCH:
        return None
    return mapping


class PuaTextRepairer:
    """Répare, page par page, le texte pypdf dont les glyphes pointent vers la PUA (AILAB-26).

    `source` : chemin ou octets du PDF, ouvert avec pypdfium2 à la première page atteinte seulement.
    """

    def __init__(self, source):
        self._source = source
        self._doc = None
        self.translated_pages = 0
        self.raw_pages = 0

    def repair(self, text: str, page, page_index: int, layout: bool = False) -> str:
        """`text` : texte déjà extrait de `page` (pypdf) ; renvoyé inchangé sous le seuil ou en cas d'erreur."""
        try:
            ratio = pua_ratio(text)
            if ratio <= PUA_RATIO_THRESHOLD:
                return text
            reference = self._pdfium_page_text(page_index)
            default_text = page.extract_text() if layout else text
            mapping = build_pua_map(default_text, reference)
            if mapping:
                self.translated_pages += 1
                return text.translate(str.maketrans(mapping))
            if mapping is None and pua_ratio(reference) < ratio:
                self.raw_pages += 1
                return reference
        except Exception:
            logging.warning("PDF PUA repair failed on page %s, keeping pypdf text", page_index, exc_info=True)
        return text

    def _pdfium_page_text(self, page_index: int) -> str:
        import pypdfium2

        with sys.modules[_LOCK_KEY_PDFIUM]:
            if self._doc is None:
                source = self._source if isinstance(self._source, str) else BytesIO(self._source)
                self._doc = pypdfium2.PdfDocument(source)
            page = self._doc[page_index]
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_range()
            finally:
                textpage.close()
                page.close()
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def close(self):
        if self._doc is not None:
            with sys.modules[_LOCK_KEY_PDFIUM]:
                self._doc.close()
            self._doc = None
        if self.translated_pages or self.raw_pages:
            logging.info("pdf_pua_repaired pages_translated=%d pages_raw=%d", self.translated_pages, self.raw_pages)


def extract_pages_text(pdf, source, from_page: int = 0, to_page: int | None = None, layout: bool = False):
    """Textes des pages [from_page:to_page] d'un PdfReader pypdf, glyphes PUA réparés (AILAB-26).

    `source` : chemin ou octets du même PDF, pour pypdfium2.
    """
    repairer = PuaTextRepairer(source)
    try:
        for index, page in enumerate(pdf.pages[from_page:to_page], start=from_page):
            yield repairer.repair(extract_page_text(page, layout), page, index, layout)
    finally:
        repairer.close()
