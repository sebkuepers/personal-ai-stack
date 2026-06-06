"""CORE workflow — classify one interaction and map it to Notion-shaped writes.

Category: core (no connectors → runs immediately, no OAuth).

Pipeline:
  1. Trigger the Studio "CRM - Classification Agent" on the raw text.
  2. Map the classification → Notion-shaped "intended writes" (pure, deterministic).
  3. Return the full triage as a DRY RUN — it shows exactly what crm-notion-sync
     would write, without touching Notion.

This is the spine of the whole CRM setup and the safest thing to run first.

Trigger:
  make execute workflow=crm-interaction-classifier \
    input='{"text":"Hi Seb, loved your talk — can we chat about a role at Ongiini?","subject":"Following up","interaction_type":"Email"}'
"""

from __future__ import annotations

from datetime import date

import mistralai.workflows as workflows
from mistralai.workflows import workflow

# Activities touch the network / mistral client → import them through the
# Temporal sandbox boundary (the decorator dispatches the real call to a worker).
with workflow.unsafe.imports_passed_through():
    from workflows.crm.classify import classify_interaction
    from workflows.crm.agent_tools import get_today

# Pure code (models + the deterministic mapping) is safe to import normally and
# to run inside the workflow thread.
from workflows.crm.agent_tools import classification_to_triage  # noqa: E402
from workflows.crm.models import (  # noqa: E402
    CRMClassification,
    InteractionInput,
    InteractionTriage,
)


@workflows.workflow.define(
    name="crm-interaction-classifier",
    workflow_display_name="CRM · Classify Interaction (dry run)",
    workflow_description=(
        "Triggers the Studio CRM Classification agent on one interaction and maps "
        "the result to Notion-shaped intended writes. Dry run — writes nothing."
    ),
)
class CRMInteractionClassifierWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: InteractionInput) -> InteractionTriage:
        # Step 1 — trigger your existing Studio agent (returns a dict).
        raw = await classify_interaction(
            text=inp.text,
            subject=inp.subject,
            interaction_type=inp.interaction_type,
            channel=inp.channel,
        )
        classification = CRMClassification.model_validate(raw)

        # Step 2 — get "today" via an activity (non-deterministic clock read),
        # then run the pure mapping in deterministic workflow code.
        today = date.fromisoformat(await get_today())
        return classification_to_triage(classification, inp, today)
