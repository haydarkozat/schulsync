"""Integrationstest: der komplette Schuljahreswechsel gegen einen echten
Samba-AD-DC – von der leeren Domäne bis zur DSGVO-konformen Löschung.

Die Geschichte:
  2025  Erstbefüllung: 149 Schüler:innen + 5 Lehrkräfte
  2025' Idempotenz: derselbe Export noch einmal ⇒ nichts zu tun
  2026  Schuljahreswechsel: 24 neue 5er, 125 rücken auf, 24 Abgänger,
        2 Namensänderungen
  2026' Eine Abgängerin kehrt zurück ⇒ Reaktivierung statt Duplikat
  Ende  cleanup nach Fristablauf ⇒ Konten sind wirklich weg
"""

from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from schulsync.cli import app

WURZEL = Path(__file__).resolve().parents[2]
LAB_CONFIG = WURZEL / "lab" / "schulsync.lab.yaml"
BEISPIELE = WURZEL / "examples"

pytestmark = pytest.mark.integration

runner = CliRunner()


def _cli(*args: str) -> object:
    ergebnis = runner.invoke(app, [*args, "--config", str(LAB_CONFIG)])
    assert ergebnis.exit_code in (0, 3), (
        f"Exit {ergebnis.exit_code} bei {args}:\n{ergebnis.output}"
    )
    return ergebnis


def _text(ergebnis) -> str:
    """CLI-Ausgabe mit normalisiertem Whitespace (Rich bricht Zeilen um)."""
    return " ".join(ergebnis.output.split())


def _konto(ad, benutzername: str):
    konten = {k.benutzername: k for k in ad.lade_ist_konten()}
    return konten.get(benutzername)


def test_kompletter_schuljahreswechsel(ad, lab_config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # zugangsdaten-*.csv landet im Testordner
    export_2025 = str(BEISPIELE / "schild-export-2025.csv")
    export_2026 = str(BEISPIELE / "schild-export-2026.csv")
    export_rueckkehr = str(BEISPIELE / "schild-export-2026-nachzuegler.csv")
    lehrer = str(BEISPIELE / "lehrkraefte.csv")

    # ---- check: Verbindung steht, Basis-OU fehlt noch ----------------------
    ergebnis = _cli("check")
    assert "existiert noch nicht" in ergebnis.output

    # ---- 2025: Erstbefüllung ------------------------------------------------
    ergebnis = _cli("apply", export_2025, "--lehrkraefte", lehrer, "--ja")
    assert "154 angelegt" in _text(ergebnis)

    konten = ad.lade_ist_konten()
    assert len(konten) == 154
    assert all(k.aktiv for k in konten)

    # Kollisionstrio Emma Fischer: Lehrkraft zuerst (sortiert vor Klassen):
    namen = {k.benutzername for k in konten}
    assert {"emma.fischer", "emma.fischer2", "emma.fischer3"} <= namen

    # Transliteration am lebenden Objekt:
    assert "lukasz.wroblewski" in namen  # Łukasz Wróblewski
    assert "francois.n-diaye" in namen  # François N'Diaye
    assert "konstantin-alexander" in namen  # exakt an der 20-Zeichen-Grenze

    # Stichprobe: OU, Gruppen, Attribute
    stichprobe = _konto(ad, "lukasz.wroblewski")
    assert stichprobe.klasse == "5A"
    gruppen = set(ad.gruppen_von(stichprobe.dn))
    assert {"Klasse-5A", "Alle-Schueler"} <= gruppen

    # ---- Idempotenz: gleicher Export ⇒ leerer Plan --------------------------
    ergebnis = _cli("plan", export_2025, "--lehrkraefte", lehrer, "--check")
    assert ergebnis.exit_code == 0, "Zweiter Lauf muss leer sein (Idempotenz!)"
    assert "Keine Abweichungen" in ergebnis.output

    # ---- 2026: der eigentliche Schuljahreswechsel ---------------------------
    report = tmp_path / "report-2026.html"
    ergebnis = _cli(
        "apply", export_2026, "--lehrkraefte", lehrer, "--ja", "--report", str(report)
    )
    text = _text(ergebnis)
    assert "24 angelegt" in text
    assert "125 verschoben" in text
    assert "2 umbenannt" in text
    assert "24 deaktiviert" in text
    assert report.exists() and "Klassenwechsel" in report.read_text(encoding="utf-8")

    # Aufgerückt: aus der 5A wurde die 6A – Gruppen wurden getauscht:
    stichprobe = _konto(ad, "lukasz.wroblewski")
    assert stichprobe.klasse == "6A"
    gruppen = set(ad.gruppen_von(stichprobe.dn))
    assert "Klasse-6A" in gruppen and "Klasse-5A" not in gruppen

    # Abgänger: deaktiviert, in der Abgänger-OU, mit Frist-Stempel:
    abgaenger = [k for k in ad.lade_ist_konten() if not k.aktiv]
    assert len(abgaenger) == 24
    assert all(k.klasse is None for k in abgaenger)
    assert all(k.deaktiviert_am == date.today() for k in abgaenger)
    assert all("Abgaenger" in k.dn for k in abgaenger)
    assert all(not ad.gruppen_von(k.dn) for k in abgaenger[:3])  # keine Gruppen mehr

    # Namensänderung: Benutzername blieb stabil:
    umbenannt = [k for k in ad.lade_ist_konten() if k.nachname == "Schmidt-Yılmaz"]
    assert len(umbenannt) == 1

    # ---- Rückkehrerin: Reaktivierung statt Duplikat -------------------------
    ergebnis = _cli("apply", export_rueckkehr, "--lehrkraefte", lehrer, "--ja")
    assert "1 reaktiviert" in _text(ergebnis)
    nachher = [k for k in ad.lade_ist_konten() if not k.aktiv]
    assert len(nachher) == 23  # eine weniger als vorher
    assert len(ad.lade_ist_konten()) == 178  # kein Duplikat entstanden (154 + 24 neue)

    # ---- cleanup: erst nach Fristablauf wird gelöscht -----------------------
    ergebnis = _cli("cleanup", "--ja")
    assert "Nichts zu löschen" in ergebnis.output  # Frist (90 Tage) läuft noch

    # Frist künstlich ablaufen lassen: Stempel 91 Tage in die Vergangenheit
    from datetime import timedelta

    from ldap3 import MODIFY_REPLACE

    from schulsync.ldapclient import deaktivierungs_stempel

    alt = date.today() - timedelta(days=91)
    for k in [k for k in ad.lade_ist_konten() if not k.aktiv]:
        ad.conn.modify(
            k.dn, {"description": [(MODIFY_REPLACE, [deaktivierungs_stempel(alt, 90)])]}
        )

    ergebnis = _cli("cleanup", "--ja")
    assert "23 Konten gelöscht" in _text(ergebnis)
    # 178 gesamt − 23 endgültig gelöscht = 155 Konten bleiben (alle aktiv):
    verbleibend = ad.lade_ist_konten()
    assert len(verbleibend) == 155
    assert all(k.aktiv for k in verbleibend)


def test_zugangsdaten_und_briefe(ad, lab_config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mini = tmp_path / "mini.csv"
    mini.write_text(
        "Interne ID-Nummer;Nachname;Vorname;Klasse\n"
        "501;Öztürk;Ayşe;5A\n"
        "502;Groß;Jürgen;5A\n",
        encoding="utf-8",
    )
    _cli("apply", str(mini), "--ja")

    zugangsdaten = list(tmp_path.glob("zugangsdaten-*.csv"))
    assert len(zugangsdaten) == 1
    inhalt = zugangsdaten[0].read_text(encoding="utf-8")
    assert "ayse.oeztuerk" in inhalt
    assert oct(zugangsdaten[0].stat().st_mode)[-3:] == "600"  # vertraulich!

    _cli("briefe", str(zugangsdaten[0]), "--ziel", str(tmp_path / "briefe"), "--loeschen")
    briefe = list((tmp_path / "briefe").glob("*.html"))
    assert len(briefe) == 1  # eine Datei pro Klasse
    html = briefe[0].read_text(encoding="utf-8")
    assert "Ayşe Öztürk" in html and "Startpasswort" in html
    assert not zugangsdaten[0].exists()  # --loeschen hat aufgeräumt


def test_notbremse_verhindert_massendeaktivierung(ad, lab_config, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _cli("apply", str(BEISPIELE / "schild-export-2025.csv"), "--ja")

    # »Kaputter« Export: nur noch eine Klasse drin
    kaputt = tmp_path / "kaputt.csv"
    zeilen = (BEISPIELE / "schild-export-2025.csv").read_text(encoding="utf-8").splitlines()
    kaputt.write_text("\n".join(zeilen[:14]) + "\n", encoding="utf-8")

    ergebnis = runner.invoke(app, ["apply", str(kaputt), "--ja", "--config", str(LAB_CONFIG)])
    assert ergebnis.exit_code == 2  # Konflikt – nichts wurde geändert
    assert "unvollständigen Export" in ergebnis.output
    assert sum(1 for k in ad.lade_ist_konten() if k.aktiv) == 149  # alle noch aktiv


def test_passwort_richtlinie_wird_erfuellt(ad):
    """Samba lehnt zu schwache unicodePwd ab – wenn Anlegen klappt,
    erfüllt unser Generator die AD-Komplexitätsrichtlinie."""
    from schulsync.models import Rolle

    ad.stelle_struktur_sicher({"5A"})
    from schulsync.passwords import erzeuge_passwort

    dn = ad.lege_benutzer_an(
        benutzername="pw.probe",
        vorname="Pia",
        nachname="Probe",
        quell_id="999",
        rolle=Rolle.SCHUELER,
        eltern_dn=ad.config.klassen_dn("5A"),
        passwort=erzeuge_passwort(),
    )
    konto = _konto(ad, "pw.probe")
    assert konto is not None and konto.aktiv
    # pwdLastSet=0: Passwortwechsel bei erster Anmeldung wird erzwungen.
    # (ldap3 formatiert den Wert 0 als Windows-Epoche 1601-01-01.)
    ad.conn.search(dn, "(objectClass=user)", search_scope="BASE", attributes=["pwdLastSet"])
    roh = str(ad.conn.entries[0]["pwdLastSet"].value)
    assert roh == "0" or roh.startswith("1601-01-01")
