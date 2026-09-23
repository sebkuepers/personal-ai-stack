"""Das Entscheidungslog — eine Zeile je Befund, in den Worten des Autors.

Das ist das Kapital des ganzen Systems. Ein angenommener Befund sagt wenig; ein
abgelehnter mit Grund sagt, wo das Stimmprofil danebenliegt. Und ein Befund,
den der Autor annimmt, aber **selbst umformuliert**, ist ein Paar, das kein
Modell erzeugt hat.

Bis hierher wurde nichts davon gespeichert: ``LektoratSitzung`` lieferte die
Entscheidungen samt Grund, und beim Schließen des Chats waren sie weg. Der
wertvollste Ausgang des Systems war Deko.

**Format:** JSONL, monatsweise, unter ``workflows/data/buch/<slug>/entscheidungen/``
— gitignored, denn hier steht Manuskripttext. Eine Zeile je Befund, nicht je
Sitzung, damit sich später je Regel auszählen lässt.

**Geschrieben wird an genau einer Stelle** — aus dem Gesprächs-Workflow heraus,
sobald eine Ebene freigegeben ist, nicht erst am Ende. Bricht die Sitzung ab
oder läuft in den Timeout, sind die Entscheidungen bis dahin trotzdem da.

Rein: keine Modelle, keine Agents. Lesen und Schreiben passiert in den
Aktivitäten in ``lokal.py``; hier stehen die Formate und die Auswertung.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Entscheidung


def log_ordner(daten_wurzel: Path, werk: str) -> Path:
    return daten_wurzel / "buch" / werk / "entscheidungen"


def log_datei(daten_wurzel: Path, werk: str, wann: datetime | None = None) -> Path:
    """Die Datei des laufenden Monats — Monatsdateien bleiben handhabbar und diffbar."""
    wann = wann or datetime.now(UTC)
    return log_ordner(daten_wurzel, werk) / f"{wann:%Y-%m}.jsonl"


def zeile(
    e: Entscheidung,
    *,
    werk: str,
    abschnitt_uuid: str,
    abschnitt_titel: str,
    pfad: list[str],
    sitzung_id: str,
    wann: datetime | None = None,
) -> dict[str, Any]:
    """Eine Logzeile — flach, damit sie mit jedem Werkzeug auszählbar bleibt."""
    wann = wann or datetime.now(UTC)
    return {
        "ts": wann.isoformat(timespec="seconds"),
        "sitzung": sitzung_id,
        "werk": werk,
        "abschnitt_uuid": abschnitt_uuid,
        "abschnitt": abschnitt_titel,
        "pfad": pfad,
        "ebene": e.ebene,
        "absatz_index": e.absatz_index,
        "absatz_hash": e.absatz_hash,
        "art": e.art,
        "regel_id": e.regel_id,
        "search": e.search,
        "replace": e.replace,
        "warum": e.warum,
        "entscheidung": e.entscheidung,
        "grund": e.grund,
        # Wenn der Autor selbst umformuliert hat, steht hier seine Fassung —
        # das Goldstandard-Paar, das kein Modell erzeugt hat.
        "eigene_fassung": e.eigene_fassung,
    }


def schreibe(datei: Path, zeilen: list[dict[str, Any]]) -> int:
    """Hängt Zeilen an; legt Ordner und Datei an, falls nötig. Gibt die Anzahl zurück."""
    if not zeilen:
        return 0
    datei.parent.mkdir(parents=True, exist_ok=True)
    with datei.open("a", encoding="utf-8") as fh:
        for z in zeilen:
            fh.write(json.dumps(z, ensure_ascii=False) + "\n")
    return len(zeilen)


def lies_alle(daten_wurzel: Path, werk: str) -> list[dict[str, Any]]:
    """Alle Zeilen aller Monate, in Schreibreihenfolge. Kaputte Zeilen werden übersprungen."""
    ordner = log_ordner(daten_wurzel, werk)
    if not ordner.is_dir():
        return []
    zeilen: list[dict[str, Any]] = []
    for datei in sorted(ordner.glob("*.jsonl")):
        for roh in datei.read_text(encoding="utf-8").splitlines():
            roh = roh.strip()
            if not roh:
                continue
            try:
                zeilen.append(json.loads(roh))
            except json.JSONDecodeError:
                continue
    return zeilen


# ---------------------------------------------------------------------------
# Auswertung
# ---------------------------------------------------------------------------


@dataclass
class Regelbilanz:
    """Wie eine Stimmprofil-Regel beim Autor ankommt."""

    regel_id: str
    vorschlaege: int = 0
    angenommen: int = 0
    abgelehnt: int = 0
    zurueckgestellt: int = 0
    gruende: dict[str, int] | None = None

    @property
    def annahmequote(self) -> float | None:
        """Anteil angenommener an entschiedenen Vorschlägen — None, wenn noch nichts entschieden."""
        entschieden = self.angenommen + self.abgelehnt
        return self.angenommen / entschieden if entschieden else None


def bilanz_je_regel(zeilen: list[dict[str, Any]], *, ebene: str = "stil") -> list[Regelbilanz]:
    """Zählt aus, wie oft jede Regel vorgeschlagen und wie oft sie angenommen wurde.

    Das ist die Zahl, aus der ``status="beobachtung"`` im Stimmprofil wird: Eine
    Regel, deren Vorschläge der Autor überwiegend ablehnt, beschreibt seine
    Stimme nicht — egal wie überzeugend ein Modell sie fand. **In Python
    gezählt, nicht von einem Modell geschätzt**, das war der Plan von Anfang an.
    """
    je_regel: dict[str, Regelbilanz] = {}
    gruende: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for z in zeilen:
        if z.get("ebene") != ebene:
            continue
        rid = z.get("regel_id") or "kein-bezug"
        b = je_regel.setdefault(rid, Regelbilanz(regel_id=rid))
        b.vorschlaege += 1
        stand = z.get("entscheidung")
        if stand == "angenommen":
            b.angenommen += 1
        elif stand == "abgelehnt":
            b.abgelehnt += 1
            if z.get("grund"):
                gruende[rid][z["grund"]] += 1
        elif stand == "zurueckgestellt":
            b.zurueckgestellt += 1
    for rid, b in je_regel.items():
        b.gruende = dict(gruende.get(rid, {}))
    return sorted(je_regel.values(), key=lambda b: -b.vorschlaege)


def als_text(bilanzen: list[Regelbilanz]) -> str:
    zeilen = [f"{'Regel':44} {'Vorschl.':>8} {'ja':>4} {'nein':>5} {'offen':>5}  Annahme"]
    for b in bilanzen:
        q = f"{b.annahmequote:4.0%}" if b.annahmequote is not None else "   —"
        zeilen.append(
            f"{b.regel_id:44} {b.vorschlaege:8} {b.angenommen:4} {b.abgelehnt:5} "
            f"{b.zurueckgestellt:5}  {q}"
        )
        for grund, n in sorted((b.gruende or {}).items(), key=lambda x: -x[1])[:3]:
            zeilen.append(f"{'':44} {'':8} {'':4} {'':5} {'':5}  · {n}× {grund}")
    return "\n".join(zeilen)
