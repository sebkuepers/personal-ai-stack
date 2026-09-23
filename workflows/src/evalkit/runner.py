"""Agent-Konfigurationen gegen Testfälle fahren — domänenunabhängig.

Getestet wird der **echte Agent** mit seinen echten Instruktionen: ``model`` und
``completion_args`` lassen sich pro Aufruf überschreiben, ohne die Definition in
Studio anzufassen. Gemessen wird also das, was später auch läuft.

Bewusst ohne die nachgelagerten Filter einer Domäne — sonst misst man die
Filter, nicht den Agenten, und weiß nie, ob eine Modelländerung etwas gebracht
hat.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .modelle import Bilanz, Ergebnis, Fall, bilanziere, pruefe

API = "https://api.mistral.ai/v1/chat/completions"


@dataclass(frozen=True)
class Konfiguration:
    """Eine zu vergleichende Einstellung."""

    name: str
    modell: str
    reasoning: str | None = None
    temperatur: float = 0.1

    @property
    def max_tokens(self) -> int:
        # Reasoning verbraucht leicht 2000+ Tokens, bevor die eigentliche Antwort
        # beginnt. Zu knapp bemessen kommt eine abgeschnittene Antwort zurück —
        # und die sieht aus wie ein Modellfehler, ist aber ein Budgetfehler.
        #
        # Gemessen an GLM: 4000 reichten nicht, die Antworten brachen mitten im
        # JSON ab und zählten als Modellfehler. Mistral-Modelle hören von selbst
        # früher auf, für sie kostet die höhere Grenze also nichts. Wer Modelle
        # vergleicht, muss ihnen denselben Platz geben.
        return 16000 if self.reasoning else 12000


# Beide Modelle akzeptieren laut API nur 'none' oder 'high';
# 'minimal'/'low'/'medium'/'xhigh' werden mit HTTP 400 abgelehnt.
STANDARD_KONFIGURATIONEN = [
    Konfiguration("small/none", "mistral-small-latest"),
    Konfiguration("small/high", "mistral-small-latest", "high"),
    Konfiguration("medium/none", "mistral-medium-latest"),
    Konfiguration("medium/high", "mistral-medium-latest", "high"),
]


def agent_definition(repo: Path, name: str) -> tuple[str, dict]:
    """Instruktionen und Antwortschema eines Agents aus seiner Repo-Definition.

    Die Datei ist die Quelle der Wahrheit (siehe ``agents/README.md``), also
    misst man hier genau das, was auch in Studio steht.
    """
    d = json.loads((repo / "agents" / f"{name}.json").read_text(encoding="utf-8"))
    return d["instructions"], d["completion_args"]["response_format"]


def _antworttext(msg: dict) -> str:
    """Holt den Antworttext; bei aktivem Reasoning liegen Thinking-Chunks davor."""
    inhalt = msg.get("content")
    if isinstance(inhalt, str):
        return inhalt
    return "".join(
        t.get("text", "")
        for t in (inhalt or [])
        if isinstance(t, dict) and t.get("type") == "text"
    )


def einmal(
    fall: Fall,
    konf: Konfiguration,
    instruktionen: str,
    schema: dict,
    *,
    zaehlpfad: str | None = None,
) -> Ergebnis:
    """Führt einen Fall unter einer Konfiguration aus."""
    body: dict = {
        "model": konf.modell,
        "messages": [
            {"role": "system", "content": instruktionen},
            {"role": "user", "content": fall.eingabe},
        ],
        "temperature": konf.temperatur,
        "max_tokens": konf.max_tokens,
        "response_format": schema,
    }
    if konf.reasoning:
        body["reasoning_effort"] = konf.reasoning

    r = urllib.request.Request(
        API,
        method="POST",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(r) as resp:
            d = json.loads(resp.read())
        antwort = json.loads(_antworttext(d["choices"][0]["message"]))
        e = pruefe(fall, antwort, zaehlpfad=zaehlpfad)
        e.dauer = time.time() - t0
        e.tokens = d.get("usage", {}).get("completion_tokens", 0)
        return e
    except Exception as exc:  # noqa: BLE001 — jeder Fehler ist ein Datenpunkt
        return Ergebnis(
            fall_id=fall.id, dauer=time.time() - t0, fehler=f"{type(exc).__name__}: {exc}"
        )


def vergleiche(
    faelle: list[Fall],
    konfigurationen: list[Konfiguration],
    instruktionen: str,
    schema: dict,
    *,
    laeufe: int = 1,
    zaehlpfad: str | None = None,
    fortschritt=None,  # noqa: ANN001 — optionaler Callback(konf_name, fall_id)
) -> list[tuple[Bilanz, list[Ergebnis]]]:
    """Fährt alle Fälle gegen alle Konfigurationen und bilanziert."""
    ergebnis: list[tuple[Bilanz, list[Ergebnis]]] = []
    for konf in konfigurationen:
        alle: list[Ergebnis] = []
        for _ in range(laeufe):
            for f in faelle:
                if fortschritt:
                    fortschritt(konf.name, f.id)
                alle.append(einmal(f, konf, instruktionen, schema, zaehlpfad=zaehlpfad))
        ergebnis.append((bilanziere(konf.name, faelle * laeufe, alle), alle))
    return ergebnis
