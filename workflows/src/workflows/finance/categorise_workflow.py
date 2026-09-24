"""FINANCE workflow — categorise a batch of bookings.

Category: finance (local worker, no connector, no schedule).

The model work belongs in a workflow, not in a CLI loop: Temporal does the
retries, the Studio timeline shows where the twenty minutes went, and a crashed
run resumes instead of starting over. The first version of this domain called
the agent straight from ``financecli`` and was therefore invisible in Studio —
which is exactly what this repo exists to avoid.

**No file system here.** The CLI reads the ledger, hands the bookings in as
data, and writes the answers back. Reading from disk is allowed in this domain
(``local.py``), writing never is.

Trigger (locally, the worker has to run):
  make finance-categorise apply=1
"""

from __future__ import annotations

import mistralai.workflows as workflows
from mistralai.workflows import execute_activities_in_parallel, workflow

with workflow.unsafe.imports_passed_through():
    import workflows.finance.config as config
    from workflows.finance.categorise import categorise_booking
    from workflows.finance.models import CategoriseInput, CategoriseResult


@workflows.workflow.define(
    name="finance-categorise",
    on_behalf_of=False,  # no connector — the agent is called with the worker's key
    workflow_display_name="Finance · Categorise (Stapel)",
    workflow_description=(
        "Ordnet einen Stapel Buchungen aus den Kontoauszügen den Kategorien der "
        "eigenen Finanzplanung zu. Fragt je Buchung den Studio-Agenten "
        "Finance · Categorise, parallel und mit Wiederholung. Schreibt nichts — "
        "das Ergebnis geht an den Aufrufer zurück."
    ),
)
class FinanceCategoriseWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, params: CategoriseInput) -> CategoriseResult:
        if not params.prompts:
            return CategoriseResult.model_validate({"answers": []})

        # Parallel, but bounded: the limit counts TOKENS per minute, and 649
        # bookings at ten at a time died on HTTP 429 after 23. The figure lives
        # in shared/finance.json next to the measurement that set it.
        # ``items`` are the arguments themselves, not keyword dicts: an activity
        # with ONE parameter receives each item directly. Handing dicts in gave
        # "Item at index 0 is not compatible with activity parameter type str",
        # which reads like a schema problem and is a calling-convention one.
        raw = await execute_activities_in_parallel(
            categorise_booking,
            items=list(params.prompts),
            max_concurrent_scheduled_tasks=config.LIMITS["concurrency"],
        )
        # Built from dumps, never from instances: a Pydantic model that crosses
        # the sandbox boundary twice is two classes with the same name
        # (workflows/CLAUDE.md gotcha 20).
        return CategoriseResult.model_validate({"answers": list(raw)})
