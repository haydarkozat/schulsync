# Datenschutz: Wie SchulSync mit personenbezogenen Daten umgeht

Schülerdaten sind personenbezogene Daten von Minderjährigen – die
sensibelste Datenkategorie, die eine Schul-IT verwaltet. SchulSync ist
deshalb nicht »auch irgendwie DSGVO-konform«, sondern von der ersten
Designentscheidung an um die Grundsätze aus **Art. 5 DSGVO** herum gebaut.

> **Wichtiger Hinweis:** Dieses Dokument beschreibt die technischen
> Eigenschaften der Software. Es ersetzt keine Rechtsberatung und nicht
> die Abstimmung mit dem/der Datenschutzbeauftragten des Schulträgers.
> Der Eintrag ins Verzeichnis der Verarbeitungstätigkeiten (Art. 30 DSGVO)
> bleibt Aufgabe der verantwortlichen Stelle.

## Datenminimierung (Art. 5 Abs. 1 lit. c)

Die Schulverwaltung exportiert oft mehr, als für Konten nötig ist.
SchulSync liest aus dem Export **genau vier Felder**:

| Feld | Zweck |
|---|---|
| ID (z. B. »Interne ID-Nummer«) | stabiler Schlüssel zwischen Schulverwaltung und AD |
| Vorname | Benutzername, Anzeigename |
| Nachname | Benutzername, Anzeigename |
| Klasse | OU-Zuordnung, Klassengruppe |

Geburtsdatum, Geschlecht, Adressen, Förderdaten usw. werden **ignoriert**,
selbst wenn sie im Export stehen. Ins AD geschrieben werden ausschließlich
Name, Benutzername, ID (`employeeNumber`), Rolle (`employeeType`) und
optional Home-Verzeichnis-Attribute.

## Speicherbegrenzung & Löschkonzept (Art. 5 Abs. 1 lit. e, Art. 17)

Der Lebenszyklus eines Kontos ist vollständig definiert – es gibt keinen
Zustand »liegt halt noch rum«:

```
Export enthält ID  ──────────────►  aktives Konto (Klassen-OU)
Export enthält ID nicht mehr  ───►  deaktiviert + Abgänger-OU
                                    └─ Stempel: »deaktiviert am JJJJ-MM-TT«
Frist abgelaufen (Standard 90 Tage) ► endgültige Löschung durch
                                      `schulsync cleanup`
```

* Deaktivieren statt sofort löschen gibt Nachzüglern, Rückkehrern und
  versehentlich fehlerhaften Exporten eine Gnadenfrist – danach wird
  **wirklich gelöscht**, nicht nur deaktiviert.
* Die Frist ist konfigurierbar (`aufbewahrung.abgaenger_tage`) und wird
  im AD-Konto selbst dokumentiert (nachvollziehbar für Audits).
* Konten ohne lesbaren Frist-Stempel löscht `cleanup` **niemals** –
  im Zweifel Mensch statt Automatik.

## Integrität & Vertraulichkeit (Art. 5 Abs. 1 lit. f, Art. 32)

* **Keine Cloud, keine Telemetrie:** SchulSync läuft dort, wo die Daten
  sind – im Schulnetz. Es telefoniert nirgendwohin.
* **Verschlüsselung erzwungen:** Verbindungen laufen über LDAPS; bei
  `ldap://` erzwingt SchulSync STARTTLS. Unverschlüsselt werden
  keine Passwörter gesetzt – das lehnt schon das AD ab, und SchulSync
  versucht es gar nicht erst.
* **Zugangsdaten-Hygiene:** Das Bind-Passwort lebt nur in der
  Umgebungsvariable `SCHULSYNC_LDAP_PASSWORT`, nie in Dateien.
  Initialpasswörter werden mit Dateimodus `0600` geschrieben, sind
  Einmalpasswörter (`pwdLastSet=0` erzwingt die Änderung bei der ersten
  Anmeldung) und `schulsync briefe --loeschen` entsorgt die Datei nach
  dem Druck.
* **Minimale Rechte:** Das Dienstkonto braucht nur Schreibrechte auf die
  SchulSync-Basis-OU – kein Domain-Admin nötig (Delegierung per
  »Object-Management« auf die OU).

## Richtigkeit & Nachvollziehbarkeit (Art. 5 Abs. 1 lit. d, Abs. 2)

* Jeder Lauf beginnt als **Dry-Run** (`plan`): Was passieren würde, steht
  vorher fest – im Terminal und auf Wunsch als HTML-Report, der als
  Verfahrensnachweis abgelegt werden kann.
* Die **Notbremse** blockiert Läufe, die mehr als die Hälfte der aktiven
  Konten deaktivieren würden – der klassische »halber Export«-Unfall.
* Konflikte (Konten ohne Quell-ID, doppelte IDs) werden gemeldet und
  **nicht** automatisch »repariert«.

## Rechtsgrundlage (zur Einordnung)

Die Verarbeitung erfolgt zur Erfüllung der schulischen Aufgaben auf
Grundlage von Art. 6 Abs. 1 lit. e DSGVO i. V. m. den jeweiligen
Landesschulgesetzen (z. B. § 120 ff. SchulG NRW, § 115 SchG BW).
Verantwortlich bleibt die Schule bzw. der Schulträger.
