"""HTML-Diff-Report und Zugangsdaten-Briefe (Jinja2)."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from . import __version__
from .applier import NeuesKonto
from .config import Config
from .models import Plan, Rolle

_env = Environment(
    loader=PackageLoader("schulsync", "templates"),
    autoescape=select_autoescape(["html"]),
)


def schreibe_report(
    plan: Plan,
    config: Config,
    quelle: str,
    pfad: Path,
    zeitpunkt: datetime,
    modus: str,
) -> Path:
    html = _env.get_template("report.html.j2").render(
        plan=plan,
        schule=config.schule.name,
        quelle=quelle,
        ziel=config.ldap.base_dn,
        zeitpunkt=zeitpunkt.strftime("%d.%m.%Y %H:%M"),
        modus=modus,
        frist_tage=config.aufbewahrung.abgaenger_tage,
        version=__version__,
    )
    pfad = Path(pfad)
    pfad.write_text(html, encoding="utf-8")
    return pfad


def lese_zugangsdaten(pfad: Path) -> list[NeuesKonto]:
    """Liest die von ``apply`` geschriebene Zugangsdaten-CSV wieder ein."""
    zeilen = [
        z for z in Path(pfad).read_text(encoding="utf-8").splitlines()
        if z and not z.startswith("#")
    ]
    leser = csv.DictReader(zeilen, delimiter=";")
    konten = []
    for z in leser:
        konten.append(
            NeuesKonto(
                benutzername=z["Benutzername"],
                anzeigename=z["Name"],
                klasse=z["Klasse"] or None,
                rolle=Rolle(z["Rolle"]),
                passwort=z["Initialpasswort"],
            )
        )
    return konten


def schreibe_briefe(
    konten: list[NeuesKonto],
    config: Config,
    ziel_ordner: Path,
    datum: str,
) -> list[Path]:
    """Erzeugt pro Klasse eine druckfertige HTML-Datei mit einem Brief
    pro Konto (Seitenumbruch je Brief)."""
    ziel_ordner = Path(ziel_ordner)
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    vorlage = _env.get_template("briefe.html.j2")

    nach_klasse: dict[str, list[NeuesKonto]] = {}
    for k in sorted(konten, key=lambda k: (k.klasse or "", k.anzeigename)):
        nach_klasse.setdefault(k.klasse or "ohne-Klasse", []).append(k)

    dateien: list[Path] = []
    for klasse, klassen_konten in nach_klasse.items():
        html = vorlage.render(
            konten=klassen_konten,
            klasse=klasse,
            schule=config.schule.name,
            it_kontakt=config.schule.it_kontakt,
            datum=datum,
        )
        datei = ziel_ordner / f"zugangsdaten-{klasse}.html"
        datei.write_text(html, encoding="utf-8")
        dateien.append(datei)
    return dateien
