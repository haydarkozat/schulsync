"""Einlesen der Schulverwaltungs-Exporte (CSV).

Realität an Schulen: Exporte kommen mal als UTF-8, mal als Windows-1252,
mit Semikolon oder Komma, und die Spaltennamen unterscheiden sich je nach
Bundesland und Berichtsvorlage. Dieses Modul fängt genau das ab.

Eingebaute Profile:

* ``schild-nrw``  – SchILD-NRW-Textexport (Semikolon, typ. Windows-1252)
* ``asv-bw``      – typischer ASV-BW-Export aus der Berichtsbibliothek
* ``generisch``   – eigene Spaltenzuordnung in schulsync.yaml

Datensparsamkeit (Art. 5 DSGVO): Es werden **nur** ID, Vorname, Nachname
und Klasse gelesen. Geburtsdatum, Geschlecht, Adresse usw. werden bewusst
ignoriert – sie sind für die Kontoanlage nicht erforderlich.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

from .models import Rolle, SollPerson, normalisiere_klasse


@dataclass(frozen=True)
class CsvProfil:
    name: str
    spalte_id: str
    spalte_vorname: str
    spalte_nachname: str
    spalte_klasse: str


PROFILE: dict[str, CsvProfil] = {
    "schild-nrw": CsvProfil(
        name="schild-nrw",
        spalte_id="Interne ID-Nummer",
        spalte_vorname="Vorname",
        spalte_nachname="Nachname",
        spalte_klasse="Klasse",
    ),
    "asv-bw": CsvProfil(
        name="asv-bw",
        spalte_id="Schülernummer",
        spalte_vorname="Rufname",
        spalte_nachname="Familienname",
        spalte_klasse="Klasse",
    ),
}


class CsvFehler(Exception):
    """Verständlicher Fehler beim Einlesen des Exports."""


def _dekodiere(pfad: Path) -> tuple[str, str]:
    """Liest die Datei und erkennt die Kodierung (UTF-8 → Windows-1252)."""
    roh = pfad.read_bytes()
    for kodierung in ("utf-8-sig", "cp1252"):
        try:
            return roh.decode(kodierung), kodierung
        except UnicodeDecodeError:
            continue
    # cp1252 kann fast alles dekodieren; hier landen wir praktisch nie.
    return roh.decode("latin-1"), "latin-1"


def _erkenne_trennzeichen(kopfzeile: str) -> str:
    """Semikolon ist an deutschen Schulen der Normalfall, Komma die Ausnahme."""
    kandidaten = {t: kopfzeile.count(t) for t in (";", ",", "\t")}
    bestes = max(kandidaten, key=lambda t: kandidaten[t])
    if kandidaten[bestes] == 0:
        raise CsvFehler("Kein Trennzeichen (;, , oder Tab) in der Kopfzeile gefunden.")
    return bestes


def _profil_aus_config(profil_name: str, spalten: dict[str, str] | None) -> CsvProfil:
    if profil_name == "generisch":
        noetig = {"id", "vorname", "nachname", "klasse"}
        if not spalten or not noetig.issubset(spalten):
            fehlend = sorted(noetig - set(spalten or {}))
            raise CsvFehler(
                "Profil 'generisch' braucht unter csv.spalten die Schlüssel "
                f"{sorted(noetig)} – es fehlen: {fehlend}"
            )
        return CsvProfil(
            name="generisch",
            spalte_id=spalten["id"],
            spalte_vorname=spalten["vorname"],
            spalte_nachname=spalten["nachname"],
            spalte_klasse=spalten["klasse"],
        )
    try:
        return PROFILE[profil_name]
    except KeyError:
        raise CsvFehler(
            f"Unbekanntes CSV-Profil '{profil_name}'. "
            f"Verfügbar: {', '.join(sorted(PROFILE))}, generisch"
        ) from None


@dataclass
class LeseErgebnis:
    personen: list[SollPerson]
    kodierung: str
    trennzeichen: str
    warnungen: list[str]


def lese_export(
    pfad: Path | str,
    rolle: Rolle,
    profil_name: str = "schild-nrw",
    spalten: dict[str, str] | None = None,
    trennzeichen: str | None = None,
) -> LeseErgebnis:
    """Liest einen Export ein und validiert ihn streng.

    Harte Fehler (Abbruch): fehlende Spalten, doppelte IDs, leere Pflichtfelder.
    Lieber ein klarer Fehler als 600 halbrichtige Konten.
    """
    pfad = Path(pfad)
    if not pfad.exists():
        raise CsvFehler(f"Datei '{pfad}' nicht gefunden.")

    profil = _profil_aus_config(profil_name, spalten)
    text, kodierung = _dekodiere(pfad)
    erste_zeile = text.splitlines()[0] if text.strip() else ""
    if not erste_zeile:
        raise CsvFehler(f"'{pfad}' ist leer.")
    sep = trennzeichen or _erkenne_trennzeichen(erste_zeile)

    leser = csv.DictReader(io.StringIO(text), delimiter=sep)
    feldnamen = [f.strip() for f in (leser.fieldnames or [])]

    braucht = [profil.spalte_id, profil.spalte_vorname, profil.spalte_nachname]
    if rolle is Rolle.SCHUELER:
        braucht.append(profil.spalte_klasse)
    fehlend = [s for s in braucht if s not in feldnamen]
    if fehlend:
        raise CsvFehler(
            f"Spalten {fehlend} fehlen in '{pfad}' (Profil '{profil.name}', "
            f"gefunden: {feldnamen}). Prüfen Sie Profil bzw. csv.spalten in schulsync.yaml."
        )

    personen: list[SollPerson] = []
    warnungen: list[str] = []
    gesehen: dict[str, int] = {}

    for nr, zeile in enumerate(leser, start=2):  # Zeile 1 = Kopf
        zeile = {(k or "").strip(): (v or "").strip() for k, v in zeile.items()}
        quell_id = zeile.get(profil.spalte_id, "")
        vorname = zeile.get(profil.spalte_vorname, "")
        nachname = zeile.get(profil.spalte_nachname, "")
        klasse_roh = zeile.get(profil.spalte_klasse, "")

        if not any([quell_id, vorname, nachname]):
            continue  # komplett leere Zeile am Dateiende
        if not quell_id:
            raise CsvFehler(f"Zeile {nr}: {profil.spalte_id} fehlt ({vorname} {nachname}).")
        if not vorname or not nachname:
            raise CsvFehler(f"Zeile {nr}: Vor- oder Nachname fehlt (ID {quell_id}).")
        if quell_id in gesehen:
            raise CsvFehler(
                f"Zeile {nr}: ID {quell_id} kommt doppelt vor (zuerst in Zeile "
                f"{gesehen[quell_id]}). Export bitte in der Schulverwaltung prüfen."
            )
        gesehen[quell_id] = nr

        klasse: str | None = None
        if rolle is Rolle.SCHUELER:
            if not klasse_roh:
                raise CsvFehler(f"Zeile {nr}: Klasse fehlt (ID {quell_id}).")
            klasse = normalisiere_klasse(klasse_roh)
            if klasse != klasse_roh:
                warnungen.append(f"Klasse '{klasse_roh}' → '{klasse}' normalisiert (Zeile {nr}).")

        personen.append(
            SollPerson(
                quell_id=quell_id,
                vorname=vorname,
                nachname=nachname,
                rolle=rolle,
                klasse=klasse,
            )
        )

    personen.sort(key=lambda p: (p.klasse or "", p.nachname, p.vorname, p.quell_id))
    return LeseErgebnis(
        personen=personen, kodierung=kodierung, trennzeichen=sep, warnungen=warnungen
    )
