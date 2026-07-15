"""Der Planner: Soll/Ist-Vergleich, Notbremse, Cleanup-Fristen."""

from datetime import date

from schulsync.models import IstKonto, Rolle, SollPerson
from schulsync.planner import berechne_cleanup, berechne_plan


def soll(quell_id: str, vorname: str, nachname: str, klasse: str | None = "5A") -> SollPerson:
    return SollPerson(
        quell_id=quell_id, vorname=vorname, nachname=nachname,
        rolle=Rolle.SCHUELER if klasse else Rolle.LEHRKRAFT, klasse=klasse,
    )


def ist(
    quell_id: str | None,
    vorname: str,
    nachname: str,
    klasse: str | None = "5A",
    aktiv: bool = True,
    deaktiviert_am: date | None = None,
) -> IstKonto:
    benutzer = f"{vorname}.{nachname}".lower()
    return IstKonto(
        dn=f"CN={benutzer},OU={klasse or 'Abgaenger'},DC=test",
        benutzername=benutzer, quell_id=quell_id, vorname=vorname, nachname=nachname,
        rolle=Rolle.SCHUELER, klasse=klasse, aktiv=aktiv, deaktiviert_am=deaktiviert_am,
    )


def test_leeres_ad_heisst_alles_anlegen():
    plan = berechne_plan([soll("1", "Emma", "Fischer")], [], set())
    assert len(plan.anlegen) == 1
    assert plan.anlegen[0].benutzername == "emma.fischer"
    assert plan.leer is False


def test_identischer_zustand_heisst_nichts_tun():
    plan = berechne_plan(
        [soll("1", "Emma", "Fischer")], [ist("1", "Emma", "Fischer")], {"emma.fischer"}
    )
    assert plan.leer
    assert plan.unveraendert == 1


def test_klassenwechsel_wird_erkannt():
    plan = berechne_plan(
        [soll("1", "Emma", "Fischer", "6A")], [ist("1", "Emma", "Fischer", "5A")], set()
    )
    assert len(plan.verschieben) == 1
    v = plan.verschieben[0]
    assert (v.von_klasse, v.nach_klasse) == ("5A", "6A")


def test_namensaenderung_wird_erkannt():
    plan = berechne_plan(
        [soll("1", "Emma", "Schmidt-Yılmaz")], [ist("1", "Emma", "Fischer")], set()
    )
    assert len(plan.umbenennen) == 1
    assert plan.umbenennen[0].neuer_nachname == "Schmidt-Yılmaz"
    # Benutzername bleibt stabil – niemand muss sich neu anmelden:
    assert not plan.anlegen and not plan.deaktivieren


def test_fehlender_eintrag_heisst_abgaenger():
    plan = berechne_plan([], [ist("1", "Emma", "Fischer")], set(), notbremse=False)
    assert len(plan.deaktivieren) == 1


def test_rueckkehrer_wird_reaktiviert_statt_neu_angelegt():
    konto = ist("1", "Emma", "Fischer", klasse=None, aktiv=False,
                deaktiviert_am=date(2026, 7, 1))
    plan = berechne_plan([soll("1", "Emma", "Fischer", "10A")], [konto], {"emma.fischer"})
    assert len(plan.reaktivieren) == 1
    assert plan.reaktivieren[0].nach_klasse == "10A"
    assert not plan.anlegen  # kein Duplikat!


def test_kollision_im_selben_lauf_bekommt_zaehler():
    plan = berechne_plan(
        [soll("1", "Emma", "Fischer", "7A"), soll("2", "Emma", "Fischer", "8B")], [], set()
    )
    namen = sorted(a.benutzername for a in plan.anlegen)
    assert namen == ["emma.fischer", "emma.fischer2"]


def test_kollision_mit_fremdem_domaenenkonto():
    # hausmeister-Konto gehört nicht SchulSync, blockiert aber den Namen:
    plan = berechne_plan([soll("1", "Emma", "Fischer")], [], {"emma.fischer"})
    assert plan.anlegen[0].benutzername == "emma.fischer2"


def test_konto_ohne_quell_id_ist_konflikt():
    fremd = ist(None, "Alt", "Bestand")
    plan = berechne_plan([], [fremd], set(), notbremse=False)
    assert len(plan.konflikte) == 1
    assert not plan.deaktivieren  # wird sicherheitshalber NICHT angefasst


def test_doppelte_quell_id_im_ad_ist_konflikt():
    plan = berechne_plan(
        [], [ist("1", "Emma", "Fischer"), ist("1", "Ben", "Weber")], set(), notbremse=False
    )
    assert len(plan.konflikte) == 1


def test_notbremse_bei_verdaechtig_leerem_export():
    bestand = [ist(str(i), "Kind", f"Nr{i}") for i in range(20)]
    plan = berechne_plan([soll("0", "Kind", "Nr0")], bestand, set())
    assert any("unvollständigen Export" in k.grund for k in plan.konflikte)


def test_notbremse_laesst_normalen_wechsel_durch():
    # 24 von 149 deaktivieren (typischer Jahrgangs-Abgang) ist kein Alarmfall.
    bestand = [ist(str(i), "Kind", f"Nr{i}") for i in range(149)]
    bleiben = [soll(str(i), "Kind", f"Nr{i}") for i in range(125)]
    plan = berechne_plan(bleiben, bestand, set())
    assert not plan.konflikte
    assert len(plan.deaktivieren) == 24


def test_plan_ist_deterministisch():
    soll_liste = [soll("2", "Ben", "Weber", "6B"), soll("1", "Emma", "Fischer", "5A")]
    a = berechne_plan(soll_liste, [], set())
    b = berechne_plan(list(reversed(soll_liste)), [], set())
    assert [x.benutzername for x in a.anlegen] == [x.benutzername for x in b.anlegen]


# ---------------------------------------------------------------- Cleanup


def test_cleanup_respektiert_frist():
    alt = ist("1", "Emma", "Fischer", klasse=None, aktiv=False,
              deaktiviert_am=date(2026, 1, 1))
    frisch = ist("2", "Ben", "Weber", klasse=None, aktiv=False,
                 deaktiviert_am=date(2026, 6, 20))
    loeschen, wartend = berechne_cleanup([alt, frisch], heute=date(2026, 7, 15), frist_tage=90)
    assert [e.konto.quell_id for e in loeschen] == ["1"]
    assert [w.quell_id for w in wartend] == ["2"]


def test_cleanup_loescht_nie_ohne_stempel():
    ohne_stempel = ist("1", "Emma", "Fischer", klasse=None, aktiv=False, deaktiviert_am=None)
    loeschen, wartend = berechne_cleanup([ohne_stempel], heute=date(2099, 1, 1), frist_tage=0)
    assert not loeschen
    assert not wartend  # taucht auch nicht als wartend auf – manuell klären


def test_cleanup_ignoriert_aktive_konten():
    aktiv = ist("1", "Emma", "Fischer", deaktiviert_am=date(2020, 1, 1))
    loeschen, _ = berechne_cleanup([aktiv], heute=date(2099, 1, 1), frist_tage=0)
    assert not loeschen
