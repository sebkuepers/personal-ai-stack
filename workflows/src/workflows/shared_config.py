"""Auflösung der geteilten Konfigurationsdateien unter ``shared/``.

Verallgemeinert das Muster aus ``workflows/crm/config.py`` für mehrere Domänen.
Solange es nur die CRM-Domäne gab, reichte ein fest verdrahteter Pfad auf
``shared/crm.json``; mit einer zweiten Domäne braucht es eine Auflösung, die
jede Datei unterhalb von ``shared/`` findet.

Auflösungsreihenfolge für ``shared/<relpath>``:
  1. ``$SHARED_CONFIG_DIR`` falls gesetzt (vom Container-Image benutzt).
  2. Nach oben laufen, bis ein Verzeichnis ``shared/`` gefunden wird (lokale Entwicklung).

``crm/config.py`` benutzt weiterhin seine eigene Auflösung samt ``$CRM_CONFIG_PATH``
und bleibt unangetastet — es funktioniert und wird produktiv im Container gefahren.
Ein Umstieg ist später trivial: ``_CFG = load_shared("crm.json")``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def shared_dir() -> Path:
    """Verzeichnis ``shared/`` des Monorepos."""
    env = os.environ.get("SHARED_CONFIG_DIR")
    if env:
        return Path(env)
    # Kein .resolve(): Die Temporal-Sandbox verbietet pathlib.Path.resolve,
    # und __file__ ist beim Import ohnehin absolut.
    here = Path(__file__)
    for parent in here.parents:
        candidate = parent / "shared"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"Verzeichnis 'shared/' nicht gefunden beim Hochlaufen von {here}; "
        "SHARED_CONFIG_DIR setzen, damit es darauf zeigt."
    )


def load_shared(relpath: str) -> dict[str, Any]:
    """Lädt ``shared/<relpath>`` als JSON.

    ``relpath`` ist relativ zu ``shared/``, z. B. ``"buch.json"`` oder
    ``"buch/immer-wieder-ruegen.json"``.
    """
    path = shared_dir() / relpath
    if not path.is_file():
        raise FileNotFoundError(f"Geteilte Konfiguration nicht gefunden: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def expand(path: str) -> Path:
    """Expandiert ``~`` und Umgebungsvariablen in einem Pfad aus der Konfiguration."""
    return Path(os.path.expandvars(os.path.expanduser(path)))
