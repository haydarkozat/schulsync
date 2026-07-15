#!/usr/bin/env python3
"""Erzeugt die (vollständig fiktiven!) Beispiel-Exporte unter examples/.

Deterministisch (fester Seed) – jeder Lauf erzeugt identische Dateien.
Die Namen sind bewusst vielfältig (deutsche, türkische, polnische,
arabische, ukrainische …) und enthalten Umlaute, Sonderzeichen und
absichtliche Härtefälle:

* zwei »Emma Fischer«             → Benutzernamen-Kollision (emma.fischer2)
* Konstantin-Alexander Wagenknecht → sAMAccountName-20-Zeichen-Grenze
* Namen mit ä/ö/ü/ß/ç/ş/ł/đ        → Transliteration

Die Hauptdateien sind UTF-8 (wie moderne SchILD-/SVWS-Exporte). Zusätzlich
gibt es eine kleine Legacy-Datei in Windows-1252 – ältere Exporte kommen
so daher, und SchulSync erkennt die Kodierung automatisch. (Zeichen wie
ş oder ł existieren in CP1252 schlicht nicht – auch das ist Schulrealität.)

Drei Dateien erzählen die Geschichte eines Schuljahreswechsels:

1. schild-export-2025.csv   Schuljahr 2025/26 – der Ausgangszustand
2. schild-export-2026.csv   Schuljahr 2026/27 – alle eine Klasse weiter,
                            10er sind Abgänger, neue 5er kommen dazu,
                            zwei Namensänderungen
3. schild-export-2026-nachzuegler.csv
                            wie (2), aber eine Abgängerin von 2026 ist
                            zurückgezogen → Reaktivierungs-Fall
"""

from __future__ import annotations

import csv
import random
from pathlib import Path

ZIEL = Path(__file__).resolve().parent.parent / "examples"
R = random.Random(20260901)  # fester Seed: reproduzierbare Beispieldaten

VORNAMEN = [
    "Emma", "Ben", "Mia", "Noah", "Lina", "Elias", "Clara", "Finn", "Ayşe",
    "Emir", "Zeynep", "Leon", "Sofia", "Luca", "Marie", "Paul", "Amira",
    "Yusuf", "Hannah", "Felix", "Lea", "Jonas", "Melisa", "David", "Olena",
    "Piotr", "Fatma", "Anton", "Ida", "Karim", "Nele", "Mateusz", "Selin",
    "Oskar", "Ronja", "Deniz", "Greta", "Milan", "Elif", "Theo",
]
NACHNAMEN = [
    "Müller", "Schmidt", "Yılmaz", "Fischer", "Weber", "Kaya", "Wagner",
    "Becker", "Öztürk", "Hoffmann", "Schäfer", "Koch", "Demir", "Richter",
    "Kowalski", "Bauer", "Şahin", "Wolf", "Neumann", "Schröder", "Zieliński",
    "Krüger", "Haddad", "Braun", "Çelik", "Đorđević", "Lange", "Schmitz",
    "Bondarenko", "Krause", "Aydın", "Vogel", "Groß", "Frank", "Böhm",
]

KLASSEN_2025 = ["5A", "5B", "6A", "6B", "7A", "7B", "8A", "8B", "9A", "9B", "10A", "10B"]
PRO_KLASSE = 12
KOPF = ["Interne ID-Nummer", "Nachname", "Vorname", "Klasse"]


def naechste_klasse(klasse: str) -> str | None:
    stufe, zug = int(klasse[:-1]), klasse[-1]
    return None if stufe >= 10 else f"{stufe + 1}{zug}"


def schreibe(pfad: Path, zeilen: list[list[str]], kodierung: str = "utf-8") -> None:
    with open(pfad, "w", newline="", encoding=kodierung) as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(KOPF)
        w.writerows(zeilen)
    print(f"  {pfad.name}: {len(zeilen)} Zeilen ({kodierung})")


def main() -> None:
    ZIEL.mkdir(exist_ok=True)
    naechste_id = 1001
    schueler: list[dict] = []  # {id, vorname, nachname, klasse}

    def neuer_schueler(klasse: str, vorname: str | None = None,
                       nachname: str | None = None) -> dict:
        nonlocal naechste_id
        s = {
            "id": str(naechste_id),
            "vorname": vorname or R.choice(VORNAMEN),
            "nachname": nachname or R.choice(NACHNAMEN),
            "klasse": klasse,
        }
        naechste_id += 1
        schueler.append(s)
        return s

    # ---- Schuljahr 2025/26 --------------------------------------------------
    for klasse in KLASSEN_2025:
        for _ in range(PRO_KLASSE):
            neuer_schueler(klasse)

    # Härtefälle gezielt einbauen:
    neuer_schueler("7A", "Emma", "Fischer")
    neuer_schueler("8B", "Emma", "Fischer")          # → emma.fischer2
    neuer_schueler("9A", "Konstantin-Alexander", "Wagenknecht")  # → 20-Zeichen-Grenze
    neuer_schueler("6B", "François", "N'Diaye")      # Akzent + Apostroph
    neuer_schueler("5A", "Łukasz", "Wróblewski")     # polnische Sonderzeichen

    export_2025 = [[s["id"], s["nachname"], s["vorname"], s["klasse"]] for s in schueler]
    schreibe(ZIEL / "schild-export-2025.csv", export_2025)

    # ---- Schuljahr 2026/27: eine Stufe weiter -------------------------------
    bleiben: list[dict] = []
    for s in schueler:
        neue = naechste_klasse(s["klasse"])
        if neue is not None:
            bleiben.append({**s, "klasse": neue})

    # Zwei Namensänderungen (Heirat der Eltern / Korrektur):
    bleiben[10] = {**bleiben[10], "nachname": "Schmidt-Yılmaz"}
    bleiben[25] = {**bleiben[25], "vorname": "Mia-Sophie"}

    # Neue Fünftklässler:
    neue_5er: list[dict] = []
    for klasse in ("5A", "5B"):
        for _ in range(PRO_KLASSE):
            neue_5er.append(neuer_schueler(klasse))

    jahr_2026 = bleiben + neue_5er
    export_2026 = [[s["id"], s["nachname"], s["vorname"], s["klasse"]] for s in jahr_2026]
    schreibe(ZIEL / "schild-export-2026.csv", export_2026)

    # ---- Nachzügler: eine Abgängerin kehrt zurück ---------------------------
    # (Familie zurückgezogen: gleiche ID, Konto wird reaktiviert statt neu angelegt)
    ehemalige_10a = next(s for s in schueler if s["klasse"] == "10A")
    rueckkehr = {**ehemalige_10a, "klasse": "10A"}  # wiederholt die 10. bei uns
    export_nachz = export_2026 + [[rueckkehr["id"], rueckkehr["nachname"],
                                   rueckkehr["vorname"], rueckkehr["klasse"]]]
    schreibe(ZIEL / "schild-export-2026-nachzuegler.csv", export_nachz)

    # ---- Legacy-Beispiel: Windows-1252, wie ältere Exporte ------------------
    legacy = [
        ["8801", "Müller", "Jürgen", "5C"],
        ["8802", "Schäfer", "Björn", "5C"],
        ["8803", "Öztürk", "Çiğdem".replace("ğ", "g"), "5C"],  # CP1252 kennt kein ğ
        ["8804", "Groß", "Käthe", "5C"],
        ["8805", "Béringer", "François", "5C"],
    ]
    schreibe(ZIEL / "schild-export-legacy-cp1252.csv", legacy, kodierung="cp1252")

    # ---- Lehrkräfte (UTF-8, gleiche Spalten, Klasse leer) --------------------
    lehrkraefte = [
        ["9001", "Özdemir", "Hülya", ""],
        ["9002", "Brandt", "Sebastian", ""],
        ["9003", "Kowalczyk", "Agnieszka", ""],
        ["9004", "Yıldırım", "Mehmet", ""],
        ["9005", "Fischer", "Emma", ""],  # Kollision mit zwei Schülerinnen!
    ]
    with open(ZIEL / "lehrkraefte.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(KOPF)
        w.writerows(lehrkraefte)
    print(f"  lehrkraefte.csv: {len(lehrkraefte)} Zeilen (utf-8)")


if __name__ == "__main__":
    print("Erzeuge fiktive Beispieldaten …")
    main()
    print("Fertig.")
