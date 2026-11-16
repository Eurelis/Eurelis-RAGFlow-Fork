# Eurelis — P1 (AILAB-52) : les PDF scannés joints au chat ou à un agent partent au LLM en images.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Régression gardée : sur un scan sans couche texte, le modèle ne recevait que « File: x.pdf Content as
# following: » (prod Synerga SM-298, lettres URSSAF). Les pages sans texte sont désormais rendues en
# JPEG et jointes comme des images, pour les assistants (`split_file_attachments`) et les agents
# (`Canvas.get_files_async` → `sys.files`). Les PDF texte gardent leur lecture au caractère près
# (AILAB-26, AILAB-45).
#
# Exécuté DANS le conteneur sous test (docker exec), avec le vrai `FileService.parse` de l'image, sur
# des PDF synthétiques (aucune donnée client) ; seul `FileService.get_blob` lit un dictionnaire.

import base64
import json

import pytest

from libs.container import docker_py, skip_reason
from libs.pdf_fixtures import SIMPLE_TEXT_LINES, balance_pdf, mixed_pdf, pua_balance_pdf, scan_pdf, simple_text_pdf

pytestmark = [pytest.mark.p1]

_RUN_IN_CONTAINER = """
import asyncio, base64, json, sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from api.db.services.file_service import FileService
from api.db.services import eurelis_scanned_pdf as scans
from api.db.services.dialog_service import split_file_attachments
from agent.canvas import Canvas
from agent.component.llm import LLM
from rag.llm.eurelis_history_log import history_for_log

blobs = {k: base64.b64decode(v) for k, v in json.load(sys.stdin).items()}
FileService.get_blob = staticmethod(lambda user_id, location: blobs[location])

def file(name):
    return {"id": name, "name": name + ".pdf", "mime_type": "application/pdf", "created_by": "eurelis-e2e"}

def summary(entries):
    return {
        "texts": [e for e in entries if not e.startswith("data:")],
        "images": [len(e) for e in entries if e.startswith("data:image/jpeg;base64,")],
    }

out = {}
for name in ("balance", "simple", "pua_balance"):
    out[name] = {
        "get_files": FileService.get_files([file(name)]),
        "parse": FileService.parse(name + ".pdf", blobs[name], True, "eurelis-e2e"),
    }
for name in ("scan", "bands", "invisible", "under", "mixed"):
    out[name] = summary(FileService.get_files([file(name)]))

texts, images = split_file_attachments([file("scan"), file("mixed")])
out["assistant"] = {"texts": texts, "images": len(images)}
texts, images = split_file_attachments([file("scan")], vision=False)
out["assistant_no_vision"] = {"texts": texts, "images": len(images)}

llm = LLM.__new__(LLM)
llm._param = SimpleNamespace(llm_id="eu.anthropic.claude-opus-4-8@Bedrock")
canvas = SimpleNamespace(_thread_pool=ThreadPoolExecutor(2), components={"llm": {"obj": llm}}, get_model_tenant_id=lambda: "eurelis-e2e")
sys_files = asyncio.run(Canvas.get_files_async(canvas, [file("scan")]))
reader = LLM.__new__(LLM)
reader._canvas = SimpleNamespace(globals={"sys.files": sys_files})
reader._param = SimpleNamespace(sys_prompt="", prompts=[])
texts, images = reader._collect_sys_files()
out["agent"] = {"texts": texts, "images": len(images)}

uri = "data:image/jpeg;base64," + "A" * 300000
out["log"] = history_for_log([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": uri}}]}], indent=2)

import os
os.environ[scans.ENV_MAX_PAGES] = "3"
out["capped"] = summary(FileService.get_files([file("scan4"), file("scan")]))
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def result():
    reason = skip_reason()
    if reason:
        pytest.skip(reason)
    pdfs = {
        "balance": balance_pdf(),
        "simple": simple_text_pdf(),
        "pua_balance": pua_balance_pdf(),
        "scan": scan_pdf(pages=2),
        "scan4": scan_pdf(pages=4),
        "bands": scan_pdf(bands=101),
        "invisible": scan_pdf(invisible_text=True),
        "under": scan_pdf(text_under_image=True),
        "mixed": mixed_pdf(),
    }
    payload = json.dumps({k: base64.b64encode(v).decode() for k, v in pdfs.items()})
    # Import de l'API + parsing et rendu sous émulation amd64 : large marge.
    return json.loads(docker_py(_RUN_IN_CONTAINER, stdin=payload, timeout=600).splitlines()[-1])


@pytest.mark.parametrize("name", ["balance", "simple", "pua_balance"])
def test_text_pdfs_are_read_exactly_as_before(result, name):
    """Non-régression AILAB-26 / AILAB-45 : aucune image, texte identique au caractère près."""
    assert result[name]["get_files"] == [result[name]["parse"]]


def test_full_page_scan(result):
    assert len(result["scan"]["images"]) == 2
    assert "scan.pdf : document scanné, 2 pages transmises en images" in result["scan"]["texts"][0]


@pytest.mark.parametrize("name", ["bands", "invisible", "under"])
def test_scan_variants(result, name):
    """Scan en 101 bandes, couche OCR invisible, texte sous l'image : une page en image."""
    assert len(result[name]["images"]) == 1, result[name]
    assert "document scanné, 1 page transmise en image" in result[name]["texts"][0]


def test_mixed_pdf(result):
    text = result["mixed"]["texts"][0]
    assert len(result["mixed"]["images"]) == 1
    assert "[mixed.pdf, page 2 : page scannée, transmise en image]" in text
    assert all(f"(page {p})" in text for p in (1, 3)) and SIMPLE_TEXT_LINES[0] in text


def test_cap_over_the_request_is_announced(result):
    texts = result["capped"]["texts"]
    assert len(result["capped"]["images"]) == 3
    assert "scan4.pdf : document scanné, 3 pages transmises en images" in texts[0]
    assert "la page 4 de scan4.pdf n'a pas été lue" in texts[0]
    assert "les pages 1 et 2 de scan.pdf n'ont pas été lues" in texts[1]


def test_assistant_path(result):
    assert result["assistant"]["images"] == 3 and len(result["assistant"]["texts"]) == 2


def test_assistant_path_without_vision(result):
    assert result["assistant_no_vision"]["images"] == 0
    assert "ne lit pas les images" in result["assistant_no_vision"]["texts"][0]


def test_agent_path(result):
    assert result["agent"]["images"] == 2
    assert "scan.pdf : document scanné, 2 pages transmises en images" in result["agent"]["texts"][0]


def test_history_log_is_truncated(result):
    assert len(result["log"]) < 1000 and "base64 tronqué" in result["log"]
