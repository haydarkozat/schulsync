"""Benutzernamen-Erzeugung.

Regeln, die sich im Schulbetrieb bewährt haben:

* Schema konfigurierbar (Standard ``vorname.nachname``), alles klein.
* Umlaute & Co. werden AD-tauglich transliteriert: ``Müller`` → ``mueller``,
  ``Yılmaz`` → ``yilmaz``, ``Đorđević`` → ``dordevic``. Schulen sind
  vielfältig – die Benutzernamen müssen es aushalten.
* ``sAMAccountName`` ist historisch auf **20 Zeichen** begrenzt – wird
  gekürzt, bevor das AD einen kryptischen Fehler wirft.
* Kollisionen (zweite ``lena.schmidt``) bekommen einen Zähler: ``lena.schmidt2``.
* Deterministisch: gleicher Input ⇒ gleicher Benutzername.
"""

from __future__ import annotations

import re
import unicodedata

SAM_MAX = 20  # historisches NetBIOS-Limit für sAMAccountName

# Gezielte Ersetzungen, die NFKD nicht (oder falsch) erledigt:
_ERSETZUNGEN = str.maketrans(
    {
        "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss",
        "Ä": "ae", "Ö": "oe", "Ü": "ue", "ẞ": "ss",
        "ı": "i", "İ": "i",          # Türkisch
        "ð": "d", "Ð": "d",
        "đ": "d", "Đ": "d",          # Südslawisch
        "ø": "oe", "Ø": "oe",
        "æ": "ae", "Æ": "ae",
        "œ": "oe", "Œ": "oe",
        "þ": "th", "Þ": "th",
        "ł": "l", "Ł": "l",          # Polnisch
    }
)


def transliteriere(text: str) -> str:
    """Wandelt einen Namen in reines ASCII-Kleinbuchstaben-Format um."""
    text = text.translate(_ERSETZUNGEN)
    # NFKD zerlegt z. B. é in e + Akzent; die Akzente werden verworfen.
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"[\s']+", "-", text.strip())  # Leerzeichen/Apostroph → Bindestrich
    text = re.sub(r"[^a-z0-9-]", "", text)  # Rest raus (AD-sicher)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text


def _kuerze(basis: str, max_len: int) -> str:
    return basis[:max_len].rstrip(".-")


def erzeuge_benutzername(
    vorname: str,
    nachname: str,
    schema: str = "{vorname}.{nachname}",
    vergeben: set[str] | None = None,
) -> str:
    """Erzeugt einen eindeutigen, AD-tauglichen Benutzernamen.

    ``vergeben`` enthält alle bereits existierenden sAMAccountNames der
    Domäne (nicht nur die von SchulSync verwalteten!) – sonst kollidiert
    die neue Schülerin irgendwann mit dem Hausmeister-Konto.
    """
    vergeben = {v.lower() for v in (vergeben or set())}
    # Bei mehrteiligen Vornamen zählt der Rufname (erster Teil):
    erster_vorname = vorname.strip().split()[0] if vorname.strip() else vorname
    basis = schema.format(
        vorname=transliteriere(erster_vorname),
        nachname=transliteriere(nachname),
    )
    basis = re.sub(r"\.{2,}", ".", basis).strip(".")
    if not basis.replace(".", "").replace("-", ""):
        raise ValueError(
            f"Aus '{vorname} {nachname}' lässt sich kein Benutzername bilden – "
            "bitte Datensatz in der Schulverwaltung prüfen."
        )

    kandidat = _kuerze(basis, SAM_MAX)
    if kandidat.lower() not in vergeben:
        return kandidat

    for zaehler in range(2, 1000):
        suffix = str(zaehler)
        kandidat = _kuerze(basis, SAM_MAX - len(suffix)) + suffix
        if kandidat.lower() not in vergeben:
            return kandidat
    raise ValueError(f"Kein freier Benutzername für '{vorname} {nachname}' gefunden.")
