"""Konfiguration der Buch-Domäne — geladen aus ``shared/``.

Zwei Ebenen, entsprechend der Namenskonvention:

* **Domäne** (``shared/buch.json``) — Agents, Modelle, Vokabulare, Judge-Kriterien,
  Satzspezifikation. Gilt für jedes Buch, liegt als Modulkonstanten vor.
* **Werk** (``shared/buch/<slug>.json``) — Titel, Pfade, Kapitelgerüst, Prüfsteine.
  Wird über :func:`lade_werk` geholt, weil es mehrere geben kann.

Dieses Modul ist rein (nur Dateizugriff beim Import) und darf deshalb in
Workflow-Code normal importiert werden — es muss nicht durch die Sandbox-Grenze.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from workflows.shared_config import expand, load_shared

_CFG: dict[str, Any] = load_shared("buch.json")

# ---------------------------------------------------------------------------
# Studio-Agents  (IDs werden von agents/sync.py vergeben und hier eingetragen)
# ---------------------------------------------------------------------------
AGENTS: dict[str, str | None] = {
    k: v for k, v in _CFG["agents"].items() if not k.startswith("_")
}

# ---------------------------------------------------------------------------
# Modelle
# ---------------------------------------------------------------------------
MODELS: dict[str, str] = _CFG["models"]

# ---------------------------------------------------------------------------
# Kontrollierte Vokabulare — spiegeln die Enums in den Agent-Schemata
# ---------------------------------------------------------------------------
_V = _CFG["vokabular"]
EBENEN: list[str] = _V["ebenen"]
KORREKTUR_ARTEN: list[str] = _V["korrektur_arten"]
STIL_PROBLEME: list[str] = _V["stil_probleme"]
SCHWEREGRADE: list[str] = _V["schweregrade"]
ENTSCHEIDUNGEN: list[str] = _V["entscheidungen"]
ABLEHNUNGSGRUENDE: list[str] = _V["ablehnungsgruende"]
REGEL_STATUS: list[str] = _V["regel_status"]
GEWOLLTE_UMGANGSSPRACHE: dict[str, str] = {
    k: v for k, v in _V.get("gewollte_umgangssprache", {}).items() if not k.startswith("_")
}

# ---------------------------------------------------------------------------
# Bewertung
# ---------------------------------------------------------------------------
JUDGE_BACKEND: str = _CFG["judges"]["backend"]
JUDGE_KRITERIEN: dict[str, dict[str, Any]] = {
    k: v for k, v in _CFG["judges"]["kriterien"].items() if not k.startswith("_")
}
AKTIVE_JUDGES: list[str] = [k for k, v in JUDGE_KRITERIEN.items() if v.get("aktiv")]

# ---------------------------------------------------------------------------
# Bewusste Obergrenzen
# ---------------------------------------------------------------------------
_G = _CFG["grenzen"]
MAX_STIL_BEFUNDE: int = _G["max_stil_befunde_pro_abschnitt"]
MAX_STIMMREGELN: int = _G["max_stimmregeln"]
MIN_BELEGE: int = _G["min_belege_pro_stimmregel"]
ABLEHNQUOTE_FUER_BEOBACHTUNG: float = _G["ablehnquote_fuer_beobachtung"]

# ---------------------------------------------------------------------------
# Scrivener-Struktur und Satzspezifikation
# ---------------------------------------------------------------------------
SCRIVENER: dict[str, Any] = _CFG["scrivener"]
SATZ: dict[str, Any] = _CFG["satz"]


@cache
def lade_werk(slug: str) -> dict[str, Any]:
    """Lädt die Werk-Konfiguration ``shared/buch/<slug>.json``.

    Die Pfade unter ``pfade`` werden dabei zu absoluten :class:`Path`-Objekten
    expandiert, damit ``~`` nicht an jeder Aufrufstelle einzeln behandelt wird.
    """
    werk = load_shared(f"buch/{slug}.json")
    werk["pfade"] = {
        k: expand(v)
        for k, v in werk["pfade"].items()
        if not k.startswith("_") and isinstance(v, str)
    }
    return werk


def scrivener_pfad(slug: str, *, test: bool = False) -> Path:
    """Pfad zum Scrivener-Paket eines Werks.

    Mit ``test=True`` die Testkopie — dort wird jeder Write-back zuerst geprobt.
    """
    pfade = lade_werk(slug)["pfade"]
    return pfade["scrivener_test"] if test else pfade["scrivener"]


def kapitel_nach_titel(slug: str, titel: str) -> dict[str, Any] | None:
    """Findet ein Kapitel des Werks über seinen Binder-Titel.

    Der Binder kennt nur den Titel; Untertitel, Prüfkriterien und Leseordnung
    stehen ausschließlich in der Werk-Konfiguration.
    """
    for kapitel in lade_werk(slug)["kapitel"]:
        if kapitel["titel"] == titel:
            return kapitel
    return None
