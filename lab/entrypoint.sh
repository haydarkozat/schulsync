#!/bin/sh
# Provisioniert beim ersten Start die AD-Domäne SCHULE.LOCAL und startet Samba.
set -eu

: "${ADMIN_PASS:?Umgebungsvariable ADMIN_PASS fehlt (Administrator-Passwort)}"
REALM="${REALM:-SCHULE.LOCAL}"
DOMAIN="${DOMAIN:-SCHULE}"

if [ ! -f /var/lib/samba/private/sam.ldb ]; then
    echo ">> Provisioniere AD-Domäne ${REALM} …"
    rm -f /etc/samba/smb.conf
    # posix:eadb: Extended Attributes in eine TDB-Datei statt ins Dateisystem –
    # Overlay-Dateisysteme in Containern können keine NT-ACL-Xattrs speichern.
    samba-tool domain provision \
        --realm="${REALM}" \
        --domain="${DOMAIN}" \
        --server-role=dc \
        --dns-backend=SAMBA_INTERNAL \
        --adminpass="${ADMIN_PASS}" \
        --option="posix:eadb = /var/lib/samba/eadb.tdb"
    echo ">> Provisionierung abgeschlossen."
fi

echo ">> Starte Samba AD DC (LDAP 389 / LDAPS 636) …"
exec samba --foreground --no-process-group
