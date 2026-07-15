"""Führt einen Plan gegen das AD aus.

Grundsätze:

* **Reihenfolge mit System**: erst Struktur, dann Reaktivieren/Anlegen,
  dann Umbenennen/Verschieben, zuletzt Deaktivieren. So ist der Schaden
  bei einem Abbruch mitten im Lauf minimal – und ein erneuter Lauf
  (idempotent!) räumt den Rest auf.
* **Ein Fehler stoppt nicht die Schule**: schlägt ein Konto fehl, wird
  der Fehler gesammelt und weitergemacht. Am Ende gibt es eine ehrliche
  Bilanz statt eines halben Stilllstands.
* Initialpasswörter werden nur im Speicher gehalten und als Datei mit
  Modus 0600 abgelegt – der Aufrufer entscheidet, wann sie gedruckt
  und gelöscht wird.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .config import Config
from .ldapclient import AdVerbindung, LdapFehler
from .models import Plan, Rolle
from .passwords import erzeuge_passwort


@dataclass
class NeuesKonto:
    benutzername: str
    anzeigename: str
    klasse: str | None
    rolle: Rolle
    passwort: str


@dataclass
class ApplyErgebnis:
    struktur_neu: list[str] = field(default_factory=list)
    angelegt: list[NeuesKonto] = field(default_factory=list)
    verschoben: int = 0
    umbenannt: int = 0
    deaktiviert: int = 0
    reaktiviert: int = 0
    fehler: list[str] = field(default_factory=list)

    @property
    def erfolgreich(self) -> bool:
        return not self.fehler


def wende_plan_an(
    plan: Plan,
    ad: AdVerbindung,
    config: Config,
    heute: date,
) -> ApplyErgebnis:
    ergebnis = ApplyErgebnis()
    s = config.struktur

    # 1) Struktur: alle Ziel-Klassen-OUs und -Gruppen müssen existieren.
    klassen = {a.person.klasse for a in plan.anlegen if a.person.klasse}
    klassen |= {v.nach_klasse for v in plan.verschieben if v.nach_klasse}
    klassen |= {r.nach_klasse for r in plan.reaktivieren if r.nach_klasse}
    try:
        ergebnis.struktur_neu = ad.stelle_struktur_sicher(klassen)
    except LdapFehler as e:
        # Ohne Struktur ist alles Weitere zwecklos.
        ergebnis.fehler.append(str(e))
        return ergebnis

    def _ziel_ou(rolle: Rolle, klasse: str | None) -> str:
        if rolle is Rolle.LEHRKRAFT:
            return config.lehrkraefte_dn
        return config.klassen_dn(klasse) if klasse else config.schueler_dn

    def _gruppen(rolle: Rolle, klasse: str | None) -> list[str]:
        if rolle is Rolle.LEHRKRAFT:
            return [s.gruppe_alle_lehrkraefte]
        gruppen = [s.gruppe_alle_schueler]
        if klasse:
            gruppen.append(config.klassen_gruppe(klasse))
        return gruppen

    # 2) Reaktivieren (Rückkehrer zuerst – sie blockieren keinen Benutzernamen).
    for r in plan.reaktivieren:
        try:
            ad.aktiviere(r.konto.dn)
            neuer_dn = ad.verschiebe(r.konto.dn, _ziel_ou(r.konto.rolle, r.nach_klasse))
            for gruppe in _gruppen(r.konto.rolle, r.nach_klasse):
                ad.fuege_zu_gruppe_hinzu(neuer_dn, gruppe)
            r.konto.dn = neuer_dn
            r.konto.klasse = r.nach_klasse
            ergebnis.reaktiviert += 1
        except LdapFehler as e:
            ergebnis.fehler.append(f"Reaktivieren {r.konto.benutzername}: {e}")

    # 3) Anlegen.
    for a in plan.anlegen:
        p = a.person
        passwort = erzeuge_passwort(config.konten.passwort_woerter)
        try:
            dn = ad.lege_benutzer_an(
                benutzername=a.benutzername,
                vorname=p.vorname,
                nachname=p.nachname,
                quell_id=p.quell_id,
                rolle=p.rolle,
                eltern_dn=_ziel_ou(p.rolle, p.klasse),
                passwort=passwort,
            )
            for gruppe in _gruppen(p.rolle, p.klasse):
                ad.fuege_zu_gruppe_hinzu(dn, gruppe)
            ergebnis.angelegt.append(
                NeuesKonto(
                    benutzername=a.benutzername,
                    anzeigename=p.anzeigename,
                    klasse=p.klasse,
                    rolle=p.rolle,
                    passwort=passwort,
                )
            )
        except LdapFehler as e:
            ergebnis.fehler.append(f"Anlegen {a.benutzername}: {e}")

    # 4) Umbenennen (vor dem Verschieben – DN ändert sich dabei nicht,
    #    weil CN = Benutzername).
    for u in plan.umbenennen:
        try:
            ad.benenne_um(u.konto.dn, u.neuer_vorname, u.neuer_nachname)
            ergebnis.umbenannt += 1
        except LdapFehler as e:
            ergebnis.fehler.append(f"Umbenennen {u.konto.benutzername}: {e}")

    # 5) Verschieben (Klassenwechsel): OU-Umzug + Gruppen tauschen.
    for v in plan.verschieben:
        try:
            neuer_dn = ad.verschiebe(v.konto.dn, _ziel_ou(v.konto.rolle, v.nach_klasse))
            if v.von_klasse:
                ad.entferne_aus_gruppe(neuer_dn, config.klassen_gruppe(v.von_klasse))
            if v.nach_klasse:
                ad.fuege_zu_gruppe_hinzu(neuer_dn, config.klassen_gruppe(v.nach_klasse))
            v.konto.dn = neuer_dn
            ergebnis.verschoben += 1
        except LdapFehler as e:
            ergebnis.fehler.append(f"Verschieben {v.konto.benutzername}: {e}")

    # 6) Deaktivieren: Konto sperren, aus allen SchulSync-Gruppen nehmen,
    #    in die Abgänger-OU verschieben, Frist-Stempel setzen.
    for d in plan.deaktivieren:
        try:
            ad.deaktiviere(d.konto.dn, am=heute, frist_tage=config.aufbewahrung.abgaenger_tage)
            for gruppe in ad.gruppen_von(d.konto.dn):
                ad.entferne_aus_gruppe(d.konto.dn, gruppe)
            d.konto.dn = ad.verschiebe(d.konto.dn, config.abgaenger_dn)
            ergebnis.deaktiviert += 1
        except LdapFehler as e:
            ergebnis.fehler.append(f"Deaktivieren {d.konto.benutzername}: {e}")

    return ergebnis


def schreibe_zugangsdaten(
    konten: list[NeuesKonto], pfad: Path, heute: date
) -> Path:
    """Schreibt die Initialpasswörter als CSV (Dateimodus 0600).

    Diese Datei ist der Rohstoff für ``schulsync briefe`` – und sollte
    nach dem Druck gelöscht werden (steht auch so im Dateikopf).
    """
    pfad = Path(pfad)
    with open(pfad, "w", newline="", encoding="utf-8") as f:
        os.fchmod(f.fileno(), 0o600)
        f.write(f"# Initialpasswörter vom {heute.isoformat()} – VERTRAULICH.\n")
        f.write("# Nach dem Druck der Briefe löschen (schulsync briefe erledigt den Rest).\n")
        w = csv.writer(f, delimiter=";")
        w.writerow(["Benutzername", "Name", "Klasse", "Rolle", "Initialpasswort"])
        for k in konten:
            w.writerow(
                [k.benutzername, k.anzeigename, k.klasse or "", k.rolle.value, k.passwort]
            )
    return pfad
