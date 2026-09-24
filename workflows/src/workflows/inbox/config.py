"""Configuration of the inbox domain — loaded from ``shared/inbox.json``.

The same pattern as ``workflows/book/config.py``: the file under ``shared/`` is
the single source of truth (agent IDs, models, connector slug, tool names,
label vocabulary, limits). The Gmail connector and its tool names are verified
live (2026-09-23, ``connectors.list_tools``) — ``shared/inbox.json`` carries
the real names (``search_threads``, ``create_draft``, ``label_*``), not the
older ones that once sat in ``shared/crm.json``.
"""

from __future__ import annotations

from typing import Any

from workflows.shared_config import load_shared

_CFG: dict[str, Any] = load_shared("inbox.json")

# --------------------------------------------------------------------------- #
# Studio agents — the cascade: the first stage (small) triages everything, the
# second (medium) re-checks the critical subset. IDs are assigned by
# agents/sync.py.
# --------------------------------------------------------------------------- #
INBOX_REVIEW_AGENT_ID: str = _CFG["agent"]["inbox_review_agent_id"]
INBOX_SECOND_REVIEW_AGENT_ID: str = _CFG["agent"]["inbox_second_review_agent_id"]

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
REVIEW_MODEL: str = _CFG["models"]["review"]  # first stage (small) — the bulk
SECOND_REVIEW_MODEL: str = _CFG["models"]["second_review"]  # second stage (medium)

# --------------------------------------------------------------------------- #
# Connector (lowercase slug, not the Studio display name)
# --------------------------------------------------------------------------- #
def _entries(section: dict) -> dict[str, str]:
    """A config section without its ``_comment`` keys.

    The JSON carries its reasoning next to the setting it justifies (repo rule
    6), and those keys must never reach a caller that iterates the map — a
    ``_comment`` in LABELS would otherwise be applied to a thread as a label.
    """
    return {k: v for k, v in section.items() if not k.startswith("_")}


CONNECTOR_GMAIL: str = _CFG["connectors"]["gmail"]["name"]
GMAIL_TOOLS: dict[str, str] = _entries(_CFG["connector_tools"]["gmail"])

# --------------------------------------------------------------------------- #
# Label vocabulary — the cleanup step applies exactly these labels, no others.
# --------------------------------------------------------------------------- #
LABELS: dict[str, str] = _entries(_CFG["labels"])

# --------------------------------------------------------------------------- #
# Controlled vocabularies — mirror the enums in the agent schema.
# --------------------------------------------------------------------------- #
_V = _CFG["vocab"]
TYPES: list[str] = list(_V["type"])
URGENCIES: list[str] = list(_V["urgency"])
FINANCE_TYPES: list[str] = list(_V["finance_type"])

# --------------------------------------------------------------------------- #
# Mistral Library — the rolling context dossier for Vibe
# --------------------------------------------------------------------------- #
LIBRARY_NAME: str = _CFG["mistral"]["library_name"]
LIBRARY_ID: str = _CFG["mistral"]["library_id"]

# --------------------------------------------------------------------------- #
# Deliberate ceilings
# --------------------------------------------------------------------------- #
_L = _CFG["limits"]
MAX_EMAILS: int = _L["max_emails"]
WINDOW_HOURS: int = _L["window_hours"]
MAX_BODY_CHARS: int = _L["max_body_chars"]
