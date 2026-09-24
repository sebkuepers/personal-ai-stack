"""The inbox domain's Gmail slot — bound to the DEPLOYMENT, not to a user.

The CRM domain uses ``on_behalf_of=True``: its workflows run while Sebastian
sits in the chat, and the connector acts with his OAuth session. The inbox
domain cannot, because its point is the nightly round — and a scheduled run
carries no user. The SDK says so itself (``core/workflow.py``):

    on_behalf_of=True cannot be combined with schedules
    because scheduled workflows lack user identity

``run_as="deployment"`` uses the worker's own identity instead. Measured end to
end on 2026-09-24: a workflow with ``on_behalf_of=False`` and this slot, fired
by a Studio schedule, completed with ``user_id = None`` and read the real
mailbox. See workflows/CLAUDE.md gotcha 19.

The slot is declared at module level, which is sandbox-safe (the SDK's own
examples do the same).
"""

from __future__ import annotations

from mistralai.workflows.plugins.mistralai.connectors import connector

from . import config

gmail_connector = connector(config.CONNECTOR_GMAIL, run_as="deployment")
