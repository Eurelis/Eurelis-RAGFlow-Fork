# Eurelis — extraction texte PDF en mode « layout » (colonnes conservées) pour les pièces jointes de chat (AILAB-45).
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

import logging
import re

_BLANK_LINE_RUN = re.compile(r"\n{3,}")


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
