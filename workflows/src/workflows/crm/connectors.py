"""Connector slot definitions for the personal-CRM workflows.

These ``ConnectorSlot`` objects bind to the connectors you've connected in
Studio (Context › Connectors). They are declared at module level — that's
sandbox-safe (the SDK's own examples do the same) — and reused by:
  - ``@uses_connectors(...)`` on the workflow class, and
  - ``Agent(connectors=[...])`` / ``Depends(...)`` inside activities.

A workflow that uses any of these must be defined with ``on_behalf_of=True``
so it acts with your OAuth credentials. The first run pauses with an auth URL.
"""

from __future__ import annotations

from mistralai.workflows.plugins.mistralai.connectors import connector

from . import config

notion_connector = connector(config.CONNECTOR_NOTION)
gmail_connector = connector(config.CONNECTOR_GMAIL)
