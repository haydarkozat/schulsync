# SchulSync

**Schuljahreswechsel ohne Handarbeit: Schulverwaltung → Active Directory.**

[![CI](https://github.com/haydarkozat/schulsync/actions/workflows/ci.yml/badge.svg)](https://github.com/haydarkozat/schulsync/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/schulsync?color=3775a9&logo=pypi&logoColor=white)](https://pypi.org/project/schulsync/)
![Python](https://img.shields.io/badge/Python-3.11%2B-3776ab?logo=python&logoColor=white)
![Getestet gegen](https://img.shields.io/badge/getestet%20gegen-Samba%20AD%20DC-1a7f4e)
![Lizenz](https://img.shields.io/badge/Lizenz-MIT-blue)

Jeden September dasselbe Ritual: Der neue Export aus der Schulverwaltung
liegt vor, und irgendjemand aus der Schul-IT klickt sich durch hunderte
Konten – neue Fünftklässler anlegen, alle Klassen eine Stufe
weiterschieben, Abgänger deaktivieren, Passwortzettel drucken. Zwei Tage
Handarbeit, und ein Tippfehler bedeutet, dass ein Kind am ersten Schultag
nicht ins WLAN kommt.

SchulSync macht daraus **einen Befehl mit Vorschau**:

![schulsync plan](https://raw.githubusercontent.com/haydarkozat/schulsync/main/docs/images/plan-2026.svg)

## Das Prinzip: Terraform für Schülerkonten

Der CSV-Export der Schulverwaltung (SchILD-NRW, ASV-BW oder beliebige
Spalten) beschreibt den **Soll-Zustand**. Das Active Directory ist der
**Ist-Zustand**. SchulSync berechnet die Differenz – und führt sie erst
aus, wenn ein Mensch den Plan gesehen und bestätigt hat.

```
schulsync plan  export.csv        # Was würde passieren? Ändert garantiert nichts.
schulsync apply export.csv        # Plan ausführen – nach Bestätigung.
```

* **Idempotent:** derselbe Export zweimal ⇒ beim zweiten Mal „nichts zu
  tun". Abgebrochene Läufe repariert der nächste Lauf von selbst.
* **Ein Modell für alles:** Schuljahreswechsel, Zuzug im Februar,
  Namensänderung nach Heirat – immer derselbe Soll/Ist-Vergleich.
* **Nachvollziehbar:** jeder Lauf auf Wunsch als HTML-Report für die
  Ablage (Verfahrensnachweis).

## Was SchulSync erledigt

| | |
|---|---|
| ➕ **Anlegen** | Konto in der Klassen-OU, Klassen- & Sammelgruppen, Home-Verzeichnis-Attribute, merkbares Initialpasswort (`Tiger-Wolke-47`), Passwortwechsel bei erster Anmeldung erzwungen |
| ⇄ **Klassenwechsel** | OU-Umzug + Gruppentausch (`Klasse-5A` → `Klasse-6A`) |
| ✎ **Umbenennen** | Namensänderung ohne neuen Benutzernamen – niemand verliert Profil oder Dateien |
| ↻ **Reaktivieren** | Rückkehrer bekommen ihr altes Konto wieder statt eines Duplikats |
| ⏻ **Deaktivieren** | Abgänger: gesperrt, aus allen Gruppen entfernt, in die Abgänger-OU, mit Frist-Stempel |
| 🗑 **Löschen** | `schulsync cleanup` löscht erst nach Ablauf der Aufbewahrungsfrist – dokumentiertes Löschkonzept statt Karteileichen |
| ✉ **Briefe** | druckfertige Zugangsdaten-Briefe pro Klasse aus einem Befehl |

Dazu die Details, die man erst nach ein paar hundert Schülerkonten zu
schätzen weiß: Umlaut- und Sonderzeichen-Transliteration
(`Yılmaz → yilmaz`, `Đorđević → dordevic`), die 20-Zeichen-Grenze von
`sAMAccountName`, Kollisionszähler gegen **alle** Konten der Domäne
(`emma.fischer2`), automatische Erkennung von Kodierung (UTF-8 ↔
Windows-1252) und Trennzeichen.

## Eingebaute Sicherheitsnetze

* **Dry-Run zuerst:** `plan` hat keinerlei Schreibzugriff – Vorschau ist
  der Normalfall, nicht das Extra.
* **Notbremse:** Ein Export, der mehr als die Hälfte der aktiven Konten
  deaktivieren würde (typisch: halber Export, falsche Berichtsvorlage),
  wird als Konflikt blockiert – bevor er Schaden anrichtet.
* **Konflikt heißt Stopp:** doppelte IDs, Konten ohne Quell-ID → Meldung
  statt Automatik-Raten. Exit-Code 2, nichts wurde geändert.
* **Nur die eigene OU:** Konten außerhalb von `OU=SchulSync` werden nie
  angefasst. Das Dienstkonto braucht keine Domain-Admin-Rechte, nur
  Delegierung auf diese OU.
* **Verschlüsselung erzwungen:** LDAPS bzw. STARTTLS – unverschlüsselt
  verweigert SchulSync den Dienst. Passwörter stehen nie in Dateien,
  nur in `SCHULSYNC_LDAP_PASSWORT`.

![schulsync apply](https://raw.githubusercontent.com/haydarkozat/schulsync/main/docs/images/apply-2026.svg)

## In 5 Minuten ausprobieren – mit echtem AD

Das Repo bringt ein Docker-Lab mit: ein wegwerfbarer **Samba Active
Directory Domain Controller** (Domäne `SCHULE.LOCAL`) plus fiktive
Beispieldaten für zwei Schuljahre.

```bash
git clone https://github.com/haydarkozat/schulsync && cd schulsync
python3 -m venv .venv && source .venv/bin/activate
pip install -e .

# 1) Lab-AD hochfahren (einmalig ~1 Minute)
docker compose -f lab/docker-compose.yml up -d --build --wait
export SCHULSYNC_LDAP_PASSWORT="Lab-Kennwort-2026"

# 2) Schuljahr 2025/26 einspielen: 149 Schüler:innen + 5 Lehrkräfte
schulsync apply examples/schild-export-2025.csv \
    --lehrkraefte examples/lehrkraefte.csv --ja \
    --config lab/schulsync.lab.yaml

# 3) Der Schuljahreswechsel: erst ansehen …
schulsync plan examples/schild-export-2026.csv \
    --lehrkraefte examples/lehrkraefte.csv \
    --report report.html --config lab/schulsync.lab.yaml

# … dann ausführen: 24 anlegen, 125 aufrücken, 24 Abgänger, 2 Umbenennungen
schulsync apply examples/schild-export-2026.csv \
    --lehrkraefte examples/lehrkraefte.csv --ja \
    --config lab/schulsync.lab.yaml

# 4) Zugangsdaten-Briefe für die neuen 5er drucken
schulsync briefe zugangsdaten-*.csv --loeschen --config lab/schulsync.lab.yaml
```

Danach lohnt ein Blick in den HTML-Report ([Beispiel](https://github.com/haydarkozat/schulsync/blob/main/docs/beispiel-report.html)):

[![HTML-Report](https://raw.githubusercontent.com/haydarkozat/schulsync/main/docs/images/report-2026.png)](https://github.com/haydarkozat/schulsync/blob/main/docs/beispiel-report.html)

Und weil SchulSync idempotent ist, sagt derselbe Befehl direkt danach
schlicht die Wahrheit:

![idempotenter zweiter Lauf](https://raw.githubusercontent.com/haydarkozat/schulsync/main/docs/images/plan-idempotent.svg)

## Im echten Schulnetz

```bash
pip install schulsync                               # frisch von PyPI (Python 3.11+)
cp examples/schulsync.example.yaml schulsync.yaml   # anpassen: Server, Basis-DN, Schema
export SCHULSYNC_LDAP_PASSWORT='…'                  # Bind-Passwort des Dienstkontos
schulsync check                                     # Verbindung & Konfiguration prüfen
schulsync validate export.csv                       # Export prüfen (Kodierung, Dubletten)
schulsync plan export.csv --report plan.html        # Vorschau für die Ablage
schulsync apply export.csv                          # mit Rückfrage ausführen
```

Funktioniert gegen **Windows Server AD** und **Samba AD** (ab Werk wird
gegen einen echten Samba-DC integrationsgetestet, s. u.). Für die
Drift-Überwachung: `schulsync plan export.csv --check` liefert Exit-Code 3,
sobald AD und Schulverwaltung auseinanderlaufen – fertig ist der
Nightly-Check im Monitoring.

| Kommando | Zweck |
|---|---|
| `schulsync check` | Konfiguration & AD-Verbindung prüfen (nur lesend) |
| `schulsync validate <csv>` | Export prüfen: Kodierung, Spalten, Dubletten |
| `schulsync plan <csv>` | Soll/Ist-Vergleich als Vorschau (Dry-Run) |
| `schulsync apply <csv>` | Plan ausführen (mit Bestätigung bzw. `--ja`) |
| `schulsync briefe <csv>` | Zugangsdaten-Briefe je Klasse als druckfertiges HTML |
| `schulsync cleanup` | Abgänger nach Ablauf der Aufbewahrungsfrist endgültig löschen |

## Warum nicht …?

* **… Microsoft School Data Sync?** Synct in die Cloud (Entra ID/Teams),
  nicht ins on-prem AD, und setzt M365-Schulverträge voraus. SchulSync
  läuft dort, wo viele Schulträger ihre Konten wirklich verwalten: im
  lokalen Active Directory – ohne dass Schülerdaten das Haus verlassen.
* **… UCS@school?** Stark, aber ein kompletter Plattformwechsel samt
  eigenem Ökosystem. SchulSync ist ein Werkzeug, keine Plattform: es
  arbeitet mit dem AD, das schon da ist.
* **… das gewachsene PowerShell-Skript?** Kennt jede Schul-IT. Meist ohne
  Dry-Run, ohne Idempotenz, ohne Notbremse, ohne Löschkonzept – und der
  Autor ist nicht mehr an der Schule. Genau diese Lücken schließt
  SchulSync, mit Tests statt Hoffnung.

## Qualität

* **60+ Tests**, darunter eine Integrationssuite, die in der CI einen
  **echten Samba-AD-DC im Docker-Container** hochfährt und den kompletten
  Lebenszyklus durchspielt: Erstbefüllung → Idempotenz →
  Schuljahreswechsel → Rückkehrer-Reaktivierung → Notbremse →
  Fristablauf & Löschung.
* Kein Mock spielt AD – was hier grün ist, lief gegen LDAP, TLS und
  `unicodePwd`-Realität.
* [docs/funktionsweise.md](https://github.com/haydarkozat/schulsync/blob/main/docs/funktionsweise.md) erklärt die
  Designentscheidungen (warum `CN = Benutzername`, warum `employeeNumber`
  als Schlüssel, warum diese Ausführungsreihenfolge).
* [docs/dsgvo.md](https://github.com/haydarkozat/schulsync/blob/main/docs/dsgvo.md): Datenminimierung, Löschkonzept,
  TLS-Zwang – Datenschutz als Designgrundlage, nicht als Fußnote.

> **Hinweis zu den Beispieldaten:** Alle Namen in `examples/` sind fiktiv
> und werden von `scripts/erzeuge_beispieldaten.py` deterministisch
> erzeugt. Es sind keine echten Schülerdaten – und es sollten auch nie
> welche ins Repo gelangen (`.gitignore` hilft nach).

## Über dieses Projekt

Ich habe 16 Jahre lang Schul-IT betrieben – zuletzt als
IT-Systemadministrator im türkischen FATİH-Programm (dem Pendant zum
DigitalPakt Schule) mit rund 5.000 Nutzerkonten. Den Schuljahreswechsel
habe ich oft genug von Hand gemacht, um zu wissen, welche Fehler um
3 Uhr nachts passieren. SchulSync ist das Werkzeug, das ich mir damals
gewünscht hätte.

**Haydar Kozat** ·
[GitHub](https://github.com/haydarkozat) ·
[LinkedIn](https://linkedin.com/in/haydar-kozat)

Lizenz: [MIT](https://github.com/haydarkozat/schulsync/blob/main/LICENSE)
