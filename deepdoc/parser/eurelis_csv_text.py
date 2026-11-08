# Eurelis — lecture des CSV quel que soit leur encodage (UTF-8, Windows-1252…) et leur séparateur (AILAB-50).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# RAGFlowExcelParser lisait les CSV par `pd.read_csv(flux)` : UTF-8 strict et virgule. Un export Excel
# FR « CSV (séparateur : point-virgule) » ou d'un logiciel comptable est en Windows-1252 avec `;` : la
# pièce jointe échouait (« 'utf-8' codec can't decode byte 0xe9 », 0xe9 = « é »), et décodée en cp1252
# elle serait sortie en une seule colonne. On corrige l'encodage ET le séparateur.
#
# Pas de chardet (cf. upstream #19253, `rag.nlp.decode_text`) : sur un CSV court et presque tout ASCII
# dont seuls les en-têtes sont accentués, il répond ISO-8859-1 à 0,73 de confiance, sous son seuil de
# 0,8, et l'erreur ne ferait que changer de message. Une cascade stricte suffit : un texte cp1252 n'est
# quasiment jamais de l'UTF-8 valide, et latin-1 ne lève jamais.

import codecs
import csv
import logging
from io import StringIO

import pandas as pd

# BOM → encodage ; UTF-32 avant UTF-16, dont le BOM est un préfixe de celui d'UTF-32 LE.
_BOMS = (
    (codecs.BOM_UTF32_LE, "utf-32"),
    (codecs.BOM_UTF32_BE, "utf-32"),
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)
_FALLBACK_ENCODINGS = ("utf-8", "cp1252")


def decode_csv_bytes(blob: bytes) -> tuple[str, str]:
    """(texte, encodage) : BOM, puis UTF-8 strict, puis cp1252 strict, puis latin-1 (ne lève jamais)."""
    for bom, encoding in _BOMS:
        if blob.startswith(bom):
            try:
                return blob.decode(encoding), encoding
            except UnicodeDecodeError:
                break
    for encoding in _FALLBACK_ENCODINGS:
        try:
            return blob.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return blob.decode("latin-1"), "latin-1"


# --- Détection du séparateur : reprise de l'upstream RAGFlow #19740 (3c8205d89, 2026-09-28),
# `deepdoc/parser/excel_parser.py`, à l'identique. À retirer au profit de l'upstream lors d'une montée
# de version qui l'embarque.

# The separators a spreadsheet actually writes into a file named ".csv". Excel
# writes the list separator of the machine's locale, which is a semicolon across
# most of Europe, and a tab separated export is routinely saved as .csv.
CSV_DELIMITERS = (",", ";", "\t", "|")

# How much of the file the detection looks at. A separator that holds for the
# first rows holds for the file.
CSV_SAMPLE_CHARS = 64 * 1024
CSV_SAMPLE_ROWS = 20


def _consistent_column_count(sample, delimiter, truncated):
    """Columns per row under `delimiter`, or 0 when the rows disagree.

    A separator the file was not written with either does not occur at all (one
    column) or occurs by accident, and then the rows do not line up. Requiring
    the same count on every row is what keeps a comma inside a sentence, or a
    semicolon inside a quoted field, from being read as a separator.

    When `truncated` is set, the sample is a prefix of a longer file, so the row
    it ends in stops wherever the read did, between two fields or inside a
    quoted one. That row is left out rather than counted as having fewer columns,
    also when it is the last of the CSV_SAMPLE_ROWS rows sampled.
    """
    rows = []
    reader = csv.reader(StringIO(sample, newline=""), delimiter=delimiter)
    try:
        for row in reader:
            if any(cell.strip() for cell in row):  # a blank or whitespace-only line says nothing
                rows.append(row)
                if len(rows) == CSV_SAMPLE_ROWS:
                    break
    except csv.Error:
        return 0
    if truncated and len(rows) > 1 and reader.line_num == len(StringIO(sample, newline="").readlines()):
        rows.pop()
    count = 0
    for row in rows:
        if count and len(row) != count:
            return 0
        count = len(row)
    return count if count > 1 else 0


def detect_csv_delimiter(text):
    """The separator `text` was written with, defaulting to a comma.

    `pandas.read_csv` and `csv.reader` both default to a comma, and reading a
    semicolon separated export with one does not fail: it returns a single
    column holding the whole row, separators included.
    """
    truncated = len(text) > CSV_SAMPLE_CHARS
    sample = text[:CSV_SAMPLE_CHARS]
    best_delimiter, best_columns = ",", 0
    for delimiter in CSV_DELIMITERS:
        columns = _consistent_column_count(sample, delimiter, truncated)
        if columns > best_columns:
            best_delimiter, best_columns = delimiter, columns
    return best_delimiter


# --- Fin de la reprise upstream.


def read_csv_dataframe(source) -> pd.DataFrame:
    """DataFrame d'un CSV (chemin, octets ou flux binaire), encodage et séparateur détectés.

    Toutes les cellules sont lues comme du texte, telles qu'écrites : zéros de tête des comptes
    (`0411`), montants à virgule décimale (`12,50`), et cellule vide = chaîne vide (jamais `nan`).
    """
    if isinstance(source, str):
        with open(source, "rb") as f:
            blob = f.read()
    elif isinstance(source, (bytes, bytearray)):
        blob = bytes(source)
    else:
        source.seek(0)
        blob = source.read()
    text, encoding = decode_csv_bytes(blob)
    delimiter = detect_csv_delimiter(text)
    logging.info("csv_read encoding=%s delimiter=%r", encoding, delimiter)
    return pd.read_csv(StringIO(text), sep=delimiter, on_bad_lines="skip", dtype=str, keep_default_na=False)
