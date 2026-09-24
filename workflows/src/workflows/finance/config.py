"""Configuration of the finance domain — loaded from ``shared/``.

Two levels, as in the book domain:

* **Domain** (``shared/finance.json``, checked in) — categories, models, tidy
  rules, library settings. No personal path, no IBAN, no account name.
* **Machine** (``shared/finance/paths.json``, gitignored) — where the
  statements actually live, which accounts exist, which workbooks are read.

The split is not cosmetic: this repo is public. The domain is shared, the
bookkeeping is not. ``paths.example.json`` sits next to the real file as the
template.

This module is pure (file access at import only) and may therefore be imported
normally from workflow code.

The category *keys* are English like everything this repo names. Their
``label`` and the ``rows`` they map to stay German — the rows are quotations
from the author's own workbook, and the labels are what he reads in the report.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from workflows.shared_config import expand, load_shared

_CFG: dict[str, Any] = load_shared("finance.json")


def _entries(section: dict[str, Any]) -> dict[str, Any]:
    """A config section without its ``_comment`` keys.

    The JSON carries its reasoning next to the setting it justifies (repo rule
    6), and those keys must never reach a caller that iterates the map — a
    ``_comment`` in the category table would otherwise become a category.
    """
    return {k: v for k, v in section.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Categories — derived from the author's planning workbook, not invented here
# ---------------------------------------------------------------------------
CATEGORIES: dict[str, dict[str, Any]] = _entries(_CFG["categories"])
CATEGORY_KEYS: list[str] = list(CATEGORIES)


def label(category: str) -> str:
    """The German word the author reads for a category key."""
    return CATEGORIES.get(category, {}).get("label", category)


# ---------------------------------------------------------------------------
# Models and agents
# ---------------------------------------------------------------------------
MODELS: dict[str, str] = _entries(_CFG["models"])
AGENTS: dict[str, str | None] = _entries(_CFG["agent"])
LIMITS: dict[str, int] = _entries(_CFG["limits"])

# ---------------------------------------------------------------------------
# Library — the summaries Vibe reads. Aggregates only, never a raw booking.
# ---------------------------------------------------------------------------
_LIB = _CFG["library"]
LIBRARY_ENABLED: bool = bool(_LIB["enabled"])
LIBRARY_NAME: str = _LIB["name"]
LIBRARY_ID: str | None = _LIB["id"]
LIBRARY_DOCUMENTS: dict[str, str] = _entries(_LIB["documents"])

# ---------------------------------------------------------------------------
# Tidy rules — data, so a wrong target is a JSON edit rather than a patch
# ---------------------------------------------------------------------------
TIDY: dict[str, Any] = _entries(_CFG["tidy"])


@cache
def paths() -> dict[str, Any]:
    """The machine-local paths (gitignored).

    Raises with an instruction rather than a stack trace when the file is
    missing — on a fresh checkout that is the expected state, not a bug.
    """
    try:
        return load_shared("finance/paths.json")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "shared/finance/paths.json fehlt — shared/finance/paths.example.json "
            "kopieren und die eigenen Pfade eintragen. Die Datei ist gitignored."
        ) from exc  # author-facing: stays German


def root() -> Path:
    """The one folder that holds everything private-financial."""
    return expand(paths()["root"])


def folder_of(name: str) -> Path:
    """A folder under the root, e.g. ``folder_of("Konten")``."""
    return root() / name


# Kept as the shorter name the rest of the code already uses.
folder = folder_of


def planning_workbook() -> Path:
    """The author's top-level planning document. **Read only, always.**"""
    return expand(paths()["planning_workbook"]["path"])


def boat_workbook() -> Path:
    """His boat workbook — read only, and the touchstone for the boat total."""
    return expand(paths()["boat_workbook"]["path"])


READ_ONLY_KEYS = ("planning_workbook", "boat_workbook")


def read_only_paths() -> list[Path]:
    """Every workbook this repo is forbidden to write.

    A test walks this list against the code: no writing path may point at one
    of them. They are his, they are maintained by hand, and a program that
    edits them would destroy the very thing that makes this domain possible.
    """
    out = []
    for key in READ_ONLY_KEYS:
        entry = paths().get(key)
        if entry:
            out.append(expand(entry["path"]))
    return out


def latest_depot() -> Path | None:
    """The most recent depot export.

    By modification time, not by name: the broker calls every download
    ``investments.csv`` and macOS appends " (1)", which sorts BEFORE the
    original — picking the alphabetically last one served a two-month-old
    portfolio while the fresh one lay next to it.
    """
    folder = folder_of("Depot")
    files = [f for f in folder.glob("*.csv")] if folder.is_dir() else []
    return max(files, key=lambda f: f.stat().st_mtime) if files else None


def accounts() -> list[dict[str, str]]:
    """The configured accounts — id, label, parser dialect. No IBAN in code."""
    return list(paths().get("accounts", []))
