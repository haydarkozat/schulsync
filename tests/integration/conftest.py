"""Fixtures für die Integrationstests gegen den Docker-Lab-DC.

Start:  cd lab && docker compose up -d --wait
Lauf:   pytest -m integration
"""

from pathlib import Path

import pytest

from schulsync.config import PASSWORT_ENV, Config, lade_config
from schulsync.ldapclient import AdVerbindung, LdapFehler

WURZEL = Path(__file__).resolve().parents[2]
LAB_CONFIG = WURZEL / "lab" / "schulsync.lab.yaml"
LAB_PASSWORT = "Lab-Kennwort-2026"
BEISPIELE = WURZEL / "examples"


@pytest.fixture(scope="session")
def lab_config(session_env) -> Config:
    return lade_config(LAB_CONFIG)


@pytest.fixture(scope="session")
def session_env():
    import os

    os.environ.setdefault(PASSWORT_ENV, LAB_PASSWORT)
    yield


def _loesche_teilbaum(ad: AdVerbindung, basis_dn: str) -> None:
    """Löscht die Basis-OU samt Inhalt (tiefste DNs zuerst)."""
    from ldap3 import SUBTREE
    from ldap3.core.exceptions import LDAPNoSuchObjectResult

    try:
        ad.conn.search(basis_dn, "(objectClass=*)", search_scope=SUBTREE, attributes=[])
    except LDAPNoSuchObjectResult:
        return
    dns = sorted((str(e.entry_dn) for e in ad.conn.entries), key=lambda d: -d.count(","))
    for dn in dns:
        ad.conn.delete(dn)


@pytest.fixture()
def ad(lab_config: Config) -> AdVerbindung:
    """Frische Verbindung mit leerer SchulSync-OU – jeder Test startet bei null."""
    verbindung = AdVerbindung(lab_config)
    try:
        verbindung.verbinden()
    except LdapFehler:
        pytest.skip(
            "Lab-DC nicht erreichbar – zuerst starten: cd lab && docker compose up -d --wait"
        )
    _loesche_teilbaum(verbindung, lab_config.basis_dn)
    yield verbindung
    verbindung.trennen()
