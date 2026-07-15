"""Benutzernamen: Transliteration, 20-Zeichen-Grenze, Kollisionen."""

import pytest

from schulsync.usernames import SAM_MAX, erzeuge_benutzername, transliteriere


@pytest.mark.parametrize(
    ("roh", "erwartet"),
    [
        ("Müller", "mueller"),
        ("Groß", "gross"),
        ("Yılmaz", "yilmaz"),
        ("Şahin", "sahin"),
        ("Öztürk", "oeztuerk"),
        ("Çelik", "celik"),
        ("Đorđević", "dordevic"),
        ("Zieliński", "zielinski"),
        ("Wróblewski", "wroblewski"),
        ("François", "francois"),
        ("N'Diaye", "n-diaye"),
        ("von der Heide", "von-der-heide"),
        ("Ærø", "aeroe"),
    ],
)
def test_transliteration(roh: str, erwartet: str):
    assert transliteriere(roh) == erwartet


def test_einfacher_benutzername():
    assert erzeuge_benutzername("Emma", "Fischer") == "emma.fischer"


def test_rufname_bei_mehreren_vornamen():
    assert erzeuge_benutzername("Anna Maria", "Weber") == "anna.weber"


def test_kollision_bekommt_zaehler():
    vergeben = {"emma.fischer"}
    assert erzeuge_benutzername("Emma", "Fischer", vergeben=vergeben) == "emma.fischer2"
    vergeben.add("emma.fischer2")
    assert erzeuge_benutzername("Emma", "Fischer", vergeben=vergeben) == "emma.fischer3"


def test_kollision_ist_case_insensitiv():
    # sAMAccountName ist im AD case-insensitiv – wir müssen es auch sein.
    assert erzeuge_benutzername("Emma", "Fischer", vergeben={"Emma.Fischer"}) == "emma.fischer2"


def test_sam_account_grenze_wird_eingehalten():
    name = erzeuge_benutzername("Konstantin-Alexander", "Wagenknecht")
    assert len(name) <= SAM_MAX
    assert name == "konstantin-alexander"  # exakt 20 Zeichen – die Grenze selbst ist erlaubt


def test_sam_account_grenze_mit_kollision():
    erster = erzeuge_benutzername("Konstantin-Alexander", "Wagenknecht")
    zweiter = erzeuge_benutzername("Konstantin-Alexander", "Wagenknecht", vergeben={erster})
    assert len(zweiter) <= SAM_MAX
    assert zweiter.endswith("2")
    assert zweiter != erster


def test_deterministisch():
    a = erzeuge_benutzername("Ayşe", "Öztürk", vergeben={"x"})
    b = erzeuge_benutzername("Ayşe", "Öztürk", vergeben={"x"})
    assert a == b == "ayse.oeztuerk"


def test_unbrauchbarer_name_wirft_fehler():
    with pytest.raises(ValueError):
        erzeuge_benutzername("...", "---")
