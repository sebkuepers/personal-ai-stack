"""BATCH workflow — ingest recent Gmail (inbox + sent) into the CRM.

Category: ingest (uses gmail + notion connectors → on_behalf_of + OAuth).

This is the workhorse for the twice-daily schedule (a Cloudflare cron triggers
it). Pipeline:

  1. A Gmail-reader agent fetches messages from the recent window (inbox + sent),
     returning structured JSON including each message's Gmail id.
  2. Each message is classified by the Studio CRM agent and mapped to Notion-
     shaped writes.
  3. Unless ``dry_run``, each is written via the durable Notion-writer agent,
     which **dedups by Gmail message id** (and stores it if the Interactions DB
     has a "Gmail Message ID" property) so overlapping windows don't duplicate.

Defaults to ``dry_run=True`` — the first runs show exactly what would be written.
Flip to ``dry_run=false`` once you've reviewed and (for reliable dedup) added a
"Gmail Message ID" text property to the Notion Interactions database.

Trigger:
  make execute workflow=crm-ingest-recent \
    input='{"window_hours":13,"max_emails":50,"dry_run":true}'
"""

from __future__ import annotations

from datetime import date

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as wf_mistral
from mistralai.workflows import workflow
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors

with workflow.unsafe.imports_passed_through():
    from workflows.crm.classify import classify_interaction
    from workflows.crm.agent_tools import get_today, extract_agent_text, parse_email_array
    from workflows.crm.notion import make_notion_writer_agent, render_triage_for_agent

from workflows.crm.agent_tools import classification_to_triage  # noqa: E402
from workflows.crm.config import AGENT_MODEL  # noqa: E402
from workflows.crm.connectors import gmail_connector, notion_connector  # noqa: E402
from workflows.crm.models import (  # noqa: E402
    CRMClassification,
    EmailItem,
    IngestItem,
    IngestRecentInput,
    IngestRecentReport,
    InteractionInput,
)


def _make_gmail_reader() -> wf_mistral.Agent:
    return wf_mistral.Agent(
        name="gmail-window-reader",
        model=AGENT_MODEL,
        instructions=(
            "You read Gmail and return structured data only. Search BOTH the inbox "
            "and sent mail for messages in the requested recent window, open each, and "
            "return ONLY a JSON array (no prose). Each element must be an object with "
            "keys: message_id (the Gmail message id), sender, subject, body, "
            "received_on (YYYY-MM-DD), direction ('received' or 'sent'). Keep body to "
            "the meaningful text. Skip promotions, social, and spam."
        ),
        connectors=[gmail_connector],
    )


@workflows.workflow.define(
    name="crm-ingest-recent",
    on_behalf_of=True,  # required: acts with your Gmail + Notion OAuth credentials
    workflow_display_name="CRM · Ingest Recent Email (batch)",
    workflow_description=(
        "Twice-daily batch: reads recent Gmail (inbox + sent), classifies each with the "
        "Studio CRM agent, and writes new interactions to Notion, deduped by Gmail "
        "message id. Dry run by default."
    ),
)
@uses_connectors(gmail_connector, notion_connector)
class CRMIngestRecentWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, params: IngestRecentInput) -> IngestRecentReport:
        # Step 1 — fetch the window of emails (inbox + sent) as JSON.
        reader = _make_gmail_reader()
        outputs = await wf_mistral.Runner.run(
            agent=reader,
            inputs=(
                f"Find emails from the last {params.window_hours} hours across the inbox "
                f"and sent mail (at most {params.max_emails}). Return ONLY the JSON array."
            ),
        )
        emails = [
            EmailItem.model_validate(e) for e in parse_email_array(await extract_agent_text(outputs))
        ][: params.max_emails]

        today = date.fromisoformat(await get_today())
        items: list[IngestItem] = []
        seen_ids: set[str] = set()

        for e in emails:
            # Within-batch dedup (cross-run dedup happens in the writer by message id).
            if e.message_id and e.message_id in seen_ids:
                continue
            if e.message_id:
                seen_ids.add(e.message_id)

            raw = await classify_interaction(
                text=e.body or e.snippet,
                subject=e.subject,
                interaction_type="Email",
                channel="Email",
            )
            classification = CRMClassification.model_validate(raw)
            inp = InteractionInput(
                text=e.body or e.snippet,
                subject=e.subject,
                interaction_type="Email",
                channel="Email",
                occurred_on=e.received_on,
            )
            triage = classification_to_triage(classification, inp, today)

            item = IngestItem(
                message_id=e.message_id,
                direction=e.direction,
                subject=e.subject,
                category=triage.interaction.category,
                contact_names=triage.interaction.contact_names,
                organization_names=triage.interaction.organization_names,
            )

            if params.dry_run:
                item.action = "classified"
            else:
                writer = make_notion_writer_agent()
                w_out = await wf_mistral.Runner.run(
                    agent=writer,
                    inputs=render_triage_for_agent(triage, gmail_message_id=e.message_id),
                )
                detail = await extract_agent_text(w_out)
                item.action = "skipped" if "duplicate" in detail.lower() else "written"
                item.detail = detail[:500]

            items.append(item)

        return IngestRecentReport(
            window_hours=params.window_hours,
            dry_run=params.dry_run,
            found=len(emails),
            processed=len(items),
            items=items,
        )
