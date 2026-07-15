"""Der Planner: Soll/Ist-Vergleich nach dem Terraform-Prinzip.

Eingaben:
  * Soll-Zustand  – Personen aus dem Schulverwaltungs-Export
  * Ist-Zustand   – von SchulSync verwaltete Konten aus dem AD

Ausgabe: ein :class:`~schulsync.models.Plan` mit fünf Aktionsarten.
Der Planner **verändert nichts** – er rechnet nur. Erst ``apply``
führt den Plan aus. Dadurch ist jeder Lauf per Diff-Report
nachvollziehbar und revisionssicher dokumentierbar.

Sicherheitsnetz: Wenn der Export auffällig leer ist (würde mehr als
``max_deaktivierungs_anteil`` der aktiven Konten deaktivieren), wird
der Plan als Konflikt blockiert. Ein halber Export – falsche
Berichtsvorlage, abgebrochener Download – soll nicht still eine
halbe Schule deaktivieren.
"""

from __future__ import annotations

from datetime import date, timedelta

from .models import (
    Anlegen,
    Deaktivieren,
    IstKonto,
    Konflikt,
    Loeschen,
    Plan,
    Reaktivieren,
    SollPerson,
    Umbenennen,
    Verschieben,
)
from .usernames import erzeuge_benutzername

MAX_DEAKTIVIERUNGS_ANTEIL = 0.5  # Notbremse gegen unvollständige Exporte


def berechne_plan(
    soll: list[SollPerson],
    ist: list[IstKonto],
    vergebene_benutzernamen: set[str],
    benutzername_schema: str = "{vorname}.{nachname}",
    notbremse: bool = True,
) -> Plan:
    """Berechnet den Plan. Deterministisch: gleiche Eingaben ⇒ gleicher Plan."""
    plan = Plan()
    ist_nach_id: dict[str, IstKonto] = {}

    for konto in ist:
        if not konto.quell_id:
            plan.konflikte.append(
                Konflikt(
                    betrifft=konto.benutzername,
                    grund=(
                        "Konto liegt im SchulSync-Bereich, hat aber keine Quell-ID "
                        "(employeeNumber). Manuell zuordnen oder herausverschieben."
                    ),
                )
            )
            continue
        if konto.quell_id in ist_nach_id:
            plan.konflikte.append(
                Konflikt(
                    betrifft=f"{konto.benutzername} / {ist_nach_id[konto.quell_id].benutzername}",
                    grund=f"Quell-ID {konto.quell_id} ist im AD doppelt vergeben.",
                )
            )
            continue
        ist_nach_id[konto.quell_id] = konto

    # Namen, die dieser Plan selbst vergibt, zählen sofort als belegt:
    belegt = {b.lower() for b in vergebene_benutzernamen}
    soll_ids: set[str] = set()

    for person in sorted(soll, key=lambda p: (p.klasse or "", p.nachname, p.vorname, p.quell_id)):
        soll_ids.add(person.quell_id)
        konto = ist_nach_id.get(person.quell_id)

        if konto is None:
            # ---------------------------------------------------- ANLEGEN
            try:
                benutzername = erzeuge_benutzername(
                    person.vorname, person.nachname, benutzername_schema, belegt
                )
            except ValueError as e:
                plan.konflikte.append(Konflikt(betrifft=person.anzeigename, grund=str(e)))
                continue
            belegt.add(benutzername.lower())
            plan.anlegen.append(Anlegen(person=person, benutzername=benutzername))
            continue

        veraendert = False

        # ------------------------------------------------- REAKTIVIEREN
        if not konto.aktiv:
            plan.reaktivieren.append(Reaktivieren(konto=konto, nach_klasse=person.klasse))
            veraendert = True
        # -------------------------------------------------- VERSCHIEBEN
        elif person.klasse != konto.klasse:
            plan.verschieben.append(
                Verschieben(konto=konto, von_klasse=konto.klasse, nach_klasse=person.klasse or "")
            )
            veraendert = True

        # --------------------------------------------------- UMBENENNEN
        if (person.vorname, person.nachname) != (konto.vorname, konto.nachname):
            plan.umbenennen.append(
                Umbenennen(
                    konto=konto,
                    neuer_vorname=person.vorname,
                    neuer_nachname=person.nachname,
                )
            )
            veraendert = True

        if not veraendert:
            plan.unveraendert += 1

    # ------------------------------------------------------ DEAKTIVIEREN
    aktive = [k for k in ist_nach_id.values() if k.aktiv]
    abgaenger = sorted(
        (k for k in aktive if k.quell_id not in soll_ids),
        key=lambda k: (k.klasse or "", k.nachname, k.vorname),
    )
    plan.deaktivieren.extend(Deaktivieren(konto=k) for k in abgaenger)

    # Notbremse: unvollständiger Export?
    if (
        notbremse
        and aktive
        and len(abgaenger) / len(aktive) > MAX_DEAKTIVIERUNGS_ANTEIL
        and len(abgaenger) > 5
    ):
        plan.konflikte.append(
            Konflikt(
                betrifft=f"{len(abgaenger)} von {len(aktive)} aktiven Konten",
                grund=(
                    "Der Export würde mehr als die Hälfte aller aktiven Konten "
                    "deaktivieren. Das deutet auf einen unvollständigen Export hin "
                    "(falsche Berichtsvorlage? nur eine Klasse exportiert?). "
                    "Bitte Export prüfen. Wenn es wirklich stimmt: --ohne-notbremse."
                ),
            )
        )

    return plan


def berechne_cleanup(
    ist: list[IstKonto],
    heute: date,
    frist_tage: int,
) -> tuple[list[Loeschen], list[IstKonto]]:
    """Findet Abgänger-Konten, deren Aufbewahrungsfrist abgelaufen ist.

    Rückgabe: (endgültig zu löschen, noch in der Frist).
    Konten ohne lesbaren Deaktivierungs-Stempel werden **nie** gelöscht.
    """
    loeschen: list[Loeschen] = []
    wartend: list[IstKonto] = []
    for konto in sorted(ist, key=lambda k: (k.nachname, k.vorname)):
        if konto.aktiv or konto.deaktiviert_am is None:
            continue
        if heute >= konto.deaktiviert_am + timedelta(days=frist_tage):
            loeschen.append(
                Loeschen(konto=konto, deaktiviert_am=konto.deaktiviert_am, frist_tage=frist_tage)
            )
        else:
            wartend.append(konto)
    return loeschen, wartend
