"""WRITE workflow — classify one interaction and write it into the Notion CRM.

Category: crm-write (uses the Notion connector → on_behalf_of + OAuth).

Pipeline:
  1. Trigger the Studio CRM Classification agent (same as the core workflow).
  2. Map → Notion-shaped intended writes (pure).
  3. Hand the result to a durable Notion-writer agent that has the Notion
     connector. The agent finds-or-creates the Contact(s) and Organization(s)
     and creates the related Interactions row, using your live Notion tools
     (notion-search / notion-fetch / notion-create-pages / notion-update-page).

The first execution pauses with an OAuth URL for Notion; after you authorise,
it resumes and every later run is non-interactive.

Trigger:
  make execute workflow=crm-notion-sync \
    input='{"text":"Hi Seb, loved your talk — can we chat about a role at Ongiini?","subject":"Following up","interaction_type":"Email"}'
"""

from __future__ import annotations

from datetime import date

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as wf_mistral
from mistralai.workflows import workflow
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors

with workflow.unsafe.imports_passed_through():
    from workflows.crm.classify import classify_interaction
    from workflows.crm.agent_tools import get_today, extract_agent_text
    from workflows.crm.notion import make_notion_writer_agent, render_triage_for_agent

# Pure imports (safe in workflow thread).
from workflows.crm.agent_tools import classification_to_triage  # noqa: E402
from workflows.crm.connectors import notion_connector  # noqa: E402
from workflows.crm.models import CRMClassification, InteractionInput  # noqa: E402


@workflows.workflow.define(
    name="crm-notion-sync",
    on_behalf_of=True,  # required: acts with your Notion OAuth credentials
    workflow_display_name="CRM · Sync Interaction to Notion",
    workflow_description=(
        "Classifies an interaction with the Studio CRM agent, then writes it into "
        "the Notion CRM (find-or-create Contact + Organization, create Interaction)."
    ),
)
@uses_connectors(notion_connector)
class CRMNotionSyncWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: InteractionInput) -> str:
        raw = await classify_interaction(
            text=inp.text,
            subject=inp.subject,
            interaction_type=inp.interaction_type,
            channel=inp.channel,
        )
        classification = CRMClassification.model_validate(raw)
        today = date.fromisoformat(await get_today())
        triage = classification_to_triage(classification, inp, today)

        # Durable agent writes the triage into Notion using the connector tools.
        agent = make_notion_writer_agent()
        outputs = await wf_mistral.Runner.run(
            agent=agent,
            inputs=render_triage_for_agent(triage),
        )
        return await extract_agent_text(outputs)
