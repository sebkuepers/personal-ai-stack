"""Die Lektoratsnotizen des Autors auswerten — der wertvollste Rohstoff im Projekt.

In den ``notes.rtf`` des Scrivener-Projekts steckt bereits ausformuliertes
Lektorat, geschrieben vom Autor selbst, in seiner eigenen Sprache. Das Format hat
sich organisch ergeben und ist bemerkenswert konsequent:

    DREIMAL DASSELBE SAGEN          ← die Regel, in Versalien
    VORHER
    Ich starre auf das tiefblaue und komplett ruhige Meer. …
    NACHHER
    Ich starre auf das Meer. …
    WARUM
    Vier Sätze, und drei davon behaupten dieselbe Stille. …

Daneben stehen Blöcke ohne Änderung — ``NICHT ANFASSEN`` (was gelungen ist),
``ENTSCHEIDUNG: …`` (was gestrichen wurde und warum), ``WAS BLEIBT``. Die sind
genauso wertvoll: eine Stilregel, die sagt, was man *nicht* anfassen darf, ist
für einen Lektorats-Agent oft nützlicher als eine, die etwas verbessert.

Der Nutzen: Das Stimmprofil startet nicht bei null und nicht bei einem
Schreibratgeber, sondern bei Dutzenden echten Entscheidungen des Autors. Und das
Entscheidungslog hat vom ersten Tag an gelabelte Beispiele.

Rein — kein Modell, kein Netz. Testbar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# Eine Blocküberschrift: eine eigene Zeile, überwiegend Versalien, kein Satzende.
# Erlaubt Doppelpunkt-Zusätze wie "ENTSCHEIDUNG: DER LOTSENEXKURS GEHT RAUS".
_UEBERSCHRIFT = re.compile(r"^(?=.*[A-ZÄÖÜ])[A-ZÄÖÜ0-9ẞß .,:()–—/&'\"-]{4,80}$")

# Die Marker innerhalb eines Blocks.
_MARKER = ("VORHER", "NACHHER", "WARUM")

Art = Literal["aenderung", "hinweis"]


@dataclass
class Lektoratsnotiz:
    """Eine benannte Beobachtung des Autors zu einem Abschnitt."""

    abschnitt_uuid: str
    abschnitt_titel: str
    regel: str
    art: Art
    vorher: str | None = None
    nachher: str | None = None
    warum: str | None = None
    text: str | None = None  # bei Hinweisen der volle Fließtext

    @property
    def regel_id(self) -> str:
        """Stabiler Bezeichner, wie ihn das Stimmprofil verwendet."""
        s = self.regel.lower()
        for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
            s = s.replace(a, b)
        s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        return f"N-{s[:48]}"


def _ist_ueberschrift(zeile: str) -> bool:
    z = zeile.strip()
    if not z or z in _MARKER:
        return False
    if not _UEBERSCHRIFT.match(z):
        return False
    # Mindestens die Hälfte der Buchstaben groß — filtert Zitate in Versalien-Nähe.
    buchstaben = [ch for ch in z if ch.isalpha()]
    return bool(buchstaben) and sum(ch.isupper() for ch in buchstaben) / len(buchstaben) > 0.8


def _abschnitte_teilen(notiz: str) -> list[tuple[str, list[str]]]:
    """Zerlegt den Notiztext in (Überschrift, Zeilen)-Blöcke."""
    bloecke: list[tuple[str, list[str]]] = []
    aktuell: tuple[str, list[str]] | None = None
    for zeile in notiz.splitlines():
        if _ist_ueberschrift(zeile):
            if aktuell:
                bloecke.append(aktuell)
            aktuell = (zeile.strip(), [])
        elif aktuell:
            aktuell[1].append(zeile)
    if aktuell:
        bloecke.append(aktuell)
    return bloecke


def _marker_teilen(zeilen: list[str]) -> dict[str, str]:
    """Trennt einen Block an VORHER / NACHHER / WARUM."""
    teile: dict[str, list[str]] = {}
    aktuell: str | None = None
    for zeile in zeilen:
        z = zeile.strip()
        if z in _MARKER:
            aktuell = z
            teile[aktuell] = []
        elif aktuell:
            teile[aktuell].append(zeile)
    return {k: "\n".join(v).strip() for k, v in teile.items()}


def lies_notizen(uuid: str, titel: str, notiz: str | None) -> list[Lektoratsnotiz]:
    """Wertet die Notizen eines Abschnitts aus."""
    if not notiz:
        return []

    ergebnis: list[Lektoratsnotiz] = []
    for ueberschrift, zeilen in _abschnitte_teilen(notiz):
        teile = _marker_teilen(zeilen)
        if teile.get("VORHER") and teile.get("NACHHER"):
            ergebnis.append(
                Lektoratsnotiz(
                    abschnitt_uuid=uuid,
                    abschnitt_titel=titel,
                    regel=ueberschrift,
                    art="aenderung",
                    vorher=teile["VORHER"],
                    nachher=teile["NACHHER"],
                    warum=teile.get("WARUM"),
                )
            )
        else:
            rumpf = "\n".join(zeilen).strip()
            if rumpf:
                ergebnis.append(
                    Lektoratsnotiz(
                        abschnitt_uuid=uuid,
                        abschnitt_titel=titel,
                        regel=ueberschrift,
                        art="hinweis",
                        text=rumpf,
                    )
                )
    return ergebnis


def alle_notizen(manuskript) -> list[Lektoratsnotiz]:  # noqa: ANN001 — Manuskript, zirkelfrei
    """Sammelt die Notizen des ganzen Werks."""
    return [
        n
        for a in manuskript.abschnitte
        for n in lies_notizen(a.uuid, a.titel, a.notizen)
    ]


def haeufige_regeln(notizen: list[Lektoratsnotiz], mindestens: int = 2) -> list[tuple[str, int]]:
    """Regelnamen, die der Autor mehrfach vergeben hat — die Kandidaten fürs Profil.

    Eine Regel, die er dreimal unabhängig benannt hat, ist belastbarer als
    alles, was ein Modell aus dem Text destilliert.
    """
    zaehler: dict[str, int] = {}
    for n in notizen:
        schluessel = n.regel.split(":")[0].strip()
        zaehler[schluessel] = zaehler.get(schluessel, 0) + 1
    return sorted(
        ((k, v) for k, v in zaehler.items() if v >= mindestens),
        key=lambda kv: (-kv[1], kv[0]),
    )
