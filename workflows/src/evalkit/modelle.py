"""Datenmodelle für Agent-Evaluation — domänenunabhängig.

Der Anlass war das Buch-Lektorat, aber das Muster gilt für jeden Agent im Stack:
Ein Agent liefert strukturierten Output, und man will wissen, ob er das Richtige
liefert — bevor man anfängt, für jeden beobachteten Einzelfehler einen Filter zu
bauen.

Zwei Arten von Zusicherungen, und die zweite ist die wertvollere:

* **erwartet** — muss zutreffen. Misst die *Trefferquote*: Wie viel von dem, was
  da ist, findet der Agent?
* **verboten** — darf nicht zutreffen. Misst die *Fallenquote*: Wie oft meldet er
  etwas, das keins ist?

Ein Agent, der alles meldet, hat perfekte Trefferquote und ist wertlos. Einer,
der nichts meldet, tappt in keine Falle und ist genauso wertlos. Erst beide
Zahlen zusammen sagen etwas.

Die Fallen kodieren Urteile, die sonst nirgends stehen: dass „runter" gewollt
ist, dass eine Kategorie nicht erfunden werden darf, dass ein Feld leer bleiben
soll, wenn die Information fehlt.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


def _norm(x: Any) -> str:
    return unicodedata.normalize("NFC", str(x)).strip().lower()


# Pfad-Syntax: "feld", "feld.unterfeld", "liste[].feld"
_SEGMENT = re.compile(r"([^.\[\]]+)(\[\])?")


def hole(daten: Any, pfad: str) -> list[Any]:
    """Löst einen Pfad in der Agent-Antwort auf und gibt alle Treffer zurück.

    ``"kategorie"`` → der Wert. ``"korrekturen[].search"`` → alle search-Werte
    der Liste. Fehlende Zwischenstufen ergeben eine leere Liste statt eines
    Fehlers — eine nicht vorhandene Stelle ist ein gültiges Messergebnis.
    """
    aktuell: list[Any] = [daten]
    for name, liste in _SEGMENT.findall(pfad):
        naechste: list[Any] = []
        for k in aktuell:
            if isinstance(k, dict) and name in k:
                wert = k[name]
                naechste.extend(wert if liste and isinstance(wert, list) else [wert])
        aktuell = naechste
    return aktuell


@dataclass
class Pruefung:
    """Eine Zusicherung über die Antwort eines Agents.

    ``operator``:
      * ``enthaelt``  — irgendein Wert am Pfad enthält ``wert`` (oder umgekehrt;
        beidseitig, damit ein Agent mehr oder weniger Kontext mitnehmen darf)
      * ``gleich``    — irgendein Wert am Pfad ist genau ``wert``
      * ``existiert`` — am Pfad steht überhaupt etwas Nichtleeres
      * ``paar``      — zwei Pfade zugleich: ``wert`` ist ``[von, nach]``; trifft
        zu, wenn ein Element beide Teile erfüllt. Für Befundlisten gedacht
        („meldet ``runter`` **und** ersetzt es durch ``hinunter``“).
    """

    pfad: str
    operator: str = "enthaelt"
    wert: Any = None
    paar_pfad: str | None = None
    hinweis: str = ""

    def trifft_zu(self, antwort: Any) -> bool:
        werte = hole(antwort, self.pfad)

        if self.operator == "existiert":
            return any(w not in (None, "", [], {}) for w in werte)

        if self.operator == "gleich":
            return any(_norm(w) == _norm(self.wert) for w in werte)

        if self.operator == "paar":
            von, nach = self.wert
            zweite = hole(antwort, self.paar_pfad or self.pfad)
            return any(
                (_norm(von) in _norm(a) or _norm(a) in _norm(von))
                and _norm(nach) in _norm(b)
                for a, b in zip(werte, zweite, strict=False)
            )

        ziel = _norm(self.wert)
        return any(ziel and (ziel in _norm(w) or _norm(w) in ziel) for w in werte if w)

    def beschreibe(self) -> str:
        if self.operator == "paar":
            return f"{self.wert[0]} → {self.wert[1]}"
        return f"{self.pfad} {self.operator} {self.wert!r}"


@dataclass
class Fall:
    """Ein Testfall: Eingabe plus was zutreffen muss und was nicht darf."""

    id: str
    eingabe: str
    erwartet: list[Pruefung] = field(default_factory=list)
    verboten: list[Pruefung] = field(default_factory=list)
    quelle: str = "manuell"
    notiz: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Fall:
        def p(x: dict) -> Pruefung:
            return Pruefung(**{k: v for k, v in x.items() if not k.startswith("_")})

        return cls(
            id=d["id"],
            eingabe=d["eingabe"],
            erwartet=[p(x) for x in d.get("erwartet", [])],
            verboten=[p(x) for x in d.get("verboten", [])],
            quelle=d.get("quelle", "manuell"),
            notiz=d.get("notiz", ""),
        )


@dataclass
class Ergebnis:
    """Was ein Lauf eines Falls ergeben hat."""

    fall_id: str
    getroffen: list[str] = field(default_factory=list)
    verpasst: list[str] = field(default_factory=list)
    fehltritte: list[str] = field(default_factory=list)
    elemente: int = 0
    dauer: float = 0.0
    tokens: int = 0
    fehler: str | None = None


def pruefe(fall: Fall, antwort: Any, *, zaehlpfad: str | None = None) -> Ergebnis:
    """Wertet eine Agent-Antwort gegen einen Fall aus.

    ``zaehlpfad`` sagt, was als „ein Befund“ zählt (z. B. ``"korrekturen[]"``) —
    nur für die Güte-Kennzahl. Fehlt er, wird die Antwort als ein Element gezählt.
    """
    e = Ergebnis(fall_id=fall.id)
    e.elemente = len(hole(antwort, zaehlpfad)) if zaehlpfad else 1

    for pr in fall.erwartet:
        (e.getroffen if pr.trifft_zu(antwort) else e.verpasst).append(pr.beschreibe())
    for pr in fall.verboten:
        if pr.trifft_zu(antwort):
            e.fehltritte.append(pr.beschreibe())
    return e


@dataclass
class Bilanz:
    """Zusammenfassung über alle Fälle einer Konfiguration."""

    konfiguration: str
    faelle: int = 0
    erwartet: int = 0
    getroffen: int = 0
    verboten: int = 0
    fehltritte: int = 0
    elemente: int = 0
    dauer: float = 0.0
    tokens: int = 0
    fehler: int = 0

    @property
    def trefferquote(self) -> float:
        return self.getroffen / self.erwartet if self.erwartet else 1.0

    @property
    def fallenquote(self) -> float:
        """Anteil der Fallen, in die getappt wurde. Kleiner ist besser."""
        return self.fehltritte / self.verboten if self.verboten else 0.0

    @property
    def punktzahl(self) -> float:
        """Trefferquote abzüglich Fallenquote — eine Zahl zum Sortieren.

        Bewusst grob: Sie ersetzt nicht den Blick auf beide Werte, macht aber
        einen Vergleich zwischen Konfigurationen auf einen Blick möglich.
        """
        return self.trefferquote - self.fallenquote

    def als_zeile(self) -> str:
        return (
            f"{self.konfiguration:22} "
            f"Treffer {self.getroffen:3}/{self.erwartet:<3} ({self.trefferquote:4.0%})  "
            f"Fallen {self.fehltritte:3}/{self.verboten:<3} ({self.fallenquote:4.0%})  "
            f"Punkte {self.punktzahl:+.2f}  "
            f"{self.dauer / max(self.faelle, 1):5.1f}s  {self.tokens:6}T"
            + (f"  {self.fehler} Fehler!" if self.fehler else "")
        )


def bilanziere(konfiguration: str, faelle: list[Fall], ergebnisse: list[Ergebnis]) -> Bilanz:
    b = Bilanz(konfiguration=konfiguration, faelle=len(ergebnisse))
    nach_id = {f.id: f for f in faelle}
    for e in ergebnisse:
        f = nach_id.get(e.fall_id)
        if f is None:
            continue
        b.erwartet += len(f.erwartet)
        b.verboten += len(f.verboten)
        b.getroffen += len(e.getroffen)
        b.fehltritte += len(e.fehltritte)
        b.elemente += e.elemente
        b.dauer += e.dauer
        b.tokens += e.tokens
        b.fehler += 1 if e.fehler else 0
    return b
