"""SchulSync-Kommandozeile.

Arbeitsablauf beim Schuljahreswechsel::

    schulsync validate export.csv          # Export prüfen
    schulsync plan export.csv              # Was würde passieren? (ändert nichts)
    schulsync apply export.csv --ja        # Plan ausführen
    schulsync briefe zugangsdaten-*.csv    # Passwort-Briefe drucken
    schulsync cleanup --ja                 # Abgänger nach Ablauf der Frist löschen

Exit-Codes (skript- und monitoringfreundlich):
    0 = Erfolg / keine Abweichungen
    1 = Fehler (Konfiguration, CSV, LDAP)
    2 = Konflikte im Plan – manuelle Klärung nötig
    3 = ``plan --check``: es gibt Abweichungen (für Cron/Monitoring)
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import __version__
from .applier import schreibe_zugangsdaten, wende_plan_an
from .config import Config, KonfigFehler, lade_config
from .csvsource import CsvFehler, lese_export
from .ldapclient import AdVerbindung, LdapFehler
from .models import Plan, Rolle, SollPerson
from .planner import berechne_cleanup, berechne_plan
from .report import lese_zugangsdaten, schreibe_briefe, schreibe_report

app = typer.Typer(
    help="Schuljahreswechsel ohne Handarbeit: Schulverwaltung → Active Directory.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

ConfigOption = typer.Option("schulsync.yaml", "--config", "-c", help="Pfad zur Konfiguration.")
MAX_ZEILEN_TERMINAL = 15


def _fehler(meldung: str, code: int = 1) -> None:
    console.print(Panel(meldung, title="Fehler", border_style="red"))
    raise typer.Exit(code)


def _lade_config(pfad: Path) -> Config:
    try:
        return lade_config(pfad)
    except KonfigFehler as e:
        _fehler(str(e))
        raise  # nie erreicht – beruhigt die Typprüfung


def _lade_soll(
    schueler_csv: Path,
    lehrkraefte_csv: Path | None,
    config: Config,
) -> list[SollPerson]:
    soll: list[SollPerson] = []
    for pfad, rolle in ((schueler_csv, Rolle.SCHUELER), (lehrkraefte_csv, Rolle.LEHRKRAFT)):
        if pfad is None:
            continue
        ergebnis = lese_export(
            pfad,
            rolle,
            profil_name=config.csv.profil,
            spalten=config.csv.spalten,
            trennzeichen=config.csv.trennzeichen,
        )
        for w in ergebnis.warnungen:
            console.print(f"[yellow]⚠[/] {w}")
        console.print(
            f"[green]✔[/] {pfad}: [bold]{len(ergebnis.personen)}[/] "
            f"{'Schüler:innen' if rolle is Rolle.SCHUELER else 'Lehrkräfte'} "
            f"({ergebnis.kodierung}, Trennzeichen '{ergebnis.trennzeichen}')"
        )
        soll.extend(ergebnis.personen)
    return soll


def zeige_plan(plan: Plan, ziel: str, out: Console | None = None) -> None:
    """Stellt den Plan im Terminal dar (wird auch für die README-SVGs genutzt)."""
    out = out or console
    uebersicht = Table.grid(padding=(0, 2))
    uebersicht.add_column(justify="right", style="bold")
    uebersicht.add_column()
    zeilen = [
        (len(plan.anlegen), "[green]＋ Anlegen[/]"),
        (len(plan.verschieben), "[blue]⇄ Klassenwechsel[/]"),
        (len(plan.umbenennen), "[yellow]✎ Umbenennen[/]"),
        (len(plan.reaktivieren), "[magenta]↻ Reaktivieren (Rückkehrer)[/]"),
        (len(plan.deaktivieren), "[red]⏻ Deaktivieren (Abgänger)[/]"),
        (plan.unveraendert, "[dim]= Unverändert[/]"),
    ]
    for zahl, label in zeilen:
        uebersicht.add_row(str(zahl), label)
    out.print(
        Panel(
            uebersicht,
            title=f"[bold]SchulSync-Plan[/] → {ziel}",
            subtitle="[dim]Es wurde noch nichts geändert[/]",
            border_style="cyan",
        )
    )

    def _tabelle(titel: str, stil: str, spalten: list[str], zeilen: list[list[str]]) -> None:
        if not zeilen:
            return
        t = Table(title=f"{titel} ({len(zeilen)})", title_style=f"bold {stil}",
                  border_style=stil, title_justify="left")
        for s in spalten:
            t.add_column(s)
        for z in zeilen[:MAX_ZEILEN_TERMINAL]:
            t.add_row(*z)
        if len(zeilen) > MAX_ZEILEN_TERMINAL:
            t.add_row(*["…"] * len(spalten))
            t.caption = f"{len(zeilen) - MAX_ZEILEN_TERMINAL} weitere im HTML-Report"
        out.print(t)

    _tabelle(
        "＋ Anlegen", "green", ["Name", "Klasse", "Benutzername"],
        [[a.person.anzeigename, a.person.klasse or "–", a.benutzername] for a in plan.anlegen],
    )
    _tabelle(
        "⇄ Klassenwechsel", "blue", ["Name", "Benutzername", "Wechsel"],
        [[v.konto.anzeigename, v.konto.benutzername, f"{v.von_klasse or '–'} → {v.nach_klasse}"]
         for v in plan.verschieben],
    )
    _tabelle(
        "✎ Umbenennen", "yellow", ["Benutzername", "Bisher", "Neu"],
        [[u.konto.benutzername, u.konto.anzeigename, f"{u.neuer_vorname} {u.neuer_nachname}"]
         for u in plan.umbenennen],
    )
    _tabelle(
        "↻ Reaktivieren", "magenta", ["Name", "Benutzername", "Neue Klasse"],
        [[r.konto.anzeigename, r.konto.benutzername, r.nach_klasse or "–"]
         for r in plan.reaktivieren],
    )
    _tabelle(
        "⏻ Deaktivieren", "red", ["Name", "Benutzername", "Bisherige Klasse"],
        [[d.konto.anzeigename, d.konto.benutzername, d.konto.klasse or "–"]
         for d in plan.deaktivieren],
    )
    if plan.konflikte:
        _tabelle(
            "⚠ Konflikte – bitte zuerst klären", "red", ["Betrifft", "Grund"],
            [[k.betrifft, k.grund] for k in plan.konflikte],
        )
    if plan.leer and not plan.konflikte:
        out.print("[green]✔ Keine Abweichungen – AD und Schulverwaltung sind synchron.[/]")


def _berechne(
    config: Config,
    schueler_csv: Path,
    lehrkraefte_csv: Path | None,
    ohne_notbremse: bool,
) -> tuple[Plan, AdVerbindung]:
    soll = _lade_soll(schueler_csv, lehrkraefte_csv, config)
    ad = AdVerbindung(config)
    ad.verbinden()
    ist = ad.lade_ist_konten()
    vergeben = ad.alle_benutzernamen_der_domaene()
    console.print(
        f"[green]✔[/] AD verbunden: [bold]{len(ist)}[/] verwaltete Konten, "
        f"{len(vergeben)} Benutzernamen domänenweit belegt"
    )
    plan = berechne_plan(
        soll,
        ist,
        vergeben,
        benutzername_schema=config.konten.benutzername_schema,
        notbremse=not ohne_notbremse,
    )
    return plan, ad


# --------------------------------------------------------------------------
# Kommandos
# --------------------------------------------------------------------------


@app.command()
def version() -> None:
    """Zeigt die SchulSync-Version."""
    console.print(f"SchulSync {__version__}")


@app.command()
def validate(
    schueler_csv: Path = typer.Argument(..., help="Export der Schulverwaltung (Schüler)."),
    lehrkraefte: Path | None = typer.Option(None, help="Optionaler Lehrkräfte-Export."),
    config_pfad: Path = ConfigOption,
) -> None:
    """Prüft einen Export, ohne das AD anzufassen: Kodierung, Spalten, Dubletten."""
    config = _lade_config(config_pfad)
    try:
        personen = _lade_soll(schueler_csv, lehrkraefte, config)
    except CsvFehler as e:
        _fehler(str(e))
        return
    klassen = sorted({p.klasse for p in personen if p.klasse})
    console.print(
        f"[green]✔ Export in Ordnung:[/] {len(personen)} Personen, "
        f"{len(klassen)} Klassen ({', '.join(klassen[:12])}{' …' if len(klassen) > 12 else ''})"
    )


@app.command()
def check(config_pfad: Path = ConfigOption) -> None:
    """Prüft Konfiguration und AD-Verbindung (nur lesend)."""
    config = _lade_config(config_pfad)
    console.print(f"[green]✔[/] Konfiguration gelesen: {config_pfad}")
    try:
        with AdVerbindung(config) as ad:
            console.print(f"[green]✔[/] Verbunden mit {config.ldap.server} (TLS aktiv)")
            if ad.basis_existiert():
                konten = ad.lade_ist_konten()
                console.print(
                    f"[green]✔[/] Basis-OU vorhanden: {config.basis_dn} "
                    f"({len(konten)} verwaltete Konten)"
                )
            else:
                console.print(
                    f"[yellow]⚠[/] Basis-OU {config.basis_dn} existiert noch nicht – "
                    "sie wird beim ersten [bold]apply[/] automatisch angelegt."
                )
    except LdapFehler as e:
        _fehler(str(e))


@app.command()
def plan(
    schueler_csv: Path = typer.Argument(..., help="Export der Schulverwaltung (Schüler)."),
    lehrkraefte: Path | None = typer.Option(None, help="Optionaler Lehrkräfte-Export."),
    report: Path | None = typer.Option(None, help="HTML-Diff-Report an diesen Pfad schreiben."),
    check_modus: bool = typer.Option(
        False, "--check", help="Exit-Code 3 bei Abweichungen (für Cron/Monitoring)."
    ),
    ohne_notbremse: bool = typer.Option(
        False, "--ohne-notbremse",
        help="Notbremse gegen unvollständige Exporte deaktivieren.",
    ),
    config_pfad: Path = ConfigOption,
) -> None:
    """Zeigt, was ein Lauf ändern würde – garantiert ohne Schreibzugriff (Dry-Run)."""
    config = _lade_config(config_pfad)
    try:
        ergebnis, ad = _berechne(config, schueler_csv, lehrkraefte, ohne_notbremse)
        ad.trennen()
    except (CsvFehler, LdapFehler) as e:
        _fehler(str(e))
        return
    zeige_plan(ergebnis, config.ldap.base_dn)
    if report:
        schreibe_report(
            ergebnis, config, str(schueler_csv), report, datetime.now(), modus="Plan (Dry-Run)"
        )
        console.print(f"[green]✔[/] HTML-Report: [bold]{report}[/]")
    if ergebnis.konflikte:
        raise typer.Exit(2)
    if check_modus and not ergebnis.leer:
        raise typer.Exit(3)


@app.command()
def apply(
    schueler_csv: Path = typer.Argument(..., help="Export der Schulverwaltung (Schüler)."),
    lehrkraefte: Path | None = typer.Option(None, help="Optionaler Lehrkräfte-Export."),
    ja: bool = typer.Option(False, "--ja", help="Plan ohne Rückfrage ausführen."),
    report: Path | None = typer.Option(None, help="HTML-Report an diesen Pfad schreiben."),
    ohne_notbremse: bool = typer.Option(
        False, "--ohne-notbremse",
        help="Notbremse gegen unvollständige Exporte deaktivieren.",
    ),
    config_pfad: Path = ConfigOption,
) -> None:
    """Führt den Plan aus: legt an, verschiebt, deaktiviert – nach Bestätigung."""
    config = _lade_config(config_pfad)
    heute = date.today()
    try:
        ergebnis, ad = _berechne(config, schueler_csv, lehrkraefte, ohne_notbremse)
    except (CsvFehler, LdapFehler) as e:
        _fehler(str(e))
        return

    try:
        zeige_plan(ergebnis, config.ldap.base_dn)
        if ergebnis.konflikte:
            _fehler(
                "Der Plan enthält Konflikte – bitte zuerst klären. Es wurde nichts geändert.",
                code=2,
            )
        if ergebnis.leer:
            console.print("[green]Nichts zu tun.[/]")
            return
        if not ja and not typer.confirm(
            f"{ergebnis.anzahl_aenderungen} Änderungen an {config.ldap.base_dn} ausführen?"
        ):
            console.print("Abgebrochen – es wurde nichts geändert.")
            raise typer.Exit(0)

        resultat = wende_plan_an(ergebnis, ad, config, heute)
    finally:
        ad.trennen()

    if resultat.struktur_neu:
        console.print(f"[green]✔[/] Struktur ergänzt: {len(resultat.struktur_neu)} Objekte")
    console.print(
        f"[green]✔ Ausgeführt:[/] {len(resultat.angelegt)} angelegt, "
        f"{resultat.verschoben} verschoben, {resultat.umbenannt} umbenannt, "
        f"{resultat.reaktiviert} reaktiviert, {resultat.deaktiviert} deaktiviert"
    )

    if resultat.angelegt:
        zugangsdaten = Path(f"zugangsdaten-{heute.isoformat()}.csv")
        schreibe_zugangsdaten(resultat.angelegt, zugangsdaten, heute)
        console.print(
            Panel(
                f"Initialpasswörter: [bold]{zugangsdaten}[/] (Dateimodus 0600)\n"
                f"Briefe drucken:    [bold]schulsync briefe {zugangsdaten}[/]\n"
                "Danach die Datei löschen – die Passwörter gelten nur bis zur ersten Anmeldung.",
                title="Vertraulich",
                border_style="yellow",
            )
        )

    if report:
        schreibe_report(
            ergebnis, config, str(schueler_csv), report, datetime.now(), modus="Apply (ausgeführt)"
        )
        console.print(f"[green]✔[/] HTML-Report: [bold]{report}[/]")

    if resultat.fehler:
        for f in resultat.fehler:
            console.print(f"[red]✘[/] {f}")
        _fehler(f"{len(resultat.fehler)} Aktionen fehlgeschlagen (Details oben).")


@app.command()
def briefe(
    zugangsdaten: Path = typer.Argument(..., help="Zugangsdaten-CSV aus 'schulsync apply'."),
    ziel: Path = typer.Option(Path("briefe"), help="Zielordner für die HTML-Briefe."),
    loeschen: bool = typer.Option(
        False, "--loeschen", help="Zugangsdaten-CSV nach Erzeugung der Briefe löschen."
    ),
    config_pfad: Path = ConfigOption,
) -> None:
    """Erzeugt druckfertige Zugangsdaten-Briefe (eine HTML-Datei pro Klasse)."""
    config = _lade_config(config_pfad)
    if not zugangsdaten.exists():
        _fehler(f"'{zugangsdaten}' nicht gefunden.")
    konten = lese_zugangsdaten(zugangsdaten)
    if not konten:
        _fehler(f"'{zugangsdaten}' enthält keine Konten.")
    dateien = schreibe_briefe(konten, config, ziel, datum=date.today().strftime("%d.%m.%Y"))
    for datei in dateien:
        console.print(f"[green]✔[/] {datei}")
    console.print(
        f"{len(konten)} Briefe in {len(dateien)} Dateien – im Browser öffnen und drucken."
    )
    if loeschen:
        zugangsdaten.unlink()
        console.print(f"[green]✔[/] {zugangsdaten} gelöscht (Passwörter nur noch auf Papier).")
    else:
        console.print(
            f"[yellow]⚠[/] Denken Sie daran, [bold]{zugangsdaten}[/] nach dem Druck zu löschen "
            "(oder gleich [bold]--loeschen[/] verwenden)."
        )


@app.command()
def cleanup(
    ja: bool = typer.Option(False, "--ja", help="Ohne Rückfrage löschen."),
    config_pfad: Path = ConfigOption,
) -> None:
    """Löscht Abgänger-Konten, deren Aufbewahrungsfrist abgelaufen ist (Löschkonzept)."""
    config = _lade_config(config_pfad)
    frist = config.aufbewahrung.abgaenger_tage
    try:
        with AdVerbindung(config) as ad:
            ist = ad.lade_ist_konten()
            zu_loeschen, wartend = berechne_cleanup(ist, date.today(), frist)
            if wartend:
                console.print(
                    f"[dim]{len(wartend)} Abgänger-Konten noch in der {frist}-Tage-Frist.[/]"
                )
            if not zu_loeschen:
                console.print("[green]✔ Nichts zu löschen.[/]")
                return
            t = Table(title=f"Endgültig löschen ({len(zu_loeschen)})", border_style="red",
                      title_justify="left")
            t.add_column("Name")
            t.add_column("Benutzername")
            t.add_column("Deaktiviert am")
            for eintrag in zu_loeschen:
                t.add_row(
                    eintrag.konto.anzeigename,
                    eintrag.konto.benutzername,
                    eintrag.deaktiviert_am.isoformat(),
                )
            console.print(t)
            if not ja and not typer.confirm(
                f"{len(zu_loeschen)} Konten endgültig löschen (Frist: {frist} Tage abgelaufen)?"
            ):
                console.print("Abgebrochen – es wurde nichts gelöscht.")
                raise typer.Exit(0)
            for eintrag in zu_loeschen:
                ad.loesche(eintrag.konto.dn)
            console.print(f"[green]✔ {len(zu_loeschen)} Konten gelöscht.[/]")
    except LdapFehler as e:
        _fehler(str(e))


if __name__ == "__main__":
    app()
