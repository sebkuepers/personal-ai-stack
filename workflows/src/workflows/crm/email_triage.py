"""INBOX workflow — pull recent Gmail and classify each message.

Category: inbox (uses the Gmail connector → on_behalf_of + OAuth).

Pipeline:
  1. A durable Gmail-reader agent searches your inbox (search_threads /
     get_thread) and returns the matching emails as a JSON array.
  2. Each email is classified by the Studio CRM agent.
  3. Returns a DRY-RUN report (classifications + intended writes). It writes
     nothing to Notion and sends nothing — safe to run against a real inbox.

To actually file them, feed each triage to crm-notion-sync (a later step).

Trigger (defaults to last 7 days, max 10):
  make execute workflow=crm-email-triage \
    input='{"query":"newer_than:3d from:recruiter","max_emails":5}'
"""

from __future__ import annotations

from datetime import date

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as wf_mistral
from mistralai.workflows import workflow
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors

with workflow.unsafe.imports_passed_through():
    from workflows.crm.agent_tools import classification_to_triage
    from workflows.crm.connectors import gmail_connector
    from workflows.crm.models import (
        CRMClassification,
        EmailItem,
        EmailTriageInput,
        EmailTriageReport,
        InteractionInput,
    )
    # Config modules read a JSON file at import. Inside the Temporal sandbox that
    # is a restricted call (pathlib.Path.read_text) and the WORKER REFUSES TO
    # START — 'Failed validating workflow …'. Whether it trips depends on import
    # order, so it can pass locally and kill the container. Passthrough, always.
    from workflows.crm.config import AGENT_MODEL
    from workflows.crm.classify import classify_interaction
    from workflows.crm.agent_tools import get_today, extract_agent_text, parse_email_array


def _make_gmail_reader(query: str, max_emails: int) -> wf_mistral.Agent:
    return wf_mistral.Agent(
        name="gmail-reader",
        model=AGENT_MODEL,
        instructions=(
            "You read Gmail and return structured data. Search the user's inbox, "
            "open the matching messages, and return ONLY a JSON array (no prose). "
            "Each element must be an object with keys: sender, subject, snippet, "
            "body, received_on (YYYY-MM-DD). Keep body to the meaningful text."
        ),
        connectors=[gmail_connector],
    )


@workflows.workflow.define(
    name="crm-email-triage",
    on_behalf_of=True,  # required: acts with your Gmail OAuth credentials
    workflow_display_name="CRM · Triage Inbox (dry run)",
    workflow_description=(
        "Pulls recent Gmail via the connector and classifies each message with the "
        "Studio CRM agent. Dry run — writes/sends nothing."
    ),
)
@uses_connectors(gmail_connector)
class CRMEmailTriageWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, params: EmailTriageInput) -> EmailTriageReport:
        # Step 1 — agent fetches the emails and returns a JSON array.
        reader = _make_gmail_reader(params.query, params.max_emails)
        outputs = await wf_mistral.Runner.run(
            agent=reader,
            inputs=(
                f"Find the {params.max_emails} most recent emails matching this "
                f"Gmail query: {params.query!r}. Return ONLY the JSON array."
            ),
        )
        text = await extract_agent_text(outputs)
        emails = [EmailItem.model_validate(e) for e in parse_email_array(text)][: params.max_emails]

        # Step 2 — classify each email (dry run; no writes).
        today = date.fromisoformat(await get_today())
        triages = []
        for e in emails:
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
            triages.append(classification_to_triage(classification, inp, today))

        return EmailTriageReport(
            query=params.query,
            emails_found=len(emails),
            triages=triages,
        )
