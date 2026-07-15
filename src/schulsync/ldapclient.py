"""LDAP-Anbindung an Active Directory (Windows AD oder Samba AD DC).

Designentscheidungen (im README ausführlicher begründet):

* **CN = Benutzername**, der Anzeigename steht in ``displayName``.
  Zwei »Ben Yılmaz« in derselben Klasse wären sonst eine RDN-Kollision –
  der Benutzername ist dagegen domänenweit eindeutig, OU-Umzüge können
  nie kollidieren.
* Die Quell-ID der Schulverwaltung liegt in ``employeeNumber``,
  die Rolle in ``employeeType`` – beides Standard-AD-Attribute,
  kein Schema-Gefrickel nötig.
* Passwörter (``unicodePwd``) verlangen eine **verschlüsselte Verbindung**:
  LDAPS oder STARTTLS. Unverschlüsselt verweigert SchulSync den Dienst.
* Deaktivierte Konten bekommen einen maschinenlesbaren Stempel in
  ``description`` – daraus liest ``cleanup`` die Aufbewahrungsfrist.
"""

from __future__ import annotations

import re
import ssl
from datetime import date

from ldap3 import (
    ALL,
    MODIFY_ADD,
    MODIFY_DELETE,
    MODIFY_REPLACE,
    SIMPLE,
    SUBTREE,
    Connection,
    Server,
    Tls,
)
from ldap3.core.exceptions import (
    LDAPAttributeOrValueExistsResult,
    LDAPEntryAlreadyExistsResult,
    LDAPException,
    LDAPNoSuchAttributeResult,
    LDAPNoSuchObjectResult,
)
from ldap3.utils.conv import escape_filter_chars
from ldap3.utils.dn import escape_rdn

from .config import Config
from .models import IstKonto, Rolle

UAC_NORMAL = 0x0200  # 512
UAC_DISABLED = 0x0202  # 514 (ACCOUNTDISABLE-Bit gesetzt)
GRUPPE_GLOBAL_SECURITY = -2147483646

_STEMPEL_RE = re.compile(r"deaktiviert am (\d{4}-\d{2}-\d{2})", re.IGNORECASE)


def deaktivierungs_stempel(am: date, frist_tage: int) -> str:
    return f"SchulSync: deaktiviert am {am.isoformat()} – Löschung nach {frist_tage} Tagen Frist"


def parse_stempel(description: str | None) -> date | None:
    if not description:
        return None
    m = _STEMPEL_RE.search(description)
    return date.fromisoformat(m.group(1)) if m else None


class LdapFehler(Exception):
    """LDAP-Fehler mit verständlicher Meldung für die CLI."""


class AdVerbindung:
    """Dünne, gut testbare Schicht über ldap3 – jede Methode ist eine
    fachliche Operation, kein generischer LDAP-Wrapper."""

    def __init__(self, config: Config):
        self.config = config
        self._conn: Connection | None = None

    # ------------------------------------------------------------- Aufbau
    def verbinden(self) -> None:
        c = self.config.ldap
        url = c.server
        use_ssl = url.startswith("ldaps://")

        tls = Tls(
            validate=ssl.CERT_REQUIRED if c.tls_verifizieren else ssl.CERT_NONE,
            version=ssl.PROTOCOL_TLS_CLIENT if c.tls_verifizieren else ssl.PROTOCOL_TLS,
        )
        # ldap3 versteht vollständige LDAP-URLs inkl. Port (ldaps://host:636).
        server = Server(
            url,
            tls=tls,
            get_info=ALL,
            connect_timeout=c.zeitlimit_sekunden,
        )
        try:
            conn = Connection(
                server,
                user=c.bind_benutzer,
                password=c.passwort,
                authentication=SIMPLE,
                raise_exceptions=True,
                receive_timeout=c.zeitlimit_sekunden * 3,
                auto_bind=False,
            )
            conn.open()
            if not use_ssl:
                # Ohne Verschlüsselung keine Passwörter: STARTTLS erzwingen.
                conn.start_tls()
            conn.bind()
        except LDAPException as e:
            raise LdapFehler(
                f"Verbindung zu {url} als '{c.bind_benutzer}' fehlgeschlagen: {e}"
            ) from e
        self._conn = conn

    def trennen(self) -> None:
        if self._conn is not None:
            self._conn.unbind()
            self._conn = None

    def __enter__(self) -> AdVerbindung:
        self.verbinden()
        return self

    def __exit__(self, *exc) -> None:
        self.trennen()

    @property
    def conn(self) -> Connection:
        if self._conn is None:
            raise LdapFehler("Nicht verbunden – verbinden() zuerst aufrufen.")
        return self._conn

    # -------------------------------------------------------------- Lesen
    def basis_existiert(self) -> bool:
        try:
            return self.conn.search(
                self.config.basis_dn, "(objectClass=organizationalUnit)", search_scope="BASE"
            )
        except LDAPNoSuchObjectResult:
            return False

    def alle_benutzernamen_der_domaene(self) -> set[str]:
        """Alle sAMAccountNames der gesamten Domäne – neue Benutzernamen
        dürfen auch mit nicht von SchulSync verwalteten Konten (Sekretariat,
        Hausmeister, Dienstkonten) nicht kollidieren."""
        self.conn.search(
            self.config.ldap.base_dn,
            "(sAMAccountName=*)",
            search_scope=SUBTREE,
            attributes=["sAMAccountName"],
        )
        return {str(e["sAMAccountName"].value) for e in self.conn.entries}

    def lade_ist_konten(self) -> list[IstKonto]:
        """Liest alle von SchulSync verwalteten Konten (unterhalb der Basis-OU)."""
        if not self.basis_existiert():
            return []
        self.conn.search(
            self.config.basis_dn,
            "(&(objectCategory=person)(objectClass=user))",
            search_scope=SUBTREE,
            attributes=[
                "sAMAccountName",
                "employeeNumber",
                "employeeType",
                "givenName",
                "sn",
                "userAccountControl",
                "description",
            ],
        )
        konten: list[IstKonto] = []
        for e in self.conn.entries:
            dn = str(e.entry_dn)
            uac = int(str(e["userAccountControl"].value or UAC_NORMAL))
            beschreibung = str(e["description"].value) if e["description"] else None
            rolle_roh = str(e["employeeType"].value) if e["employeeType"] else ""
            konten.append(
                IstKonto(
                    dn=dn,
                    benutzername=str(e["sAMAccountName"].value),
                    quell_id=str(e["employeeNumber"].value) if e["employeeNumber"] else None,
                    vorname=str(e["givenName"].value) if e["givenName"] else "",
                    nachname=str(e["sn"].value) if e["sn"] else "",
                    rolle=Rolle(rolle_roh) if rolle_roh in ("schueler", "lehrkraft")
                    else Rolle.SCHUELER,
                    klasse=self._klasse_aus_dn(dn),
                    aktiv=not (uac & 0x2),
                    deaktiviert_am=parse_stempel(beschreibung),
                )
            )
        konten.sort(key=lambda k: (k.klasse or "", k.nachname, k.vorname))
        return konten

    def _klasse_aus_dn(self, dn: str) -> str | None:
        """CN=maja.weber,OU=5A,OU=Schueler,… → ``5A``."""
        suffix = "," + self.config.schueler_dn.lower()
        if not dn.lower().endswith(suffix):
            return None  # Lehrkraft oder Abgänger
        mitte = dn[: -len(suffix)]
        teile = mitte.split(",")
        if len(teile) >= 2 and teile[-1].upper().startswith("OU="):
            return teile[-1][3:]
        return None

    # ---------------------------------------------------------- Struktur
    def stelle_struktur_sicher(self, klassen: set[str]) -> list[str]:
        """Legt Basis-OUs, Klassen-OUs und Gruppen an, falls sie fehlen.
        Idempotent. Gibt die neu angelegten Objekte zurück."""
        neu: list[str] = []
        s = self.config
        ous = [
            s.basis_dn,
            s.schueler_dn,
            s.lehrkraefte_dn,
            s.abgaenger_dn,
            *(s.klassen_dn(k) for k in sorted(klassen)),
        ]
        for dn in ous:
            if self._lege_ou_an(dn):
                neu.append(dn)
        gruppen = [
            s.struktur.gruppe_alle_schueler,
            s.struktur.gruppe_alle_lehrkraefte,
            *(s.klassen_gruppe(k) for k in sorted(klassen)),
        ]
        for name in gruppen:
            if self._lege_gruppe_an(name):
                neu.append(f"Gruppe {name}")
        return neu

    def _lege_ou_an(self, dn: str) -> bool:
        try:
            self.conn.add(dn, attributes={"objectClass": ["top", "organizationalUnit"]})
            return True
        except LDAPEntryAlreadyExistsResult:
            return False
        except LDAPException as e:
            raise LdapFehler(f"OU '{dn}' konnte nicht angelegt werden: {e}") from e

    def _gruppen_dn(self, name: str) -> str:
        return f"CN={escape_rdn(name)},{self.config.basis_dn}"

    def _lege_gruppe_an(self, name: str) -> bool:
        try:
            self.conn.add(
                self._gruppen_dn(name),
                attributes={
                    "objectClass": ["top", "group"],
                    "sAMAccountName": name,
                    "groupType": GRUPPE_GLOBAL_SECURITY,
                },
            )
            return True
        except LDAPEntryAlreadyExistsResult:
            return False
        except LDAPException as e:
            raise LdapFehler(f"Gruppe '{name}' konnte nicht angelegt werden: {e}") from e

    # ------------------------------------------------------------ Konten
    def benutzer_dn(self, benutzername: str, eltern_dn: str) -> str:
        return f"CN={escape_rdn(benutzername)},{eltern_dn}"

    def lege_benutzer_an(
        self,
        benutzername: str,
        vorname: str,
        nachname: str,
        quell_id: str,
        rolle: Rolle,
        eltern_dn: str,
        passwort: str,
    ) -> str:
        """Dreischritt, wie AD ihn verlangt: anlegen (deaktiviert) →
        Passwort setzen (nur über TLS möglich) → aktivieren + Passwortwechsel
        bei erster Anmeldung erzwingen."""
        dn = self.benutzer_dn(benutzername, eltern_dn)
        attribute = {
            "objectClass": ["top", "person", "organizationalPerson", "user"],
            "sAMAccountName": benutzername,
            "userPrincipalName": f"{benutzername}{self.config.konten.upn_suffix}",
            "givenName": vorname,
            "sn": nachname,
            "displayName": f"{vorname} {nachname}",
            "employeeNumber": quell_id,
            "employeeType": rolle.value,
        }
        k = self.config.konten
        if k.home_laufwerk and k.home_pfad:
            attribute["homeDrive"] = k.home_laufwerk
            attribute["homeDirectory"] = k.home_pfad.format(benutzername=benutzername)
        try:
            self.conn.add(dn, attributes=attribute)
            self.setze_passwort(dn, passwort)
            self.conn.modify(
                dn,
                {
                    "userAccountControl": [(MODIFY_REPLACE, [UAC_NORMAL])],
                    "pwdLastSet": [(MODIFY_REPLACE, [0])],  # Änderung bei 1. Anmeldung
                },
            )
        except LDAPException as e:
            raise LdapFehler(f"Konto '{benutzername}' konnte nicht angelegt werden: {e}") from e
        return dn

    def setze_passwort(self, dn: str, passwort: str) -> None:
        self.conn.modify(
            dn, {"unicodePwd": [(MODIFY_REPLACE, [f'"{passwort}"'.encode("utf-16-le")])]}
        )

    def verschiebe(self, dn: str, ziel_ou: str) -> str:
        rdn = dn.split(",", 1)[0]
        try:
            self.conn.modify_dn(dn, rdn, new_superior=ziel_ou)
        except LDAPException as e:
            raise LdapFehler(f"'{dn}' → '{ziel_ou}' fehlgeschlagen: {e}") from e
        return f"{rdn},{ziel_ou}"

    def benenne_um(self, dn: str, vorname: str, nachname: str) -> None:
        try:
            self.conn.modify(
                dn,
                {
                    "givenName": [(MODIFY_REPLACE, [vorname])],
                    "sn": [(MODIFY_REPLACE, [nachname])],
                    "displayName": [(MODIFY_REPLACE, [f"{vorname} {nachname}"])],
                },
            )
        except LDAPException as e:
            raise LdapFehler(f"Umbenennen von '{dn}' fehlgeschlagen: {e}") from e

    def deaktiviere(self, dn: str, am: date, frist_tage: int) -> None:
        try:
            self.conn.modify(
                dn,
                {
                    "userAccountControl": [(MODIFY_REPLACE, [UAC_DISABLED])],
                    "description": [(MODIFY_REPLACE, [deaktivierungs_stempel(am, frist_tage)])],
                },
            )
        except LDAPException as e:
            raise LdapFehler(f"Deaktivieren von '{dn}' fehlgeschlagen: {e}") from e

    def aktiviere(self, dn: str) -> None:
        try:
            self.conn.modify(
                dn,
                {
                    "userAccountControl": [(MODIFY_REPLACE, [UAC_NORMAL])],
                    "description": [(MODIFY_REPLACE, [])],
                },
            )
        except LDAPException as e:
            raise LdapFehler(f"Aktivieren von '{dn}' fehlgeschlagen: {e}") from e

    def loesche(self, dn: str) -> None:
        try:
            self.conn.delete(dn)
        except LDAPException as e:
            raise LdapFehler(f"Löschen von '{dn}' fehlgeschlagen: {e}") from e

    # ----------------------------------------------------------- Gruppen
    def fuege_zu_gruppe_hinzu(self, benutzer_dn: str, gruppe: str) -> None:
        try:
            self.conn.modify(
                self._gruppen_dn(gruppe), {"member": [(MODIFY_ADD, [benutzer_dn])]}
            )
        except (LDAPAttributeOrValueExistsResult, LDAPEntryAlreadyExistsResult):
            pass  # schon Mitglied – idempotent
        except LDAPException as e:
            raise LdapFehler(f"'{benutzer_dn}' → Gruppe '{gruppe}' fehlgeschlagen: {e}") from e

    def entferne_aus_gruppe(self, benutzer_dn: str, gruppe: str) -> None:
        try:
            self.conn.modify(
                self._gruppen_dn(gruppe), {"member": [(MODIFY_DELETE, [benutzer_dn])]}
            )
        except (LDAPNoSuchAttributeResult, LDAPNoSuchObjectResult):
            pass  # war kein Mitglied / Gruppe existiert nicht – idempotent
        except LDAPException as e:
            raise LdapFehler(f"'{benutzer_dn}' aus '{gruppe}' entfernen fehlgeschlagen: {e}") from e

    def gruppen_von(self, benutzer_dn: str) -> list[str]:
        """Alle SchulSync-Gruppen, in denen der Benutzer Mitglied ist."""
        self.conn.search(
            self.config.basis_dn,
            f"(&(objectClass=group)(member={escape_filter_chars(benutzer_dn)}))",
            search_scope=SUBTREE,
            attributes=["sAMAccountName"],
        )
        return [str(e["sAMAccountName"].value) for e in self.conn.entries]
