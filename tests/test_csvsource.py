"""CSV-Einlesen: Kodierungen, Trennzeichen, Profile, Validierung."""

from pathlib import Path

import pytest

from schulsync.csvsource import CsvFehler, lese_export
from schulsync.models import Rolle

BEISPIELE = Path(__file__).resolve().parent.parent / "examples"


def _schreibe(tmp_path: Path, inhalt: str, kodierung: str = "utf-8") -> Path:
    pfad = tmp_path / "export.csv"
    pfad.write_bytes(inhalt.encode(kodierung))
    return pfad


def test_liest_utf8_beispielexport():
    ergebnis = lese_export(BEISPIELE / "schild-export-2025.csv", Rolle.SCHUELER)
    assert ergebnis.kodierung == "utf-8-sig"
    assert ergebnis.trennzeichen == ";"
    assert len(ergebnis.personen) == 149
    assert all(p.rolle is Rolle.SCHUELER for p in ergebnis.personen)


def test_erkennt_windows_1252():
    ergebnis = lese_export(BEISPIELE / "schild-export-legacy-cp1252.csv", Rolle.SCHUELER)
    assert ergebnis.kodierung == "cp1252"
    namen = {p.nachname for p in ergebnis.personen}
    assert "Müller" in namen  # Umlaut hat die Kodierungserkennung überlebt
    assert "Béringer" in namen


def test_erkennt_komma_als_trennzeichen(tmp_path):
    pfad = _schreibe(
        tmp_path,
        "Interne ID-Nummer,Nachname,Vorname,Klasse\n1,Kaya,Emir,5a\n",
    )
    ergebnis = lese_export(pfad, Rolle.SCHUELER)
    assert ergebnis.trennzeichen == ","
    assert ergebnis.personen[0].klasse == "5A"  # und normalisiert 5a → 5A
    assert ergebnis.warnungen  # Normalisierung wird gemeldet


def test_asv_bw_profil(tmp_path):
    pfad = _schreibe(
        tmp_path,
        "Schülernummer;Familienname;Rufname;Klasse\n77;Weber;Lina;7B\n",
    )
    ergebnis = lese_export(pfad, Rolle.SCHUELER, profil_name="asv-bw")
    p = ergebnis.personen[0]
    assert (p.quell_id, p.vorname, p.nachname, p.klasse) == ("77", "Lina", "Weber", "7B")


def test_generisches_profil(tmp_path):
    pfad = _schreibe(tmp_path, "id;nn;vn;kl\n5;Braun;Ida;9A\n")
    ergebnis = lese_export(
        pfad,
        Rolle.SCHUELER,
        profil_name="generisch",
        spalten={"id": "id", "nachname": "nn", "vorname": "vn", "klasse": "kl"},
    )
    assert ergebnis.personen[0].nachname == "Braun"


def test_generisches_profil_ohne_spalten_schlaegt_fehl(tmp_path):
    pfad = _schreibe(tmp_path, "a;b\n1;2\n")
    with pytest.raises(CsvFehler, match="generisch"):
        lese_export(pfad, Rolle.SCHUELER, profil_name="generisch", spalten={"id": "a"})


def test_fehlende_spalte_wird_klar_gemeldet(tmp_path):
    pfad = _schreibe(tmp_path, "Nachname;Vorname;Klasse\nKaya;Emir;5A\n")
    with pytest.raises(CsvFehler, match="Interne ID-Nummer"):
        lese_export(pfad, Rolle.SCHUELER)


def test_doppelte_id_bricht_ab(tmp_path):
    pfad = _schreibe(
        tmp_path,
        "Interne ID-Nummer;Nachname;Vorname;Klasse\n"
        "1;Kaya;Emir;5A\n"
        "1;Weber;Lina;6B\n",
    )
    with pytest.raises(CsvFehler, match="doppelt"):
        lese_export(pfad, Rolle.SCHUELER)


def test_fehlende_klasse_bei_schueler_bricht_ab(tmp_path):
    pfad = _schreibe(
        tmp_path, "Interne ID-Nummer;Nachname;Vorname;Klasse\n1;Kaya;Emir;\n"
    )
    with pytest.raises(CsvFehler, match="Klasse fehlt"):
        lese_export(pfad, Rolle.SCHUELER)


def test_lehrkraefte_brauchen_keine_klasse():
    ergebnis = lese_export(BEISPIELE / "lehrkraefte.csv", Rolle.LEHRKRAFT)
    assert len(ergebnis.personen) == 5
    assert all(p.klasse is None for p in ergebnis.personen)


def test_leere_zeilen_am_ende_werden_ignoriert(tmp_path):
    pfad = _schreibe(
        tmp_path,
        "Interne ID-Nummer;Nachname;Vorname;Klasse\n1;Kaya;Emir;5A\n;;;\n\n",
    )
    assert len(lese_export(pfad, Rolle.SCHUELER).personen) == 1


def test_unbekanntes_profil(tmp_path):
    pfad = _schreibe(tmp_path, "a;b\n")
    with pytest.raises(CsvFehler, match="Unbekanntes CSV-Profil"):
        lese_export(pfad, Rolle.SCHUELER, profil_name="gibtsnicht")
