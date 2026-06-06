"""ASSISTANT workflow — find due follow-ups in Notion and draft reminder emails.

Category: assistant (uses Notion + Gmail connectors → on_behalf_of + OAuth).

A durable agent with both connectors:
  1. Searches the Notion Interactions/Contacts for items where a follow-up is
     due (Follow-up Needed = true and Follow-up Date <= today + horizon).
  2. For each, drafts a short, friendly reminder email in Gmail
     (draft_gmail_email — it DRAFTS only, never sends).
  3. Returns a digest of what it found and drafted.

SCHEDULING NOTE: this workflow uses on_behalf_of, and the SDK forbids combining
on_behalf_of=True with `schedules=[...]` (a scheduled run has no user OAuth
session). To run it daily, trigger it on a schedule from outside (cron / the
executions API) rather than as an in-SDK Schedule. See README.

Trigger:
  make execute workflow=crm-followup-digest \
    input='{"draft_reminders": true, "horizon_days": 0}'
"""

from __future__ import annotations

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as wf_mistral
from mistralai.workflows import workflow
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors

with workflow.unsafe.imports_passed_through():
    from workflows.crm.agent_tools import get_today, extract_agent_text

from workflows.crm import config  # noqa: E402
from workflows.crm.connectors import gmail_connector, notion_connector  # noqa: E402
from workflows.crm.models import FollowUpDigestInput  # noqa: E402


def _make_digest_agent() -> wf_mistral.Agent:
    return wf_mistral.Agent(
        name="crm-followup-digest",
        model=config.DIGEST_MODEL,
        instructions=(
            "You run Sebastian's CRM follow-up digest. You have Notion and Gmail.\n"
            f"- Notion Interactions data source id: {config.NOTION_DB['interactions']}\n"
            f"- Notion Contacts data source id: {config.NOTION_DB['contacts']}\n"
            "Use notion-search / notion-fetch to find Interactions where "
            "'Follow-up Needed' is true and 'Follow-up Date' is due. For each due "
            "item, look up the related Contact's email. If asked to draft reminders, "
            "use draft_gmail_email to create a short, warm reminder draft (NEVER "
            "send — drafts only). Then return a concise digest: who, why, due date, "
            "and whether a draft was created."
        ),
        connectors=[notion_connector, gmail_connector],
    )


@workflows.workflow.define(
    name="crm-followup-digest",
    on_behalf_of=True,  # required: acts with your Notion + Gmail OAuth credentials
    workflow_display_name="CRM · Follow-up Digest",
    workflow_description=(
        "Finds due follow-ups in the Notion CRM and drafts reminder emails in Gmail "
        "(drafts only, never sends)."
    ),
)
@uses_connectors(notion_connector, gmail_connector)
class CRMFollowUpDigestWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, params: FollowUpDigestInput) -> str:
        today = await get_today()
        action = (
            "Draft reminder emails for each due follow-up."
            if params.draft_reminders
            else "Do NOT draft anything; just list the due follow-ups."
        )
        agent = _make_digest_agent()
        outputs = await wf_mistral.Runner.run(
            agent=agent,
            inputs=(
                f"Today is {today}. Run my follow-up digest including items due "
                f"within {params.horizon_days} day(s). {action}"
            ),
        )
        return await extract_agent_text(outputs)
