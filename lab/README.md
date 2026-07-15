# SchulSync-Lab

Ein wegwerfbarer Samba Active Directory Domain Controller zum Ausprobieren
von SchulSync und für die Integrationstests – bewusst **ohne Volume**:
`docker compose down && up` ergibt eine frische, leere Schule.

```bash
docker compose up -d --build --wait     # Domäne SCHULE.LOCAL, dauert ~1 Minute
export SCHULSYNC_LDAP_PASSWORT="Lab-Kennwort-2026"
schulsync check --config schulsync.lab.yaml
```

| | |
|---|---|
| Domäne / Realm | `SCHULE` / `SCHULE.LOCAL` |
| Base-DN | `DC=schule,DC=local` |
| Bind | `Administrator@schule.local` / `Lab-Kennwort-2026` |
| LDAPS | `ldaps://localhost:1636` (selbstsigniert → `tls_verifizieren: false`) |
| LDAP + STARTTLS | `ldap://localhost:1389` |

Die Ports sind an `127.0.0.1` gebunden – der Lab-DC ist nicht aus dem
Netz erreichbar. Das Passwort ist absichtlich öffentlich: **nur fürs Lab**.

Integrationstests dagegen laufen lassen:

```bash
pytest -m integration -o addopts=''
```
