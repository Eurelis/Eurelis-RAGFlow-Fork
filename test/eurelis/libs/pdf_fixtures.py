# Eurelis — helper : PDF synthétiques (balance en colonnes, texte simple, scan sans couche texte).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Générés à la volée (reportlab) : aucune donnée client n'est committée (AILAB-45).

from io import BytesIO

from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# Bord droit (en points) des colonnes de montants, alignées à droite comme dans un export comptable.
BALANCE_COLUMNS = {"Débiteur": 470, "Créditeur": 590, "Sld N-1": 720}

# (compte, intitulé, débiteur, créditeur, solde N-1) — montants sans signe dans les colonnes D/C.
BALANCE_ROWS = [
    ("10100000", "Capital", "", "3 500 000,00", "-3 500 000,00"),
    ("11900000", "Report a nouveau solde debit", "1 761 331,16", "", ""),
    ("40100000", "Fournisseurs", "", "12 450,00", "-9 800,00"),
    ("51200000", "Banque", "245 118,84", "", "198 004,12"),
    ("60100000", "Achats matieres premieres", "1 506 000,00", "", "1 202 330,57"),
]

SIMPLE_TEXT_LINES = [
    "Compte rendu de la reunion du comite de pilotage.",
    "Le budget previsionnel est valide sans reserve.",
    "La prochaine echeance est fixee au premier trimestre.",
]


def balance_pdf() -> bytes:
    """Balance comptable en colonnes : N° Compte, Intitulé, Débiteur, Créditeur, Sld N-1."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setFont("Helvetica", 9)
    y = 540
    c.drawString(40, y, "Balance des comptes generaux")
    y -= 30
    c.drawString(40, y, "N° Compte")
    c.drawString(120, y, "Intitulé")
    for header, right in BALANCE_COLUMNS.items():
        c.drawRightString(right, y, header)
    for account, label, debit, credit, previous in BALANCE_ROWS:
        y -= 16
        c.drawString(40, y, account)
        c.drawString(120, y, label)
        for amount, right in zip((debit, credit, previous), BALANCE_COLUMNS.values()):
            if amount:
                c.drawRightString(right, y, amount)
    c.showPage()
    c.save()
    return buf.getvalue()


def simple_text_pdf() -> bytes:
    """Quelques phrases sur une colonne, sans tableau."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica", 11)
    y = 780
    for line in SIMPLE_TEXT_LINES:
        c.drawString(60, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def scanned_pdf() -> bytes:
    """Page constituée d'une seule image (aucune couche texte), comme un document scanné."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (600, 300), "white")
    draw = ImageDraw.Draw(img)
    for i in range(6):
        draw.rectangle((40, 40 + i * 35, 520 - i * 40, 55 + i * 35), fill="black")
    img_buf = BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.drawImage(ImageReader(img_buf), 40, 400, width=500, height=250)
    c.showPage()
    c.save()
    return buf.getvalue()


# AILAB-26 — PUA de la police Type 3 synthétique : chiffres U+E071 à U+E07A, virgule U+E093 et signe
# moins U+E088, comme dans les PDF « 3-Heights » du ticket.
PUA_GLYPHS = {**{str(d): chr(0xE071 + d) for d in range(10)}, ",": "", "-": ""}
_TYPE3_ADVANCE = 600  # chasse fixe de chaque glyphe, en millièmes de corps


def pua_balance_pdf() -> bytes:
    """Balance en colonnes dont les chiffres sont encodés comme dans les PDF du ticket AILAB-26.

    Police Type 3 dont la table ToUnicode envoie chiffres, virgule et signe moins vers la PUA ; le vrai
    texte n'est porté que par des balises `/Span <</ActualText …>> BDC … EMC`. Les en-têtes Débiteur /
    Créditeur sont en Helvetica standard. PDF écrit à la main (reportlab ne sait pas produire ce cas).
    """
    size = 9
    advance = _TYPE3_ADVANCE * size / 1000

    def run(x: float, y: float, text: str) -> str:
        # Codes de glyphes = ASCII : c'est la ToUnicode qui détourne chiffres et signes vers la PUA.
        literal = "".join(f"\\{c}" if c in "()\\" else c for c in text)
        return f"/Span <</ActualText ({literal})>> BDC BT /T3 {size} Tf {x:.2f} {y:.2f} Td ({literal}) Tj ET EMC\n"

    def helvetica(x: float, y: float, text: str, right: bool = False) -> str:
        if right:  # largeur approximative suffisante pour l'alignement à droite des en-têtes
            x -= len(text) * size * 0.55
        return f"BT /F1 {size} Tf {x:.2f} {y:.2f} Td ({text.encode('cp1252').decode('latin-1')}) Tj ET\n"

    ops = [helvetica(40, 540, "Balance des comptes generaux")]
    y = 510
    ops.append(helvetica(40, y, "N° Compte"))
    ops.append(helvetica(120, y, "Intitulé"))
    for header, right in BALANCE_COLUMNS.items():
        ops.append(helvetica(right, y, header, right=True))
    for account, label, debit, credit, previous in BALANCE_ROWS:
        y -= 16
        ops.append(run(40, y, account))
        ops.append(run(120, y, label))
        for amount, right in zip((debit, credit, previous), BALANCE_COLUMNS.values()):
            if amount:
                ops.append(run(right - len(amount) * advance, y, amount))
    content = "".join(ops).encode("latin-1")

    cmap_lines = [f"<{ord(c):02X}> <{ord(PUA_GLYPHS.get(c, c)):04X}>" for c in map(chr, range(32, 127))]
    tounicode = (
        "/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        "/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def\n"
        "/CMapName /Eurelis-PUA def /CMapType 2 def\n"
        "1 begincodespacerange <00> <FF> endcodespacerange\n"
        f"{len(cmap_lines)} beginbfchar\n" + "\n".join(cmap_lines) + "\nendbfchar\n"
        "endcmap CMapName currentdict /CMap defineresource pop end end\n"
    ).encode()
    glyph = f"{_TYPE3_ADVANCE} 0 0 0 500 700 d1 50 0 400 700 re f".encode()
    names = " ".join(f"/g{code}" for code in range(32, 127))
    char_procs = " ".join(f"/g{code} 7 0 R" for code in range(32, 127))
    widths = " ".join([str(_TYPE3_ADVANCE)] * 95)

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Contents 4 0 R /Resources << /Font << /T3 5 0 R /F1 8 0 R >> >> >>",
        _stream(content),
        (
            "<< /Type /Font /Subtype /Type3 /FontBBox [0 0 600 700] /FontMatrix [0.001 0 0 0.001 0 0]"
            f" /CharProcs << {char_procs} >> /Encoding << /Type /Encoding /Differences [32 {names}] >>"
            f" /FirstChar 32 /LastChar 126 /Widths [{widths}] /ToUnicode 6 0 R /Resources << >> >>"
        ).encode(),
        _stream(tounicode),
        _stream(glyph),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    return _assemble_pdf(objects)


def _stream(data: bytes) -> bytes:
    return b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


def _assemble_pdf(objects: list[bytes]) -> bytes:
    out = BytesIO()
    out.write(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()
