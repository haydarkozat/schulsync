"""Initialpasswörter.

Anforderungen aus der Praxis:

* Ein Fünftklässler muss es **abtippen** können → Wortpaare statt Zeichensalat.
* AD-Komplexitätsrichtlinie (3 von 4 Zeichenklassen) muss erfüllt sein
  → Großbuchstabe + Kleinbuchstaben + Ziffern sind immer enthalten.
* Es ist ein **Einmalpasswort**: ``pwdLastSet = 0`` erzwingt die Änderung
  bei der ersten Anmeldung. Die Stärke muss den Schulflur bis zur ersten
  Anmeldung überleben, keinen Offline-Angriff über Jahre.
* Kryptografisch sauberer Zufall via ``secrets``.
"""

from __future__ import annotations

import secrets

# Kindgerechte, eindeutig tippbare Wörter (keine Umlaute, kein ß):
WOERTER = (
    "Adler", "Ampel", "Anker", "Apfel", "Banane", "Baum", "Berg", "Biber",
    "Blitz", "Brille", "Delfin", "Drache", "Eiche", "Ente", "Erdbeere",
    "Falke", "Feder", "Fichte", "Flamme", "Garten", "Gipfel", "Hafen",
    "Herbst", "Himmel", "Honig", "Igel", "Insel", "Kaktus", "Kirsche",
    "Koala", "Komet", "Kompass", "Kranich", "Lampe", "Leuchtturm", "Linde",
    "Melone", "Mond", "Morgen", "Nebel", "Orange", "Panda", "Pilot",
    "Pinguin", "Rakete", "Regen", "Robbe", "Salat", "Sommer", "Sonne",
    "Stern", "Sturm", "Tiger", "Tomate", "Traktor", "Wal", "Wiese",
    "Winter", "Wolke", "Zebra",
)

MIN_LAENGE = 12


def erzeuge_passwort(anzahl_woerter: int = 2) -> str:
    """Erzeugt z. B. ``Tiger-Wolke-83`` – merkbar, tippbar, AD-konform."""
    anzahl_woerter = max(2, anzahl_woerter)
    while True:
        woerter = [secrets.choice(WOERTER) for _ in range(anzahl_woerter)]
        ziffern = f"{secrets.randbelow(90) + 10}"  # zweistellig, keine führende 0
        pw = "-".join([*woerter, ziffern])
        if len(pw) >= MIN_LAENGE:
            return pw
