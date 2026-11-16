# Eurelis — AILAB-52 : PDF scannés joints au chat ou à un agent, pages transmises au LLM en images.
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Sans stack : `FileService.get_blob` lit un dictionnaire et `FileService.parse` est remplacé par la
# même lecture PlainParser (mode layout) sans l'import de rag.app, qui exige Elasticsearch. L'identité
# au caractère près avec le vrai `FileService.parse` est vérifiée dans le conteneur (e2e).

import asyncio
import base64
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from api.db.services import eurelis_scanned_pdf as scans
from api.db.services.dialog_service import convert_last_user_msg_to_multimodal, split_file_attachments
from api.db.services.file_service import FileService
from deepdoc.parser.pdf_parser import PlainParser
from libs.pdf_fixtures import (
    SIMPLE_TEXT_LINES,
    balance_pdf,
    mixed_pdf,
    pua_balance_pdf,
    scan_pdf,
    simple_text_pdf,
    text_over_background_pdf,
)
from rag.llm.eurelis_history_log import history_for_log, truncate_data_uris

MAX_PAGE = 100000000


@pytest.fixture
def store(monkeypatch):
    """Pièces jointes en mémoire et lecture texte « actuelle » sans Elasticsearch."""
    blobs: dict[str, bytes] = {}
    calls: list[tuple] = []

    def get_blob(user_id, location):
        return blobs[location]

    def parse(filename, blob, img_base64=True, tenant_id=None, layout_recognize=None, from_page=0, to_page=MAX_PAGE):
        calls.append((filename, from_page, to_page))
        lines = [line for line, _ in PlainParser(layout=True)(blob, from_page, to_page)[0]]
        return scans.HEADER.format(name=filename) + "\n".join(lines)

    monkeypatch.setattr(FileService, "get_blob", staticmethod(get_blob))
    monkeypatch.setattr(FileService, "parse", staticmethod(parse))
    monkeypatch.delenv(scans.ENV_MAX_PAGES, raising=False)

    def add(name: str, blob: bytes, mime: str = "application/pdf") -> dict:
        blobs[name] = blob
        return {"id": name, "name": name, "mime_type": mime, "created_by": "user-1"}

    return SimpleNamespace(add=add, calls=calls, parse=parse)


def _jpeg(entry) -> Image.Image:
    raw = entry if isinstance(entry, bytes) else base64.b64decode(entry.split(",", 1)[1])
    return Image.open(BytesIO(raw))


# --- Détection -----------------------------------------------------------------------------------


@pytest.mark.parametrize("pdf", [balance_pdf, simple_text_pdf, pua_balance_pdf, text_over_background_pdf])
def test_text_pdfs_are_not_scans(pdf):
    """Non-régression AILAB-26 / AILAB-45 et papier à en-tête : aucune page prise pour un scan."""
    assert scans.analyse_pdf(pdf()).scan_pages == []


def test_full_page_scan():
    page = scans.analyse_pdf(scan_pdf()).pages[0]
    assert page.scanned and page.chars == 0 and page.image_coverage >= 0.99


def test_scan_in_bands_cumulates_image_surface():
    """101 bandes pleine largeur (lettre « observations ») : la surface se cumule, pas d'image unique."""
    page = scans.analyse_pdf(scan_pdf(bands=101)).pages[0]
    assert page.scanned and page.image_coverage >= 0.99


def test_scan_with_invisible_ocr_layer():
    """Couche OCR de copieur (mode de rendu 3) : du texte existe mais il est invisible → scan."""
    page = scans.analyse_pdf(scan_pdf(invisible_text=True)).pages[0]
    assert page.chars >= scans.MIN_TEXT_CHARS and page.visible_chars == 0 and page.scanned


def test_scan_with_text_under_the_image():
    """Texte OCR peint avant l'image qui le recouvre : invisible à l'œil → scan."""
    page = scans.analyse_pdf(scan_pdf(text_under_image=True)).pages[0]
    assert page.chars >= scans.MIN_TEXT_CHARS and page.visible_chars == 0 and page.scanned


def test_mixed_pdf_detects_only_the_scanned_page():
    assert scans.analyse_pdf(mixed_pdf()).scan_pages == [1]


def test_render_jpeg_long_side_capped():
    jpegs = scans.render_pages(scan_pdf(pages=2), [0, 1])
    assert len(jpegs) == 2
    for jpeg in jpegs:
        image = Image.open(BytesIO(jpeg))
        assert image.format == "JPEG" and max(image.size) <= scans.MAX_LONG_SIDE
        assert max(image.size) == scans.MAX_LONG_SIDE  # A4 à 150 dpi = 1754 px, ramené à 1568


def test_format_pages():
    assert scans.format_pages([0, 1, 2, 4, 6, 7]) == "1 à 3, 5, 7 et 8"


# --- Lecture des pièces jointes ------------------------------------------------------------------


@pytest.mark.parametrize("pdf", [balance_pdf, simple_text_pdf, pua_balance_pdf, text_over_background_pdf])
def test_text_pdf_reading_is_identical(store, pdf):
    """PDF sans page scannée : exactement la lecture actuelle, d'un seul appel, sans image."""
    file = store.add("doc.pdf", pdf())
    assert FileService.get_files([file]) == [store.parse("doc.pdf", pdf())]
    assert store.calls[0][1:] == (0, MAX_PAGE)


def test_full_scan_sends_pages_as_images(store):
    files = [store.add("lettre.pdf", scan_pdf(pages=4))]
    entries = FileService.get_files(files)
    text, images = entries[0], entries[1:]
    assert "lettre.pdf : document scanné, 4 pages transmises en images" in text
    assert len(images) == 4 and all(i.startswith("data:image/jpeg;base64,") for i in images)
    assert _jpeg(images[0]).format == "JPEG"


@pytest.mark.parametrize("variant", [{"bands": 101}, {"invisible_text": True}, {"text_under_image": True}])
def test_scan_variants_send_images_and_no_ocr_text(store, variant):
    files = [store.add("scan.pdf", scan_pdf(**variant))]
    entries = FileService.get_files(files)
    assert len(entries) == 2 and entries[1].startswith("data:image/jpeg")
    assert "Montant du redressement" not in entries[0]  # la couche OCR (douteuse) n'est pas transmise


def test_mixed_pdf_keeps_text_pages_and_sends_the_scanned_one(store):
    files = [store.add("mixte.pdf", mixed_pdf())]
    text, *images = FileService.get_files(files)
    assert len(images) == 1
    assert "PDF mixte, 1 page scannée sur 3 (page 2)" in text
    assert "[mixte.pdf, page 2 : page scannée, transmise en image]" in text
    for page in (1, 3):
        assert f"{SIMPLE_TEXT_LINES[0]} (page {page})" in text
    assert text.index("(page 1)") < text.index("page 2 : page scannée") < text.index("(page 3)")
    assert [c[1:] for c in store.calls] == [(0, 1), (2, 3)]  # pages texte relues par la lecture actuelle


def test_cap_counts_pages_across_the_whole_request(store, monkeypatch):
    """Plafond sur toute la requête : premières pages seulement, et le prompt le dit."""
    monkeypatch.setenv(scans.ENV_MAX_PAGES, "5")
    files = [store.add("a.pdf", scan_pdf(pages=3)), store.add("b.pdf", scan_pdf(pages=4)), store.add("c.pdf", scan_pdf(pages=2))]
    entries = FileService.get_files(files)
    texts = [e for e in entries if not e.startswith("data:")]
    assert len(entries) - len(texts) == 5
    assert entries[1:4] == [e for e in entries[1:4] if e.startswith("data:")]  # a.pdf : 3 pages
    assert "a.pdf : document scanné, 3 pages transmises en images" in texts[0] and "ATTENTION" not in texts[0]
    assert "b.pdf : document scanné, 2 pages transmises en images" in texts[1]
    assert "les pages 3 et 4 de b.pdf n'ont pas été lues" in texts[1] and "Préviens l'utilisateur" in texts[1]
    assert "c.pdf : document scanné de 2 pages, aucune page transmise en image" in texts[2]
    assert "les pages 1 et 2 de c.pdf n'ont pas été lues" in texts[2]


def test_cap_marks_unread_pages_in_mixed_pdf(store, monkeypatch):
    monkeypatch.setenv(scans.ENV_MAX_PAGES, "1")
    files = [store.add("a.pdf", scan_pdf()), store.add("mixte.pdf", mixed_pdf())]
    entries = FileService.get_files(files)
    assert sum(e.startswith("data:") for e in entries) == 1
    assert "[mixte.pdf, page 2 : page scannée, NON LUE (plafond de pages en images atteint)]" in entries[2]
    assert "la page 2 de mixte.pdf n'a pas été lue" in entries[2]


def test_cap_zero_disables_the_feature(store, monkeypatch):
    monkeypatch.setenv(scans.ENV_MAX_PAGES, "0")
    blob = scan_pdf()
    assert FileService.get_files([store.add("s.pdf", blob)]) == [store.parse("s.pdf", blob)]


def test_model_without_vision_keeps_text_reading(store):
    """Repli : lecture texte actuelle, sans image, et une phrase pour que le modèle prévienne."""
    blob = scan_pdf(pages=2)
    entries = FileService.get_files([store.add("s.pdf", blob)], vision=False)
    assert len(entries) == 1 and entries[0].startswith(store.parse("s.pdf", blob))
    assert "s.pdf : 2 pages scannées sans texte (pages 1 et 2) non lues : le modèle utilisé ne lit pas les images" in entries[0]


def test_render_failure_falls_back_to_text(store, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("pdfium")

    monkeypatch.setattr(scans, "render_pages", boom)
    blob = scan_pdf()
    assert FileService.get_files([store.add("s.pdf", blob)]) == [store.parse("s.pdf", blob)]


def test_images_and_text_files_keep_their_order(store):
    png = BytesIO()
    Image.new("RGB", (10, 10)).save(png, format="PNG")
    files = [store.add("photo.png", png.getvalue(), "image/png"), store.add("scan.pdf", scan_pdf()), store.add("doc.pdf", simple_text_pdf())]
    entries = FileService.get_files(files)
    assert entries[0].startswith("data:image/png;base64,")
    assert "scan.pdf : document scanné" in entries[1] and entries[2].startswith("data:image/jpeg")
    assert "File: doc.pdf" in entries[3] and len(entries) == 4


def test_raw_mode_returns_jpeg_bytes(store):
    """Dialogs avec un modèle image2text (mode raw) : pages en octets JPEG, comme les images jointes."""
    texts, images = FileService.get_files([store.add("s.pdf", scan_pdf(pages=2))], raw=True)
    assert len(texts) == 1 and "2 pages transmises en images" in texts[0]
    assert len(images) == 2 and all(isinstance(i, bytes) and _jpeg(i).format == "JPEG" for i in images)


# --- Chemin assistant ----------------------------------------------------------------------------


def test_assistant_path_sends_pages_to_the_llm(store):
    text_attachments, image_attachments = split_file_attachments([store.add("s.pdf", scan_pdf(pages=2))])
    assert len(text_attachments) == 1 and len(image_attachments) == 2
    msg = [{"role": "user", "content": "Résume la lettre." + "\n\n".join(text_attachments)}]
    convert_last_user_msg_to_multimodal(msg, image_attachments, "Bedrock")
    blocks = msg[0]["content"]
    assert blocks[0]["type"] == "text" and "s.pdf : document scanné" in blocks[0]["text"]
    assert [b["type"] for b in blocks[1:]] == ["image_url", "image_url"]


def test_assistant_path_without_vision(store):
    text_attachments, image_attachments = split_file_attachments([store.add("s.pdf", scan_pdf())], vision=False)
    assert image_attachments == [] and "ne lit pas les images" in text_attachments[0]


# --- Chemin agent --------------------------------------------------------------------------------


class _Canvas:
    """Canvas minimal : pool de threads et composants LLM du DSL."""

    def __init__(self, llm_ids):
        from agent.component.llm import LLM

        self._thread_pool = ThreadPoolExecutor(max_workers=2)
        self.components = {}
        for k, llm_id in enumerate(llm_ids):
            obj = LLM.__new__(LLM)
            obj._param = SimpleNamespace(llm_id=llm_id)
            self.components[f"llm{k}"] = {"obj": obj}

    def get_model_tenant_id(self):
        return "tenant-1"


def _agent_llm_split(sys_files):
    from agent.component.llm import LLM

    llm = LLM.__new__(LLM)
    llm._canvas = SimpleNamespace(globals={"sys.files": sys_files})
    llm._param = SimpleNamespace(sys_prompt="Tu es un assistant.", prompts=[{"role": "user", "content": "{sys.query}"}])
    return llm._collect_sys_files()


def test_agent_path_sends_pages_to_the_llm(store, monkeypatch):
    from agent.canvas import Canvas

    monkeypatch.setattr(scans, "model_reads_images", lambda tenant_id, llm_id: llm_id.startswith("claude"))
    canvas = _Canvas(["claude-opus-4-8@Bedrock"])
    sys_files = asyncio.run(Canvas.get_files_async(canvas, [store.add("s.pdf", scan_pdf(pages=3))]))
    texts, images = _agent_llm_split(sys_files)
    assert len(texts) == 1 and "s.pdf : document scanné, 3 pages transmises en images" in texts[0]
    assert len(images) == 3 and all(i.startswith("data:image/jpeg;base64,") for i in images)


def test_agent_path_without_vision_model(store, monkeypatch):
    from agent.canvas import Canvas

    monkeypatch.setattr(scans, "model_reads_images", lambda tenant_id, llm_id: False)
    sys_files = asyncio.run(Canvas.get_files_async(_Canvas(["deepseek-chat@DeepSeek"]), [store.add("s.pdf", scan_pdf())]))
    texts, images = _agent_llm_split(sys_files)
    assert images == [] and "ne lit pas les images" in texts[0]


# --- Le modèle lit-il les images ? ---------------------------------------------------------------


@pytest.mark.parametrize(
    "llm_id,expected",
    [
        ("eu.anthropic.claude-opus-4-8@Bedrock", True),
        ("claude-sonnet-4-6@Anthropic", True),
        ("gpt-4o@OpenAI", True),
        ("gpt-4.1-mini@OpenAI", True),
        ("gemini-2.5-pro@Gemini", True),
        ("qwen2.5-vl:7b@Ollama", True),
        ("deepseek-chat@DeepSeek", False),
        ("mistral-large-latest@Mistral", False),
        ("qwen3:8b@Ollama", False),
        ("", False),
    ],
)
def test_model_reads_images_by_name(monkeypatch, llm_id, expected):
    def no_types(tenant_id, name):
        raise LookupError("not registered")

    monkeypatch.setattr("api.db.joint_services.tenant_model_service.get_model_type_by_name", no_types)
    assert scans.model_reads_images("tenant-1", llm_id) is expected


def test_model_registered_as_image2text_reads_images(monkeypatch):
    monkeypatch.setattr("api.db.joint_services.tenant_model_service.get_model_type_by_name", lambda t, n: ["chat", "image2text"])
    assert scans.model_reads_images("tenant-1", "mon-modele-maison@OpenAI-API-Compatible")


def test_canvas_reads_images_if_any_llm_component_does(monkeypatch):
    monkeypatch.setattr(scans, "model_reads_images", lambda tenant_id, llm_id: llm_id == "vision")
    assert scans.canvas_reads_images(_Canvas(["texte", "vision"]))
    assert not scans.canvas_reads_images(_Canvas(["texte"]))
    assert not scans.canvas_reads_images(_Canvas([]))


# --- Journaux ------------------------------------------------------------------------------------


def _history_with_images():
    uri = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8" + b"x" * 300_000).decode()
    return [
        {"role": "system", "content": "Tu es un assistant."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Résume la lettre jointe."},
                {"type": "image_url", "image_url": {"url": uri}},
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": uri.split(",", 1)[1]}},
            ],
        },
    ], uri


def test_history_log_truncates_images():
    history, uri = _history_with_images()
    logged = history_for_log(history, indent=2)
    assert len(logged) < 2000 and uri not in logged
    assert "Résume la lettre jointe." in logged and "base64 tronqué" in logged
    assert history[1]["content"][1]["image_url"]["url"] == uri  # l'historique envoyé n'est pas modifié


def test_history_log_keeps_long_text():
    text = "Le budget est validé. " * 500
    assert truncate_data_uris({"content": text}) == {"content": text}


def test_litellm_history_log_is_truncated(monkeypatch, caplog):
    """`LiteLLMBase.async_chat` journalise `[HISTORY]` sans les base64."""
    import litellm

    from rag.llm.chat_model import LiteLLMBase

    async def stop(**kwargs):
        raise RuntimeError("stop after logging")

    monkeypatch.setattr(litellm, "acompletion", stop)
    mdl = LiteLLMBase.__new__(LiteLLMBase)
    mdl.model_name, mdl.provider, mdl.prefix, mdl.api_key, mdl.base_url = "eu.anthropic.claude-opus-4-8", "Bedrock", "bedrock/", "{}", None
    mdl.max_retries, mdl.base_delay, mdl.timeout, mdl.toolcall_sessions, mdl.tools, mdl.is_tools = 0, 0, 1, {}, [], False
    history, uri = _history_with_images()
    with caplog.at_level(logging.INFO):
        try:
            asyncio.run(mdl.async_chat("Système", history[1:], {}))
        except Exception:
            pass
    logs = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[HISTORY]")]
    assert logs, "aucun log [HISTORY]"
    assert all(uri[30:200] not in line and len(line) < 5000 for line in logs)
    assert "base64 tronqué" in logs[0] and json.loads(logs[0][len("[HISTORY]") :])
