"""Konfiguration von SchulSync (``schulsync.yaml``).

Sicherheitsprinzip: Das LDAP-Passwort steht **niemals** in der Datei,
sondern ausschließlich in der Umgebungsvariable ``SCHULSYNC_LDAP_PASSWORT``.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

PASSWORT_ENV = "SCHULSYNC_LDAP_PASSWORT"


class LdapConfig(BaseModel):
    server: str = "ldaps://dc1.schule.local"
    bind_benutzer: str = "Administrator@schule.local"
    base_dn: str = "DC=schule,DC=local"
    tls_verifizieren: bool = True  # nur im Lab mit Self-Signed-Zertifikat: false
    zeitlimit_sekunden: int = 10

    @property
    def passwort(self) -> str:
        pw = os.environ.get(PASSWORT_ENV, "")
        if not pw:
            raise KonfigFehler(
                f"LDAP-Passwort fehlt. Bitte Umgebungsvariable {PASSWORT_ENV} setzen – "
                "Passwörter gehören nicht in Konfigurationsdateien."
            )
        return pw


class StrukturConfig(BaseModel):
    """OU- und Gruppenlayout unterhalb von base_dn.

    Standard-Layout::

        OU=SchulSync
        ├── OU=Schueler
        │   ├── OU=5A …            (je Klasse eine OU)
        ├── OU=Lehrkraefte
        └── OU=Abgaenger           (deaktivierte Konten, Aufbewahrungsfrist)
    """

    basis_ou: str = "SchulSync"
    schueler_ou: str = "Schueler"
    lehrkraefte_ou: str = "Lehrkraefte"
    abgaenger_ou: str = "Abgaenger"
    klassen_gruppen_praefix: str = "Klasse-"
    gruppe_alle_schueler: str = "Alle-Schueler"
    gruppe_alle_lehrkraefte: str = "Alle-Lehrkraefte"


class KontenConfig(BaseModel):
    benutzername_schema: str = "{vorname}.{nachname}"
    upn_suffix: str = "@schule.local"
    # Optional: Home-Verzeichnis-Attribute (Anlage der Ordner übernimmt der Fileserver)
    home_laufwerk: str | None = None  # z. B. "H:"
    home_pfad: str | None = None  # z. B. r"\\fs01\homes\{benutzername}"
    passwort_woerter: int = 2

    @field_validator("upn_suffix")
    @classmethod
    def _upn_mit_at(cls, v: str) -> str:
        if not v.startswith("@"):
            raise ValueError("upn_suffix muss mit '@' beginnen, z. B. '@schule.local'")
        return v


class AufbewahrungConfig(BaseModel):
    """Löschkonzept: Abgänger-Konten werden nach Ablauf der Frist durch
    ``schulsync cleanup`` endgültig gelöscht (Art. 5 & 17 DSGVO)."""

    abgaenger_tage: int = Field(default=90, ge=0)


class CsvConfig(BaseModel):
    profil: str = "schild-nrw"  # schild-nrw | asv-bw | generisch
    # nur bei profil: generisch nötig – eigene Spaltenzuordnung:
    spalten: dict[str, str] | None = None
    trennzeichen: str | None = None  # None = automatisch erkennen


class SchuleConfig(BaseModel):
    """Angaben für Berichte und Zugangsdaten-Briefe."""

    name: str = "Muster-Realschule"
    it_kontakt: str = "IT-Support, Zimmer 042"


class Config(BaseModel):
    ldap: LdapConfig = Field(default_factory=LdapConfig)
    struktur: StrukturConfig = Field(default_factory=StrukturConfig)
    konten: KontenConfig = Field(default_factory=KontenConfig)
    aufbewahrung: AufbewahrungConfig = Field(default_factory=AufbewahrungConfig)
    csv: CsvConfig = Field(default_factory=CsvConfig)
    schule: SchuleConfig = Field(default_factory=SchuleConfig)

    # --- abgeleitete DNs ---------------------------------------------------
    @property
    def basis_dn(self) -> str:
        return f"OU={self.struktur.basis_ou},{self.ldap.base_dn}"

    @property
    def schueler_dn(self) -> str:
        return f"OU={self.struktur.schueler_ou},{self.basis_dn}"

    @property
    def lehrkraefte_dn(self) -> str:
        return f"OU={self.struktur.lehrkraefte_ou},{self.basis_dn}"

    @property
    def abgaenger_dn(self) -> str:
        return f"OU={self.struktur.abgaenger_ou},{self.basis_dn}"

    def klassen_dn(self, klasse: str) -> str:
        return f"OU={klasse},{self.schueler_dn}"

    def klassen_gruppe(self, klasse: str) -> str:
        return f"{self.struktur.klassen_gruppen_praefix}{klasse}"


class KonfigFehler(Exception):
    """Verständlicher Konfigurationsfehler für die CLI."""


def lade_config(pfad: Path | str = "schulsync.yaml") -> Config:
    pfad = Path(pfad)
    if not pfad.exists():
        raise KonfigFehler(
            f"Konfigurationsdatei '{pfad}' nicht gefunden. "
            "Vorlage: examples/schulsync.example.yaml"
        )
    try:
        daten = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as e:
        raise KonfigFehler(f"'{pfad}' ist kein gültiges YAML: {e}") from e
    return Config.model_validate(daten)
