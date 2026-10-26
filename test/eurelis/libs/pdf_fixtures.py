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
