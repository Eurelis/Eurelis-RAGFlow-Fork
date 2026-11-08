# Eurelis — P1 (AILAB-50) : les CSV joints au chat sont lus quel que soit leur encodage et leur séparateur.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Régression gardée : deux balances âgées jointes en CSV, exportées d'Excel FR (Windows-1252, point-virgule),
# faisaient échouer la conversation (prod Synerga SM-204) :
#   ERROR: Failed to parse CSV and convert to Excel Workbook: 'utf-8' codec can't decode byte 0xe9 …
# RAGFlowExcelParser lisait les CSV en UTF-8 strict avec la virgule. Les mêmes fichiers en XLSX passaient.
#
# Exécuté DANS le conteneur sous test (docker exec), sur des CSV synthétiques (aucune donnée client).

import base64
import json

import pytest

from libs.container import docker_py, skip_reason
from libs.csv_fixtures import AGED_BALANCE_HEADER, aged_balance_csv

pytestmark = [pytest.mark.p1]

# Texte des pièces jointes (FileService.parse, sans l'en-tête « Content as following »), ou l'exception.
_PARSE_IN_CONTAINER = """
import base64, json, sys
from api.db.services.file_service import FileService

out = {}
for name, b64 in json.load(sys.stdin).items():
    try:
        text = FileService.parse(name + ".csv", base64.b64decode(b64), False, tenant_id="eurelis-e2e")
        out[name] = text.split("Content as following: \\n", 1)[-1]
    except Exception as e:
        out[name] = f"ERROR: {e}"
print(json.dumps(out))
"""

CASES = {
    "excel_fr_cp1252_semicolon": aged_balance_csv("cp1252", ";"),
    "utf8_comma": aged_balance_csv("utf-8", ","),
    "utf8_bom_semicolon": aged_balance_csv("utf-8", ";", bom=True),
}


@pytest.fixture(scope="module")
def parsed():
    reason = skip_reason()
    if reason:
        pytest.skip(reason)
    payload = json.dumps({k: base64.b64encode(v).decode() for k, v in CASES.items()})
    # Import de l'API + parsing sous émulation amd64 : large marge.
    return json.loads(docker_py(_PARSE_IN_CONTAINER, stdin=payload, timeout=300).splitlines()[-1])


@pytest.mark.parametrize("name", list(CASES))
def test_csv_attachment_is_parsed_without_error(parsed, name):
    assert "ERROR" not in parsed[name], parsed[name][:500]


@pytest.mark.parametrize("name", list(CASES))
def test_csv_attachment_keeps_its_columns(parsed, name):
    """Chaque colonne est reconnue : en-têtes accentués décodés, montants sous leur en-tête."""
    text = parsed[name]
    for header in AGED_BALANCE_HEADER:
        assert f"{header}：" in text, f"en-tête {header!r} absent :\n{text[:500]}"
    assert "Compte：41100001; Libellé：CLIENT 1 SARL; Total：12,50;" in text, text[:500]
