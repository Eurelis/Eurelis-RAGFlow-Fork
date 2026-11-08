# Eurelis — helper : CSV synthétiques (balance âgée) dans les encodages et séparateurs rencontrés en prod (AILAB-50).
# Fichier propre au fork Eurelis, absent de l'upstream RAGFlow.
#
# Générés à la volée : aucune donnée client n'est committée.

import csv
from io import StringIO

AGED_BALANCE_HEADER = [
    "Compte",
    "Libellé",
    "Total",
    "Non échu",
    "0 à 30 jours",
    "31 à 60 jours",
    "61 à 90 jours",
    "91 à 120 jours",
    "Plus de 120 jours",
]


def aged_balance_rows(count: int = 200) -> list[list[str]]:
    """Lignes ASCII uniquement : seuls les en-têtes sont accentués (cas où chardet hésite, 0,73)."""
    rows = []
    for i in range(count):
        amounts = [f"{i * 12.5:.2f}", "0.00", "100.50", "0.00", "0.00", "0.00", f"{i * 3.1:.2f}"]
        rows.append([f"411{i:05d}", f"CLIENT {i} SARL"] + [a.replace(".", ",") for a in amounts])
    return rows


def aged_balance_csv(encoding: str = "cp1252", delimiter: str = ";", count: int = 200, bom: bool = False) -> bytes:
    """Balance âgée en CSV, par défaut comme un export Excel FR « CSV (séparateur : point-virgule) »."""
    buf = StringIO()
    writer = csv.writer(buf, delimiter=delimiter, lineterminator="\r\n")  # « 12,50 » quoté si séparateur virgule
    writer.writerow(AGED_BALANCE_HEADER)
    writer.writerows(aged_balance_rows(count))
    return buf.getvalue().encode("utf-8-sig" if bom else encoding)
