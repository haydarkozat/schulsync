"""Domänenmodell von SchulSync.

Zentrale Idee (Terraform-Prinzip):
  * Der CSV-Export der Schulverwaltung beschreibt den **Soll-Zustand**.
  * Das Active Directory enthält den **Ist-Zustand**.
  * Der Planner berechnet daraus einen nachvollziehbaren Plan,
    der erst nach expliziter Bestätigung angewendet wird.

Als stabiler Schlüssel zwischen beiden Welten dient die ID aus der
Schulverwaltung (SchILD: "Interne ID-Nummer", ASV: "Schülernummer").
Sie wird im AD-Attribut ``employeeNumber`` gespeichert – Namen und
Klassen dürfen sich ändern, die ID nicht.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum


class Rolle(StrEnum):
    SCHUELER = "schueler"
    LEHRKRAFT = "lehrkraft"


_KLASSE_RE = re.compile(r"^([0-9]{1,2})\s*([A-Za-z]{0,3})$")


def normalisiere_klasse(roh: str) -> str:
    """Normalisiert Klassenbezeichnungen: ``5a`` → ``5A``, `` 10 b`` → ``10B``.

    Bezeichnungen ohne Jahrgangsmuster (z. B. Kursstufen wie ``JG1``)
    werden nur getrimmt und großgeschrieben.
    """
    roh = roh.strip()
    m = _KLASSE_RE.match(roh)
    if m:
        return f"{int(m.group(1))}{m.group(2).upper()}"
    return roh.upper().replace(" ", "-")


@dataclass(frozen=True, slots=True)
class SollPerson:
    """Eine Person, wie die Schulverwaltung sie exportiert (Soll-Zustand)."""

    quell_id: str
    vorname: str
    nachname: str
    rolle: Rolle
    klasse: str | None = None  # nur für Schüler:innen

    @property
    def anzeigename(self) -> str:
        return f"{self.vorname} {self.nachname}"


@dataclass(slots=True)
class IstKonto:
    """Ein von SchulSync verwaltetes Konto, wie es im AD existiert (Ist-Zustand)."""

    dn: str
    benutzername: str  # sAMAccountName
    quell_id: str | None
    vorname: str
    nachname: str
    rolle: Rolle
    klasse: str | None
    aktiv: bool
    deaktiviert_am: date | None = None  # aus dem description-Stempel geparst

    @property
    def anzeigename(self) -> str:
        return f"{self.vorname} {self.nachname}"


# ---------------------------------------------------------------------------
# Plan-Aktionen
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Anlegen:
    person: SollPerson
    benutzername: str


@dataclass(frozen=True, slots=True)
class Verschieben:
    """Klassenwechsel: OU-Umzug + Gruppen-Update (z. B. 5A → 6A)."""

    konto: IstKonto
    von_klasse: str | None
    nach_klasse: str


@dataclass(frozen=True, slots=True)
class Umbenennen:
    """Namensänderung in der Schulverwaltung (Heirat, Korrektur …)."""

    konto: IstKonto
    neuer_vorname: str
    neuer_nachname: str


@dataclass(frozen=True, slots=True)
class Deaktivieren:
    """Abgänger: Konto wird deaktiviert und in die Abgänger-OU verschoben.

    Gelöscht wird erst nach Ablauf der Aufbewahrungsfrist durch
    ``schulsync cleanup`` – niemals sofort (Löschkonzept, Art. 17 DSGVO).
    """

    konto: IstKonto


@dataclass(frozen=True, slots=True)
class Reaktivieren:
    """Rückkehrer: war Abgänger, taucht im Export wieder auf."""

    konto: IstKonto
    nach_klasse: str | None


@dataclass(frozen=True, slots=True)
class Loeschen:
    """Endgültige Löschung nach Ablauf der Aufbewahrungsfrist (nur `cleanup`)."""

    konto: IstKonto
    deaktiviert_am: date
    frist_tage: int


@dataclass(frozen=True, slots=True)
class Konflikt:
    """Ein Datensatz, der nicht automatisch verarbeitet werden kann."""

    betrifft: str
    grund: str


@dataclass(slots=True)
class Plan:
    """Ergebnis des Soll/Ist-Vergleichs. Reihenfolge der Listen ist deterministisch."""

    anlegen: list[Anlegen] = field(default_factory=list)
    verschieben: list[Verschieben] = field(default_factory=list)
    umbenennen: list[Umbenennen] = field(default_factory=list)
    deaktivieren: list[Deaktivieren] = field(default_factory=list)
    reaktivieren: list[Reaktivieren] = field(default_factory=list)
    konflikte: list[Konflikt] = field(default_factory=list)
    unveraendert: int = 0

    @property
    def anzahl_aenderungen(self) -> int:
        return (
            len(self.anlegen)
            + len(self.verschieben)
            + len(self.umbenennen)
            + len(self.deaktivieren)
            + len(self.reaktivieren)
        )

    @property
    def leer(self) -> bool:
        return self.anzahl_aenderungen == 0
