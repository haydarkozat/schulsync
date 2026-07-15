# Änderungen

## 0.1.0 – 2026-07

Erste Veröffentlichung.

* Deklarativer Soll/Ist-Abgleich (plan/apply) zwischen Schulverwaltungs-CSV
  und Active Directory: Anlegen, Klassenwechsel, Umbenennen, Reaktivieren,
  Deaktivieren.
* CSV-Profile für SchILD-NRW und ASV-BW, generisches Profil mit freier
  Spaltenzuordnung; automatische Erkennung von Kodierung (UTF-8/Windows-1252)
  und Trennzeichen.
* Benutzernamen mit Transliteration (Umlaute, Türkisch, Polnisch …),
  sAMAccountName-20-Zeichen-Grenze, domänenweiter Kollisionsprüfung.
* Sicherheitsnetze: Dry-Run als Standard, Notbremse gegen unvollständige
  Exporte, Konflikte blockieren den Lauf, TLS-Zwang.
* Löschkonzept: Abgänger-OU mit Frist-Stempel, `cleanup` löscht erst nach
  Ablauf der Aufbewahrungsfrist.
* HTML-Diff-Report und druckfertige Zugangsdaten-Briefe pro Klasse.
* Docker-Lab mit echtem Samba-AD-DC; Integrationstests decken den
  kompletten Konten-Lebenszyklus ab und laufen in der CI.
