#!/usr/bin/env python3
"""Erzeugt die README-Bilder (SVG) aus *echten* SchulSync-Läufen gegen
das Docker-Lab – keine gestellten Screenshots.

Voraussetzung:
    cd lab && docker compose up -d --wait
    export SCHULSYNC_LDAP_PASSWORT="Lab-Kennwort-2026"

Ablauf:
    1. Lab-OU leeren, Schuljahr 2025/26 einspielen (unsichtbar)
    2. `plan` für 2026/27 aufzeichnen  → docs/images/plan-2026.svg
    3. `apply` für 2026/27 aufzeichnen → docs/images/apply-2026.svg
       + HTML-Report                   → docs/beispiel-report.html
    4. Idempotenz-Lauf aufzeichnen     → docs/images/plan-idempotent.svg
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL / "src"))

import schulsync.cli as cli  # noqa: E402
from schulsync.cli import app  # noqa: E402
from schulsync.config import lade_config  # noqa: E402
from schulsync.ldapclient import AdVerbindung  # noqa: E402

LAB = str(WURZEL / "lab" / "schulsync.lab.yaml")
BEISPIELE = WURZEL / "examples"
BILDER = WURZEL / "docs" / "images"
runner = CliRunner()


def _leere_lab_ou(config) -> None:
    from ldap3 import SUBTREE
    from ldap3.core.exceptions import LDAPNoSuchObjectResult

    with AdVerbindung(config) as ad:
        try:
            ad.conn.search(config.basis_dn, "(objectClass=*)", search_scope=SUBTREE,
                           attributes=[])
        except LDAPNoSuchObjectResult:
            return
        for dn in sorted((str(e.entry_dn) for e in ad.conn.entries),
                         key=lambda d: -d.count(",")):
            ad.conn.delete(dn)


def _aufzeichnen(befehl: list[str], datei: str, titel: str) -> None:
    """Führt einen CLI-Befehl mit aufzeichnender Konsole aus und
    exportiert die Ausgabe als SVG."""
    rec = Console(record=True, width=96, force_terminal=True)
    cli.console = rec  # die CLI schreibt jetzt in die Aufzeichnung
    ergebnis = runner.invoke(app, [*befehl, "--config", LAB])
    if ergebnis.exit_code not in (0, 3):
        print(ergebnis.output)
        raise SystemExit(f"Befehl {befehl} scheiterte mit Exit {ergebnis.exit_code}")
    pfad = BILDER / datei
    rec.save_svg(str(pfad), title=titel)
    print(f"  {pfad.relative_to(WURZEL)}")


def main() -> None:
    os.environ.setdefault("SCHULSYNC_LDAP_PASSWORT", "Lab-Kennwort-2026")
    os.chdir(WURZEL)  # zugangsdaten-*.csv landet im Repo-Wurzelverzeichnis (gitignored)
    BILDER.mkdir(parents=True, exist_ok=True)
    export_2025 = str(BEISPIELE / "schild-export-2025.csv")
    export_2026 = str(BEISPIELE / "schild-export-2026.csv")
    lehrer = str(BEISPIELE / "lehrkraefte.csv")

    print("Bereite Lab vor (Schuljahr 2025/26 einspielen) …")
    _leere_lab_ou(lade_config(LAB))
    with open(os.devnull, "w") as leer:
        cli.console = Console(file=leer, force_terminal=True)
        ergebnis = runner.invoke(
            app, ["apply", export_2025, "--lehrkraefte", lehrer, "--ja", "--config", LAB]
        )
        assert ergebnis.exit_code == 0, ergebnis.output

    print("Zeichne auf …")
    _aufzeichnen(
        ["plan", export_2026, "--lehrkraefte", lehrer],
        "plan-2026.svg",
        "schulsync plan schild-export-2026.csv",
    )
    _aufzeichnen(
        ["apply", export_2026, "--lehrkraefte", lehrer, "--ja",
         "--report", "docs/beispiel-report.html"],
        "apply-2026.svg",
        "schulsync apply schild-export-2026.csv --ja",
    )
    print("  docs/beispiel-report.html")
    _aufzeichnen(
        ["plan", export_2026, "--lehrkraefte", lehrer],
        "plan-idempotent.svg",
        "schulsync plan – zweiter Lauf (idempotent)",
    )
    print("Fertig.")


if __name__ == "__main__":
    main()
