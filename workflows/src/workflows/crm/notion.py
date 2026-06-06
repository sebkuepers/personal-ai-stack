"""Notion CRM writer — turns intended writes into real Notion pages.

Two approaches, both confirmed against the installed SDK examples:

1. ``make_notion_writer_agent`` (agent-driven) — RECOMMENDED. Hands the Notion
   connector to a durable agent together with your CRM schema (NOTION_WRITER_
   CONTEXT). The model discovers and calls the right Notion MCP tools
   autonomously (search → find-or-create → create page → relate). This is robust
   to the exact Notion tool names/parameters.

2. ``create_notion_page`` (direct) — a deterministic ``ToolCallClient`` call to
   the ``notion-create-pages`` tool (the exact name used in the SDK's own
   Notion example). Use when you want full control and known inputs.

Both require the workflow to be ``on_behalf_of=True`` and decorated with
``@uses_connectors(notion_connector)``.
"""

from __future__ import annotations

from typing import Any

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as wf_mistral
from mistralai.workflows import Depends
from mistralai.workflows.plugins.mistralai.connectors import ToolCallClient

from . import config
from .connectors import notion_connector
from .models import InteractionTriage
from .prompts import NOTION_WRITER_CONTEXT


def make_notion_writer_agent() -> wf_mistral.Agent:
    """Build the durable agent that writes a triage result into the Notion CRM."""
    return wf_mistral.Agent(
        name="notion-crm-writer",
        model=config.AGENT_MODEL,
        instructions=NOTION_WRITER_CONTEXT,
        connectors=[notion_connector],
    )


def render_triage_for_agent(triage: InteractionTriage, gmail_message_id: str | None = None) -> str:
    """Render an InteractionTriage as a clear instruction for the writer agent.

    When ``gmail_message_id`` is given, the writer is told to dedup and store it
    (see NOTION_WRITER_CONTEXT) — so re-runs of the batch don't create duplicates.
    """
    i = triage.interaction
    lines = [
        "Write the following interaction into the Notion CRM, "
        "finding-or-creating the related Contact(s) and Organization(s).",
        "",
    ]
    if gmail_message_id:
        lines.append(f"Gmail Message ID: {gmail_message_id}")
    lines += [
        f"Title: {i.title}",
        f"Date: {i.occurred_on}",
        f"Interaction Type: {i.interaction_type}",
        f"Channel: {i.channel}",
        f"Category: {i.category or '(leave empty)'}",
        f"Sub-Category: {i.sub_category or '(leave empty)'}",
        f"Sentiment: {i.sentiment}",
        f"Subject: {i.subject or ''}",
        f"AI Summary: {i.ai_summary or ''}",
        f"AI Analysis: {i.ai_analysis or ''}",
        f"Follow-up Date: {i.follow_up_date or '(none)'}",
        f"Follow-up Needed: {i.follow_up_needed}",
        f"Contacts to relate: {', '.join(i.contact_names) or '(none)'}",
        f"Organizations to relate: {', '.join(i.organization_names) or '(none)'}",
        "",
        "Contact details (set Priority + Auto-Tags on each):",
    ]
    for c in triage.contacts:
        lines.append(f"  - {c.name} | priority={c.priority} | auto_tags={', '.join(c.auto_tags) or '(none)'}")
    lines.append("Raw content:")
    lines.append(i.raw_content or "")
    return "\n".join(lines)


@workflows.activity(name="create-notion-page")
async def create_notion_page(
    parent_page_id: str,
    title: str,
    content: str,
    notion: ToolCallClient = Depends(notion_connector),
) -> dict[str, Any]:
    """Direct path: create a single Notion page via the connector's tool.

    Mirrors the SDK's own Notion example (tool name ``notion-create-pages``).
    """
    return await notion.call_tool(  # type: ignore[no-any-return]
        tool_name="notion-create-pages",
        arguments={
            "parent": {"page_id": parent_page_id},
            "pages": [{"properties": {"title": title}, "content": content}],
        },
    )
