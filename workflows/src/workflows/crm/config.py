"""Config for the personal-CRM workflows — loaded from the shared single source of truth.

The canonical IDs and vocabularies live in ``shared/crm.json`` at the monorepo
root, so the Python workflows and the TypeScript MCP server stay in sync from one
file. This module loads that JSON and re-exposes the same constants the rest of
the package already imports (``CRM_CLASSIFICATION_AGENT_ID``, ``NOTION_DB`` …),
so nothing downstream changed.

Resolution order for ``shared/crm.json``:
  1. ``$CRM_CONFIG_PATH`` if set (used by the container image, see Dockerfile).
  2. Walk up from this file until a ``shared/crm.json`` is found (local dev).
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _find_shared_config() -> Path:
    env = os.environ.get("CRM_CONFIG_PATH")
    if env:
        return Path(env)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "shared" / "crm.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(
        "shared/crm.json not found by walking up from "
        f"{here}; set CRM_CONFIG_PATH to point at it."
    )


_CFG = json.loads(_find_shared_config().read_text(encoding="utf-8"))

# ---------------------------------------------------------------------------
# Studio agent
# ---------------------------------------------------------------------------
CRM_CLASSIFICATION_AGENT_ID: str = _CFG["agent"]["crm_classification_agent_id"]

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
CLASSIFY_MODEL: str = _CFG["models"]["classify"]
AGENT_MODEL: str = _CFG["models"]["agent"]
DIGEST_MODEL: str = _CFG["models"]["digest"]

# Names that refer to you — filtered out of people_mentioned so you never end up
# as a contact in your own CRM. Lower-cased; matched case-insensitively.
USER_ALIASES: set[str] = {a.lower() for a in _CFG["user_aliases"]}

# ---------------------------------------------------------------------------
# Notion CRM data-source (collection) IDs + page URLs
# ---------------------------------------------------------------------------
NOTION_DB: dict[str, str] = dict(_CFG["notion"]["databases"])
NOTION_URL: dict[str, str] = dict(_CFG["notion"]["urls"])

# ---------------------------------------------------------------------------
# Connector identifiers (lowercase API slugs, NOT the Studio display names) and
# their exact tool names.
# ---------------------------------------------------------------------------
CONNECTOR_NOTION: str = _CFG["connectors"]["notion"]["name"]
CONNECTOR_GMAIL: str = _CFG["connectors"]["gmail"]["name"]

NOTION_TOOLS: dict[str, str] = dict(_CFG["connector_tools"]["notion"])
GMAIL_TOOLS: dict[str, str] = dict(_CFG["connector_tools"]["gmail"])

# ---------------------------------------------------------------------------
# Controlled vocabularies — must stay in sync with the Notion select options.
# ---------------------------------------------------------------------------
CATEGORIES: list[str] = list(_CFG["vocab"]["categories"])
SUB_CATEGORIES: list[str] = list(_CFG["vocab"]["sub_categories"])
INTERACTION_TYPES: list[str] = list(_CFG["vocab"]["interaction_types"])
SENTIMENTS: list[str] = list(_CFG["vocab"]["sentiments"])
PRIORITIES: list[str] = list(_CFG["vocab"]["priorities"])
AUTO_TAGS: list[str] = list(_CFG["vocab"]["auto_tags"])
