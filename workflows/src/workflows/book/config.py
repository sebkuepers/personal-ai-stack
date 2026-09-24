"""Configuration of the book domain — loaded from ``shared/``.

Two levels, matching the naming convention:

* **Domain** (``shared/book.json``) — agents, models, vocabularies, review
  criteria, typesetting spec. Applies to every book, exposed as module
  constants.
* **Work** (``shared/book/<slug>.json``) — title, paths, chapter scaffold,
  touchstones. Fetched through :func:`load_work`, because there can be several.

This module is pure (file access at import only) and may therefore be imported
normally from workflow code — it does not need to cross the sandbox boundary.

The controlled vocabularies keep their German values on purpose: they are the
categories of German copy-editing and the wording the author reads. Only the
identifiers are English.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

from workflows.shared_config import expand, load_shared

_CFG: dict[str, Any] = load_shared("book.json")

# ---------------------------------------------------------------------------
# Studio agents  (IDs are assigned by agents/sync.py and recorded in the JSON)
# ---------------------------------------------------------------------------
AGENTS: dict[str, str | None] = {
    k: v for k, v in _CFG["agents"].items() if not k.startswith("_")
}

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
MODELS: dict[str, str] = _CFG["models"]

# ---------------------------------------------------------------------------
# Controlled vocabularies — mirror the enums in the agent schemas
# ---------------------------------------------------------------------------
_V = _CFG["vocabulary"]
LEVELS: list[str] = _V["levels"]
CORRECTION_KINDS: list[str] = _V["correction_kinds"]
STYLE_PROBLEMS: list[str] = _V["style_problems"]
SEVERITIES: list[str] = _V["severities"]
DECISIONS: list[str] = _V["decisions"]
REJECTION_REASONS: list[str] = _V["rejection_reasons"]
RULE_STATUS: list[str] = _V["rule_status"]
INTENTIONAL_COLLOQUIALISMS: dict[str, str] = {
    k: v for k, v in _V.get("intentional_colloquialisms", {}).items() if not k.startswith("_")
}

# ---------------------------------------------------------------------------
# Deliberate ceilings
# ---------------------------------------------------------------------------
_L = _CFG["limits"]
MAX_STYLE_FINDINGS: int = _L["max_style_findings_per_section"]
MAX_VOICE_RULES: int = _L["max_voice_rules"]
MIN_EVIDENCE: int = _L["min_evidence_per_voice_rule"]
REJECTION_RATE_FOR_OBSERVATION: float = _L["rejection_rate_for_observation"]

# ---------------------------------------------------------------------------
# Scrivener structure and typesetting spec
# ---------------------------------------------------------------------------
SCRIVENER: dict[str, Any] = _CFG["scrivener"]
TYPESET: dict[str, Any] = _CFG["typeset"]


@cache
def load_work(slug: str) -> dict[str, Any]:
    """Load the work configuration ``shared/book/<slug>.json``.

    The entries under ``paths`` are expanded to absolute :class:`Path` objects
    so that ``~`` does not have to be handled at every call site.
    """
    work = load_shared(f"book/{slug}.json")
    work["paths"] = {
        k: expand(v)
        for k, v in work["paths"].items()
        if not k.startswith("_") and isinstance(v, str)
    }
    return work


def scrivener_path(slug: str, *, test: bool = False) -> Path:
    """Path to a work's Scrivener package.

    With ``test=True`` the test copy — every write-back is rehearsed there first.
    """
    paths = load_work(slug)["paths"]
    return paths["scrivener_test"] if test else paths["scrivener"]


def work_path(slug: str, name: str) -> Path:
    """A named path from the work configuration's ``paths`` (``context``, ``pdf``, …)."""
    return load_work(slug)["paths"][name]


def chapter_by_title(slug: str, title: str) -> dict[str, Any] | None:
    """Find a chapter of the work by its binder title.

    The binder only knows the title; subtitle, review criteria and reading
    order live exclusively in the work configuration.
    """
    for chapter in load_work(slug)["chapters"]:
        if chapter["title"] == title:
            return chapter
    return None
