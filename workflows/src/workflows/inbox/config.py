"""Konfiguration der inbox-Domäne — geladen aus ``shared/inbox.json``.

Dasselbe Muster wie ``workflows/buch/config.py``: die Datei unter ``shared/``
ist die einzige Quelle der Wahrheit (Agent-ID, Modelle, Connector-Slug,
Tool-Namen, Label-Vokabular, Grenzen). Der Gmail-Connector und seine
Tool-Namen sind live verifiziert (2026-09-23, ``connectors.list_tools``) —
``shared/inbox.json`` führt die echten Namen (``search_threads``,
``create_draft``, ``label_*``), nicht die älteren aus ``shared/crm.json``.
"""

from __future__ import annotations

from typing import Any

from workflows.shared_config import load_shared

_CFG: dict[str, Any] = load_shared("inbox.json")

# --------------------------------------------------------------------------- #
# Studio agents — die Kaskade: Erstblick (small) sichtet, Zweitblick (medium)
# prüft die kritische Teilmenge nach. IDs vergibt agents/sync.py.
# --------------------------------------------------------------------------- #
INBOX_REVIEW_AGENT_ID: str = _CFG["agent"]["inbox_review_agent_id"]
INBOX_SECOND_REVIEW_AGENT_ID: str = _CFG["agent"]["inbox_second_review_agent_id"]

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
REVIEW_MODEL: str = _CFG["models"]["review"]  # first stage (small) — the bulk
SECOND_REVIEW_MODEL: str = _CFG["models"]["second_review"]  # second stage (medium) — critical cases

# --------------------------------------------------------------------------- #
# Connector (lowercase slug, nicht der Studio-Display-Name)
# --------------------------------------------------------------------------- #
CONNECTOR_GMAIL: str = _CFG["connectors"]["gmail"]["name"]
GMAIL_TOOLS: dict[str, str] = dict(_CFG["connector_tools"]["gmail"])

# --------------------------------------------------------------------------- #
# Label-Vokabular — Phase 2 wendet genau diese Labels an, keine anderen.
# --------------------------------------------------------------------------- #
LABELS: dict[str, str] = dict(_CFG["labels"])

# --------------------------------------------------------------------------- #
# Kontrollierte Vokabulare — spiegeln die Enums im Agent-Schema.
# --------------------------------------------------------------------------- #
_V = _CFG["vocab"]
TYPES: list[str] = list(_V["type"])
URGENCIES: list[str] = list(_V["urgency"])
FINANCE_TYPES: list[str] = list(_V["finance_type"])

# --------------------------------------------------------------------------- #
# Mistral Library — das rollierende Kontext-Dossier für Vibe
# --------------------------------------------------------------------------- #
LIBRARY_NAME: str = _CFG["mistral"]["library_name"]
LIBRARY_ID: str = _CFG["mistral"]["library_id"]

# --------------------------------------------------------------------------- #
# Bewusste Obergrenzen
# --------------------------------------------------------------------------- #
_G = _CFG["limits"]
MAX_EMAILS: int = _G["max_emails"]
WINDOW_HOURS: int = _G["window_hours"]
MAX_BODY_ZEICHEN: int = _G["max_body_zeichen"]
