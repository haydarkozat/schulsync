# Samba Active Directory Domain Controller für das SchulSync-Lab.
#
# Bewusst ohne Volume: Container löschen = frische, leere Schule.
# Beim ersten Start provisioniert der Entrypoint die Domäne SCHULE.LOCAL;
# Samba erzeugt dabei automatisch ein selbstsigniertes TLS-Zertifikat,
# LDAPS (636) ist damit sofort nutzbar.
FROM debian:bookworm-slim

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
        samba samba-ad-dc samba-ad-provision samba-dsdb-modules samba-vfs-modules \
        krb5-user ldap-utils \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 389 636

HEALTHCHECK --interval=5s --timeout=4s --start-period=20s --retries=40 \
    CMD ldapsearch -H ldap://127.0.0.1 -x -b '' -s base defaultNamingContext >/dev/null || exit 1

ENTRYPOINT ["/entrypoint.sh"]
