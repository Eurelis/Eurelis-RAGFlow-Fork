# Eurelis — non-régression AILAB-50 : CSV joints lus quel que soit leur encodage et leur séparateur.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# RAGFlowExcelParser lisait les CSV en UTF-8 strict avec la virgule : un export Excel FR (Windows-1252,
# point-virgule) échouait sur « 'utf-8' codec can't decode byte 0xe9 », et décodé il serait sorti en une
# seule colonne. Données synthétiques uniquement.

from io import BytesIO

import pandas as pd
import pytest
from openpyxl import Workbook

from deepdoc.parser.eurelis_csv_text import decode_csv_bytes, detect_csv_delimiter, read_csv_dataframe
from deepdoc.parser.excel_parser import RAGFlowExcelParser
from libs.csv_fixtures import AGED_BALANCE_HEADER, aged_balance_csv


def _assert_balance(df: pd.DataFrame):
    assert list(df.columns) == AGED_BALANCE_HEADER
    assert len(df) == 200
    assert df.iloc[1]["Compte"] == "41100001" and df.iloc[1]["Total"] == "12,50"
    assert not df.isna().any().any()


# --- Décodage -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "blob,encoding",
    [
        ("Libellé;Montant".encode("utf-8"), "utf-8"),
        ("Libellé;Montant".encode("utf-8-sig"), "utf-8-sig"),
        ("Libellé;Montant".encode("utf-16"), "utf-16"),
        ("Libellé;Montant".encode("utf-32"), "utf-32"),
        ("Libellé;Montant".encode("cp1252"), "cp1252"),
    ],
)
def test_decode_detects_encoding(blob, encoding):
    assert decode_csv_bytes(blob) == ("Libellé;Montant", encoding)


def test_decode_cp1252_specific_characters():
    """€ (0x80) et œ (0x9C) n'existent pas en latin-1 : il faut bien cp1252."""
    assert decode_csv_bytes("Cœur;10 €".encode("cp1252")) == ("Cœur;10 €", "cp1252")


def test_decode_falls_back_to_latin1_on_undefined_cp1252_byte():
    """0x81 n'est pas défini en cp1252 : repli latin-1, qui ne lève jamais."""
    text, encoding = decode_csv_bytes(b"Libell\xe9;\x81")
    assert encoding == "latin-1" and text == "Libellé;\x81"


# --- Séparateur ---------------------------------------------------------------------------------


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_delimiter_detected(delimiter):
    assert detect_csv_delimiter(aged_balance_csv("utf-8", delimiter, count=30).decode()) == delimiter


def test_delimiter_ignores_separators_inside_quoted_fields():
    text = 'Compte;Libellé;Total\n0411;"Dupont, Durand; associés";12,50\n0412;"Martin";3,00\n'
    assert detect_csv_delimiter(text) == ";"
    df = read_csv_dataframe(text.encode("cp1252"))
    assert df.iloc[0]["Libellé"] == "Dupont, Durand; associés"


# --- Lecture complète ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "encoding,delimiter,bom",
    [("utf-8", ",", False), ("utf-8", ";", True), ("cp1252", ";", False), ("utf-8", "\t", False)],
)
def test_read_csv_dataframe(encoding, delimiter, bom):
    _assert_balance(read_csv_dataframe(aged_balance_csv(encoding, delimiter, bom=bom)))


def test_read_csv_dataframe_accepts_stream_and_path(tmp_path):
    blob = aged_balance_csv()
    stream = BytesIO(blob)
    stream.read(10)  # flux déjà entamé (détection du type de fichier) : relu depuis le début
    _assert_balance(read_csv_dataframe(stream))
    path = tmp_path / "balance.csv"
    path.write_bytes(blob)
    _assert_balance(read_csv_dataframe(str(path)))


def test_values_kept_as_written():
    df = read_csv_dataframe("Compte;Libellé;Montant;Note\r\n0411;Client A;12,50;\r\n".encode("cp1252"))
    assert df.iloc[0].tolist() == ["0411", "Client A", "12,50", ""]


# --- RAGFlowExcelParser (chemin des pièces jointes et de l'ingestion « naive ») ------------------


def test_parser_reads_french_excel_csv_export():
    """Cas du ticket : CSV cp1252 au point-virgule, accents dans l'en-tête seulement."""
    lines = RAGFlowExcelParser()(aged_balance_csv("cp1252", ";"))
    assert len(lines) == 200
    assert lines[1].startswith("Compte：41100001; Libellé：CLIENT 1 SARL; Total：12,50;")
    assert "Plus de 120 jours：3,10" in lines[1]


def test_parser_html_and_markdown_read_french_excel_csv_export():
    blob = aged_balance_csv("cp1252", ";")
    html = RAGFlowExcelParser().html(blob, 12)[0]
    assert "<th>Libellé</th>" in html and "<th>Plus de 120 jours</th>" in html
    markdown = RAGFlowExcelParser().markdown(blob)
    assert "Libellé" in markdown and "Plus de 120 jours" in markdown


def test_parser_drops_empty_cells_instead_of_nan():
    lines = RAGFlowExcelParser()("Compte,Libellé,Note\n0411,Client A,\n".encode())
    assert lines == ["Compte：0411; Libellé：Client A ——Data"]


def test_xlsx_is_unchanged():
    """Le chemin XLSX ne passe pas par la lecture CSV."""
    wb = Workbook()
    ws = wb.active
    ws.append(["Compte", "Libellé", "Total"])
    ws.append(["0411", "Client A", 12.5])
    buf = BytesIO()
    wb.save(buf)
    assert RAGFlowExcelParser()(buf.getvalue()) == ["Compte：0411; Libellé：Client A; Total：12.5"]
