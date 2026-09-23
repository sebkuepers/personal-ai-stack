"""Agent-Evaluation für den ganzen Stack — domänenunabhängig.

Entstanden beim Buch-Lektorat, aber bewusst nicht dort angesiedelt: Jeder Agent
im Repo wirft dieselbe Frage auf — liefert er das Richtige, und woran merkt man
eine Verschlechterung?

    from evalkit import Fall, Konfiguration, vergleiche, agent_definition

Aufbau:
  modelle.py  Fall, Prüfung, Ergebnis, Bilanz — was gemessen wird
  runner.py   führt Fälle gegen Konfigurationen aus — wie gemessen wird
  __main__.py generisches CLI: python -m evalkit --agent <name> --faelle <datei>

Eine Domäne steuert nur zwei Dinge bei: die Testfälle (welche Eingaben, welche
Zusicherungen) und optional einen Generator dafür. Alles andere ist hier.
"""

from .modelle import Bilanz, Ergebnis, Fall, Pruefung, bilanziere, hole, pruefe
from .runner import (
    STANDARD_KONFIGURATIONEN,
    Konfiguration,
    agent_definition,
    einmal,
    vergleiche,
)

__all__ = [
    "STANDARD_KONFIGURATIONEN",
    "Bilanz",
    "Ergebnis",
    "Fall",
    "Konfiguration",

    "Pruefung",
    "agent_definition",
    "bilanziere",
    "einmal",
    "hole",
    "pruefe",
    "vergleiche",
]
