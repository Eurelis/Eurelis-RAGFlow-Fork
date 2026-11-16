# Eurelis — PDF scannés joints au chat ou à un agent : les pages sans texte partent au LLM en images (AILAB-52).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Les PDF joints sont lus en « Plain Text » (PlainParser, pypdf) : sur un scan sans couche texte, le
# modèle ne recevait que « File: x.pdf Content as following: » et rien d'autre. Les images jointes,
# elles, partent déjà au LLM (data URI) dans les deux chemins : assistants (`split_file_attachments` →
# `convert_last_user_msg_to_multimodal`) et agents (`sys.files` → composant LLM). On réutilise ce
# canal : les pages scannées sont rendues en JPEG et ajoutées comme des images jointes.
#
# - Détection page par page : moins de MIN_TEXT_CHARS caractères visibles → page scannée. Texte
#   « visible » : hors mode de rendu invisible (couche OCR de copieur) et hors texte recouvert par une
#   image peinte après lui. La surface d'image se cumule sur la page (scans livrés en bandes).
# - PDF sans page scannée : lecture actuelle strictement inchangée (`FileService.parse`, AILAB-26/45).
# - PDF mixte : les pages texte gardent la lecture actuelle, les pages scannées partent en images.
# - Plafond de pages en images sur toute la requête (le Shield renvoie toutes les PJ de la session à
#   chaque tour) ; au-delà, les premières pages seulement, et le prompt le dit.
# - Modèle sans vision : lecture texte actuelle, plus une phrase qui signale les pages non lues.
# - Toute erreur d'analyse ou de rendu : lecture texte actuelle (jamais d'échec de la conversation).

import base64
import ctypes
import logging
import math
import os
import re
import sys
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from io import BytesIO

ENV_MAX_PAGES = "EURELIS_ATTACHMENT_SCAN_MAX_PAGES"
DEFAULT_MAX_PAGES = 20

# En dessous de ce nombre de caractères visibles (blancs exclus), la page est traitée comme scannée.
MIN_TEXT_CHARS = 50
# Part de la page couverte par des images au-delà de laquelle on cherche du texte caché sous l'image.
HIDDEN_TEXT_MIN_COVERAGE = 0.5
_COVERAGE_GRID = 100  # maillage de calcul de la surface d'image (union, pas somme)

RENDER_DPI = 150
MAX_LONG_SIDE = 1568  # au-delà, Claude redimensionne lui-même : autant ne pas transmettre plus
JPEG_QUALITY = 85

HEADER = "\n -----------------\nFile: {name}\nContent as following: \n"

# pdfium n'est pas thread-safe : même verrou que deepdoc et la réparation PUA (AILAB-26).
_LOCK_KEY_PDFIUM = "global_shared_lock_pdfplumber"
if _LOCK_KEY_PDFIUM not in sys.modules:
    sys.modules[_LOCK_KEY_PDFIUM] = threading.Lock()


def _pdfium_lock():
    return sys.modules[_LOCK_KEY_PDFIUM]


def max_scan_pages() -> int:
    """Plafond de pages en images par requête ; 0 désactive la fonction (lecture texte seule)."""
    raw = os.environ.get(ENV_MAX_PAGES, "").strip()
    if not raw:
        return DEFAULT_MAX_PAGES
    try:
        return max(0, int(raw))
    except ValueError:
        logging.warning("%s=%r invalide, valeur par défaut %d", ENV_MAX_PAGES, raw, DEFAULT_MAX_PAGES)
        return DEFAULT_MAX_PAGES


# --- Analyse ------------------------------------------------------------------------------------


@dataclass
class PageInfo:
    index: int
    chars: int  # caractères non blancs examinés (décompte arrêté dès MIN_TEXT_CHARS caractères visibles)
    visible_chars: int  # plafonné à MIN_TEXT_CHARS
    image_coverage: float
    has_graphics: bool  # image, tracé ou dégradé : la page n'est pas vide

    @property
    def scanned(self) -> bool:
        return self.visible_chars < MIN_TEXT_CHARS and self.has_graphics


@dataclass
class PdfAnalysis:
    pages: list[PageInfo] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def scan_pages(self) -> list[int]:
        return [p.index for p in self.pages if p.scanned]


def _address(handle) -> int:
    return ctypes.cast(handle, ctypes.c_void_p).value or 0


def _coverage(rects, page_box) -> float:
    """Part de la page couverte par l'union des rectangles (images en bandes : pas de double compte)."""
    if not rects:
        return 0.0
    x0, y0, x1, y1 = page_box
    width, height = max(x1 - x0, 1e-6), max(y1 - y0, 1e-6)
    n = _COVERAGE_GRID
    grid = bytearray(n * n)
    for left, bottom, right, top in rects:
        c0 = max(0, math.floor((left - x0) / width * n))
        c1 = min(n, math.ceil((right - x0) / width * n))
        r0 = max(0, math.floor((bottom - y0) / height * n))
        r1 = min(n, math.ceil((top - y0) / height * n))
        for row in range(r0, r1):
            grid[row * n + c0 : row * n + c1] = b"\x01" * max(0, c1 - c0)
    return sum(grid) / (n * n)


def _contains(rect, x, y) -> bool:
    left, bottom, right, top = rect
    return left <= x <= right and bottom <= y <= top


def _analyse_page(page, index: int) -> PageInfo:
    import pypdfium2.raw as pdfium_c

    # Ordre de peinture (parcours en profondeur) et rectangles des images en coordonnées de page.
    # Les objets imbriqués dans un XObject de formulaire ont leurs bornes dans l'espace du formulaire :
    # on prend alors celles du formulaire de premier niveau qui les contient.
    z_order: dict[int, int] = {}
    images: list[tuple[int, tuple]] = []
    has_graphics = False
    top_bounds = None
    for z, obj in enumerate(page.get_objects()):
        z_order[_address(obj.raw)] = z
        if obj.level == 0:
            try:
                top_bounds = obj.get_bounds()
            except Exception:
                top_bounds = None
        if obj.type == pdfium_c.FPDF_PAGEOBJ_IMAGE:
            has_graphics = True
            try:
                bounds = obj.get_bounds() if obj.level == 0 else top_bounds
            except Exception:
                bounds = None
            if bounds:
                images.append((z, bounds))
        elif obj.type in (pdfium_c.FPDF_PAGEOBJ_PATH, pdfium_c.FPDF_PAGEOBJ_SHADING):
            has_graphics = True

    page_box = page.get_bbox()
    coverage = _coverage([b for _, b in images], page_box)

    # Caractères visibles, en s'arrêtant dès que la page est jugée « texte » : sur un PDF texte de
    # 200 pages, le décompte complet coûtait ~5 s sous le verrou pdfium, l'arrêt anticipé ~0,3 s.
    check_hidden = coverage >= HIDDEN_TEXT_MIN_COVERAGE
    invisible_objects: dict[int, bool] = {}
    total = visible = 0
    textpage = page.get_textpage()
    try:
        for i in range(textpage.count_chars()):
            code = pdfium_c.FPDFText_GetUnicode(textpage, i)
            if code == 0 or chr(code).isspace():
                continue
            total += 1
            handle = pdfium_c.FPDFText_GetTextObject(textpage, i)
            key = _address(handle)
            if key:
                invisible = invisible_objects.get(key)
                if invisible is None:
                    invisible = pdfium_c.FPDFTextObj_GetTextRenderMode(handle) == pdfium_c.FPDF_TEXTRENDERMODE_INVISIBLE
                    invisible_objects[key] = invisible
                if invisible:
                    continue  # couche OCR de copieur (mode de rendu 3)
                if check_hidden:
                    left, right, bottom, top = ctypes.c_double(), ctypes.c_double(), ctypes.c_double(), ctypes.c_double()
                    if pdfium_c.FPDFText_GetCharBox(textpage, i, left, right, bottom, top):
                        z_text = z_order.get(key, -1)
                        cx, cy = (left.value + right.value) / 2, (bottom.value + top.value) / 2
                        if any(z_img > z_text and _contains(rect, cx, cy) for z_img, rect in images):
                            continue  # texte peint sous une image : invisible à l'œil
            visible += 1
            if visible >= MIN_TEXT_CHARS:
                break
    finally:
        textpage.close()
    return PageInfo(index=index, chars=total, visible_chars=visible, image_coverage=round(coverage, 3), has_graphics=has_graphics)


def analyse_pdf(blob: bytes) -> PdfAnalysis:
    import pypdfium2

    with _pdfium_lock():
        pdf = pypdfium2.PdfDocument(BytesIO(blob))
        try:
            analysis = PdfAnalysis()
            for index in range(len(pdf)):
                page = pdf[index]
                try:
                    analysis.pages.append(_analyse_page(page, index))
                finally:
                    page.close()
            return analysis
        finally:
            pdf.close()


# --- Rendu --------------------------------------------------------------------------------------


def render_pages(blob: bytes, pages: list[int]) -> list[bytes]:
    """Pages en JPEG (qualité 85, 150 dpi, grand côté ≤ 1568 px), dans l'ordre demandé."""
    import pypdfium2
    from PIL import Image

    out = []
    with _pdfium_lock():
        pdf = pypdfium2.PdfDocument(BytesIO(blob))
        try:
            for index in pages:
                page = pdf[index]
                try:
                    width, height = page.get_size()
                    scale = min(RENDER_DPI / 72, MAX_LONG_SIDE / max(width, height, 1))
                    bitmap = page.render(scale=scale)
                    image = bitmap.to_pil().convert("RGB")
                    bitmap.close()
                finally:
                    page.close()
                if max(image.size) > MAX_LONG_SIDE:  # page tournée ou arrondi
                    image.thumbnail((MAX_LONG_SIDE, MAX_LONG_SIDE), Image.Resampling.LANCZOS)
                buf = BytesIO()
                image.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
                out.append(buf.getvalue())
        finally:
            pdf.close()
    return out


def jpeg_data_uri(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")


# --- Plafond ------------------------------------------------------------------------------------


class ScanPageBudget:
    """Pages en images encore autorisées pour la requête ; réservé dans l'ordre des pièces jointes."""

    def __init__(self, limit: int):
        self.limit = limit
        self.remaining = limit
        self._lock = threading.Lock()

    def take(self, wanted: int) -> int:
        with self._lock:
            granted = min(wanted, self.remaining)
            self.remaining -= granted
            return granted


# --- Textes d'accompagnement --------------------------------------------------------------------


def format_pages(indexes: list[int]) -> str:
    """[0, 1, 2, 4] → « 1 à 3, 5 » (numéros de page à partir de 1)."""
    numbers = sorted(i + 1 for i in indexes)
    parts, start = [], None
    for k, n in enumerate(numbers):
        if start is None:
            start = n
        if k + 1 == len(numbers) or numbers[k + 1] != n + 1:
            parts.append(str(start) if start == n else (f"{start} et {n}" if n == start + 1 else f"{start} à {n}"))
            start = None
    return ", ".join(parts)


def pages_label(indexes: list[int]) -> str:
    """« page 3 » ou « pages 1 à 4 »."""
    return f"page{'s' if len(indexes) > 1 else ''} {format_pages(indexes)}"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n > 1 else ''}"


def scan_notice(name: str, analysis: PdfAnalysis, granted: list[int], limit: int, mixed: bool) -> str:
    scan = analysis.scan_pages
    dropped = [i for i in scan if i not in set(granted)]
    if mixed:
        lines = [
            f"{name} : PDF mixte, {_plural(len(scan), 'page')} scannée{'s' if len(scan) > 1 else ''} sur {analysis.page_count} ({pages_label(scan)}) ; les autres pages sont lues en texte ci-dessous."
        ]
        if granted:
            lines.append(
                f"{_plural(len(granted), 'page')} transmise{'s' if len(granted) > 1 else ''} en image{'s' if len(granted) > 1 else ''}, une image par page, dans l'ordre : {pages_label(granted)}."
            )
    elif granted:
        lines = [
            f"{name} : document scanné, {_plural(len(granted), 'page')} transmise{'s' if len(granted) > 1 else ''} en image{'s' if len(granted) > 1 else ''} (une image par page, dans l'ordre : {pages_label(granted)})."
        ]
    else:
        lines = [f"{name} : document scanné de {_plural(analysis.page_count, 'page')}, aucune page transmise en image."]
    if dropped:
        lines.append(
            f"ATTENTION : plafond de {limit} pages en images par message atteint : "
            + (f"les {pages_label(dropped)} de {name} n'ont pas été lues. " if len(dropped) > 1 else f"la {pages_label(dropped)} de {name} n'a pas été lue. ")
            + "Préviens l'utilisateur que ces pages n'ont pas été lues et qu'il peut les envoyer à part."
        )
    return "\n".join(lines)


def no_vision_notice(name: str, analysis: PdfAnalysis) -> str:
    scan = analysis.scan_pages
    return (
        f"\n{name} : {_plural(len(scan), 'page')} scannée{'s' if len(scan) > 1 else ''} sans texte ({pages_label(scan)}) "
        f"non lue{'s' if len(scan) > 1 else ''} : le modèle utilisé ne lit pas les images. Préviens l'utilisateur."
    )


# --- Lecture d'un PDF joint ---------------------------------------------------------------------


@dataclass
class PdfPlan:
    analysis: PdfAnalysis
    granted: list[int]
    limit: int


def plan_pdf(name: str, blob: bytes, budget: ScanPageBudget) -> PdfPlan | None:
    """Analyse et réservation du plafond ; None si rien à faire (aucune page scannée, fonction coupée, erreur)."""
    if budget.limit <= 0:
        return None
    try:
        analysis = analyse_pdf(blob)
    except Exception:
        logging.warning("scanned_pdf analyse failed for %s, keeping text reading", name, exc_info=True)
        return None
    scan = analysis.scan_pages
    if not scan:
        return None
    granted = scan[: budget.take(len(scan))]
    return PdfPlan(analysis=analysis, granted=granted, limit=budget.limit)


def _text_ranges(page_count: int, excluded: set[int]) -> list[tuple[int, int]]:
    ranges, start = [], None
    for i in range(page_count + 1):
        inside = i < page_count and i not in excluded
        if inside and start is None:
            start = i
        elif not inside and start is not None:
            ranges.append((start, i))
            start = None
    return ranges


def read_planned_pdf(name: str, blob: bytes, plan: PdfPlan, parse_range) -> tuple[str, list[bytes]]:
    """Texte (pages texte + texte d'accompagnement) et JPEG des pages scannées retenues.

    `parse_range(from_page, to_page)` : lecture actuelle (`FileService.parse`) des pages [from, to[,
    en-tête « File: … » compris.
    """
    analysis = plan.analysis
    scan = set(analysis.scan_pages)
    header = HEADER.format(name=name)
    sections = []
    for start, end in _text_ranges(analysis.page_count, scan):
        text = parse_range(start, end)
        text = text[len(header) :] if text.startswith(header) else text
        if text.strip():
            label = f"[{name}, page {start + 1}]" if end == start + 1 else f"[{name}, pages {format_pages(list(range(start, end)))}]"
            sections.append((start, f"{label}\n{text}"))
    mixed = bool(sections)
    if mixed:
        granted = set(plan.granted)
        for index in sorted(scan):
            status = "transmise en image" if index in granted else "NON LUE (plafond de pages en images atteint)"
            sections.append((index, f"[{name}, page {index + 1} : page scannée, {status}]"))
        sections.sort(key=lambda s: s[0])
    images = render_pages(blob, plan.granted) if plan.granted else []
    body = scan_notice(name, analysis, plan.granted, plan.limit, mixed)
    if mixed:
        body += "\n\n" + "\n\n".join(text for _, text in sections)
    logging.info(
        "scanned_pdf name=%s pages=%d scanned=%d images=%d image_bytes=%d mixed=%s",
        name,
        analysis.page_count,
        len(scan),
        len(images),
        sum(len(i) for i in images),
        mixed,
    )
    return header + body, images


# --- Pièces jointes d'une requête (assistants et agents) ----------------------------------------


def _is_pdf(file: dict) -> bool:
    return str(file.get("name", "")).lower().endswith(".pdf") or "pdf" in str(file.get("mime_type", "")).lower()


def _resolved(value) -> Future:
    fut = Future()
    fut.set_result(value)
    return fut


def read_attachments(files: list[dict], layout_recognize: str | None = None, raw: bool = False, vision: bool = True) -> list:
    """Contenu des pièces jointes d'une requête, dans leur ordre : une liste plate d'entrées.

    - texte d'un fichier (str) ;
    - image jointe ou page scannée : data URI (str), ou octets bruts si `raw` (modèles image2text).

    Plafond de pages en images partagé par toutes les pièces jointes, réservé dans leur ordre.
    """
    from api.db.services.file_service import FileService

    if not files:
        return []
    budget = ScanPageBudget(max_scan_pages() if vision else 0)

    def image_entry(file):
        blob = FileService.get_blob(file["created_by"], file["id"])
        if raw:
            return [blob]
        return ["data:{};base64,{}".format(file["mime_type"], base64.b64encode(blob).decode("utf-8"))]

    def text_entry(file, blob, plan):
        def parse_range(from_page=0, to_page=None):
            kwargs = {} if to_page is None else {"from_page": from_page, "to_page": to_page}
            return FileService.parse(file["name"], blob, True, file["created_by"], layout_recognize, **kwargs)

        if plan is not None:
            try:
                text, jpegs = read_planned_pdf(file["name"], blob, plan, parse_range)
                return [text] + (jpegs if raw else [jpeg_data_uri(j) for j in jpegs])
            except Exception:
                logging.warning("scanned_pdf render failed for %s, keeping text reading", file["name"], exc_info=True)
        text = parse_range()
        if not vision and _is_pdf(file) and max_scan_pages() > 0:
            try:
                analysis = analyse_pdf(blob)
                if analysis.scan_pages:
                    text += no_vision_notice(file["name"], analysis)
            except Exception:
                logging.debug("scanned_pdf analyse failed for %s", file["name"], exc_info=True)
        return [text]

    with ThreadPoolExecutor(max_workers=5) as exe:
        futures = []
        for file in files:
            if file["mime_type"].find("image") >= 0:
                futures.append(_resolved(image_entry(file)) if raw else exe.submit(image_entry, file))
                continue
            blob = FileService.get_blob(file["created_by"], file["id"])
            # Analyse dans l'ordre des pièces jointes : le plafond va aux premières pages.
            plan = plan_pdf(file["name"], blob, budget) if _is_pdf(file) else None
            futures.append(exe.submit(text_entry, file, blob, plan))
        return [entry for fut in futures for entry in fut.result()]


# --- Le modèle lit-il les images ? --------------------------------------------------------------

# Familles de modèles multimodaux, pour les modèles ajoutés à la main (Bedrock, OpenAI-API-Compatible…)
# dont le type enregistré est « chat » sans « image2text ».
_VISION_MODEL_NAME = re.compile(
    r"claude-(?!2|instant)|anthropic\.claude-(?!v2|instant)|gpt-4o|gpt-4\.1|gpt-4-turbo|gpt-4-vision|gpt-5|"
    r"(^|[/.])o[134](-|$|@)|chatgpt-4o|gemini|gemma-?3|pixtral|mistral-(small|medium)-(3|2503|2505|2506|latest)|"
    r"llava|bakllava|qwen[\d.]*-?vl|qvq|glm-4(\.\d+)?v|llama-?3\.2.*vision|llama-?4|grok-(2-vision|4)|"
    r"nova-(lite|pro|premier)|internvl|minicpm-v|moondream|kimi-vl|step-1v|yi-vision|vision",
    re.IGNORECASE,
)


def model_reads_images(tenant_id: str | None, llm_id: str | None) -> bool:
    if not llm_id:
        return False
    if tenant_id:
        try:
            from api.db.joint_services.tenant_model_service import get_model_type_by_name

            if "image2text" in get_model_type_by_name(tenant_id, llm_id):
                return True
        except Exception:
            logging.debug("scanned_pdf: model types unavailable for %s", llm_id, exc_info=True)
    return bool(_VISION_MODEL_NAME.search(llm_id))


def canvas_reads_images(canvas) -> bool:
    """Un agent lit les pages en images si l'un de ses composants LLM (LLM, Agent…) utilise un modèle multimodal."""
    try:
        from agent.component.llm import LLM

        tenant_id = canvas.get_model_tenant_id()
        llm_ids = {getattr(cpn["obj"]._param, "llm_id", None) for cpn in canvas.components.values() if isinstance(cpn.get("obj"), LLM)}
        return any(model_reads_images(tenant_id, llm_id) for llm_id in llm_ids if llm_id)
    except Exception:
        logging.debug("scanned_pdf: canvas vision check failed", exc_info=True)
        return True
