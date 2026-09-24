"""FINANCE workflow — the conversation about the numbers.

Category: finance (local worker, reads the ledger, changes nothing).

This is where the four questions get answered: *Gebe ich zu viel für
Mittagessen aus? Soll ich Abos kündigen? Wie viel fürs Boot, wie viel fürs
KI-Setup?* Every figure comes from ``report.build``, the same function the
workbook and the library summaries use, so the three can never disagree.

**It changes nothing.** No file is written, no library document replaced, no
category overruled. The conversation reads.

Two shapes taken from the inbox domain, both learned the hard way:

* **No input schema.** ``run(self)`` without parameters, so Le Chat starts
  immediately instead of asking for a typed message first (gotcha 11).
* **The TodoList wraps the whole session**, not a single step — Vibe renders it
  only while the context manager is open (gotcha 12).

And one from `overview.py`: there is no table component and no clickable row
(gotcha 13). A table to read plus one form to choose from is the usable shape.

Trigger:
  make finance-review
"""

from __future__ import annotations

from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    import mistralai.workflows.conversational as wf_chat
    import mistralai.workflows.plugins.mistralai as wf_mistral
    import workflows.finance.config as config
    from workflows.finance.local import read_ledger, read_planning, read_positions
    from workflows.finance.models import LedgerEntry, PlanningContext, Position
    from workflows.finance.render import euro, month_summary, subscription_summary
    from workflows.finance.report import build, subscriptions

from mistralai.workflows.plugins.mistralai.conversational_ui_components import (  # noqa: E402
    Alert,
    Badge,
    Card,
    Chart,
    Markdown,
    PieChart,
    Row,
)

VIEWS = [
    ("Wofür geht es hin?", "Wofür geht es hin? — alle Kategorien gegen den Plan"),
    ("Abos", "Abos — was monatlich abgebucht wird"),
    ("Das Boot", "Das Boot — was Telsche kostet"),
    ("Das KI-Setup", "Das KI-Setup — was die Modelle kosten"),
    ("Die größten Posten", "Die größten Posten — wohin die vierstelligen Beträge gehen"),
    ("Fertig", "Fertig"),
]


def _view_form() -> type[wf_chat.FormInput]:
    """One view at a time — not a menu of everything at once."""

    class NextView(wf_chat.FormInput):
        # Vibe shows the chosen VALUE in its summary card, not the label, so the
        # values have to read on their own.
        choice: str = wf_chat.SingleChoice(
            options=VIEWS, description="Was willst du sehen?", prefilled_value="Wofür geht es hin?"
        )

    return NextView


def _markdown(text: str):
    return [wf_mistral.ResourceOutput(
        resource=wf_mistral.UIComponentResource(component=Markdown(content=text))
    )]


def _headline(report, plan: PlanningContext | None) -> list:
    cards = [
        Card(title=euro(report.income_cents), description="Einnahmen"),
        Card(title=euro(report.spent_cents), description="Ausgaben"),
        Card(title=euro(report.balance_cents), description="Saldo"),
        Card(title=euro(report.monthly_balance_cents), description="Saldo je Monat"),
    ]
    if plan:
        cards.append(Card(title=euro(plan.monthly_total_cents), description="Plan je Monat"))
    return [Row(gap="md", wrap=True, children=cards)]


def _category_charts(report) -> list:
    """Where the money goes — the picture before the table."""
    spending = [t for t in report.categories if t.spent_cents < 0]
    return [
        Chart(
            variant="bar",
            title="Ausgaben je Kategorie",
            data=[
                {"Kategorie": t.label, "Euro": round(abs(t.spent_cents) / 100)}
                for t in spending[:12]
            ],
            xAxis="Kategorie",
            yAxis="Euro",
        ),
        PieChart(
            title="Anteil am Ausgegebenen",
            data=[
                {"name": t.label, "value": round(abs(t.spent_cents) / 100)}
                for t in spending[:10]
            ],
        ),
    ]


def _plan_table(report) -> str:
    lines = ["| Kategorie | pro Monat | Plan | |", "|---|---:|---:|---|"]
    for total in report.categories:
        if total.spent_cents >= 0:
            continue
        actual = report.per_month(total.spent_cents)
        if not total.plan_cents:
            lines.append(f"| {total.label} | {euro(actual)} | — | kein Plan |")
            continue
        diff = abs(actual) - total.plan_cents
        mark = "über" if diff > 0 else "unter"
        lines.append(
            f"| {total.label} | {euro(actual)} | {euro(total.plan_cents)} | "
            f"{euro(abs(diff))} {mark} |"
        )
    return "\n".join(lines)


def _category_detail(entries: list[LedgerEntry], category: str, title: str) -> str:
    rows = sorted(
        [e for e in entries if e.category == category and e.amount_cents < 0],
        key=lambda e: e.amount_cents,
    )
    if not rows:
        return f"### {title}\n\n_(nichts gefunden)_"
    total = sum(e.amount_cents for e in rows)
    lines = [f"### {title}", "", f"**{euro(total)}** in {len(rows)} Buchungen.", ""]
    for entry in rows[:20]:
        lines.append(
            f"- {euro(entry.amount_cents)} · {entry.booked_on:%d.%m.%Y} · "
            f"{entry.merchant or entry.text[:40]}"
        )
    if len(rows) > 20:
        lines.append(f"- … und {len(rows) - 20} weitere")
    return "\n".join(lines)


@workflows.workflow.define(
    name="finance-review",
    on_behalf_of=False,
    workflow_display_name="Finance · Review (Gespräch)",
    workflow_description=(
        "Das Gespräch über die eigenen Zahlen: Bilanz, Ausgaben je Kategorie "
        "gegen den Plan aus der Planungsmappe, Abos, Boot, KI-Setup und die "
        "größten Posten — mit Diagrammen. Liest nur; verändert nichts."
    ),
)
class FinanceReviewWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> wf_mistral.ChatAssistantWorkflowOutput:
        # description is REQUIRED on TodoListItem — without it the workflow dies
        # at construction, before the first form, and all the chat shows is
        # "Workflow failed".
        # The ITEMS are the context managers, not the list — `async with
        # TodoList(...) as step` raised "'TodoList' object is not subscriptable".
        step = {
            "read": wf_chat.TodoListItem(
                title="Zahlen lesen", description="Ledger, Planung, Depot"
            ),
            "overview": wf_chat.TodoListItem(
                title="Überblick", description="Bilanz und Verteilung"
            ),
            "ask": wf_chat.TodoListItem(
                title="Nachfragen", description="Eine Ansicht nach der anderen"
            ),
        }
        # Gotcha 12: the list wraps the WHOLE session, waiting times included —
        # Vibe renders it only while the context manager is open.
        async with wf_chat.TodoList(items=list(step.values())):
            async with step["read"]:
                raw_entries = await read_ledger()
                raw_plan = await read_planning()
                raw_positions = await read_positions()

            entries = [LedgerEntry.model_validate(e) for e in raw_entries]
            plan = PlanningContext.model_validate(raw_plan) if raw_plan else None
            positions = [Position.model_validate(p) for p in raw_positions]
            if not entries:
                return wf_mistral.ChatAssistantWorkflowOutput(
                    content=[wf_mistral.TextOutput(
                        text="Das Ledger ist leer — erst `make finance-ingest apply=1`."
                    )],
                    isError=True,
                )
            report = build(entries, plan)

            async with step["overview"]:
                missing = sum(1 for e in entries if not e.category)
                parts = _headline(report, plan) + _category_charts(report)
                if missing:
                    parts.append(Alert(
                        variant="warning",
                        title=f"{missing} Buchungen ohne Kategorie",
                        description="make finance-categorise apply=1",
                    ))
                if report.balance_cents < 0:
                    parts.append(Row(gap="sm", wrap=True, children=[
                        # Badge variants are: default, primary, success, warning, error.
                        Badge(children="Saldo negativ", variant="error"),
                        Badge(
                            children=f"{euro(report.monthly_balance_cents)} je Monat",
                            variant="default",
                        ),
                    ]))
                await wf_mistral.send_assistant_message([
                    wf_mistral.ResourceOutput(
                        resource=wf_mistral.UIComponentResource(component=part)
                    )
                    for part in parts
                ])

            async with step["ask"]:
                while True:
                    answer = await self.wait_for_input(
                        _view_form(), label="Ansicht", timeout=timedelta(hours=8)
                    )
                    choice = getattr(answer, "choice", "Fertig")
                    if choice.startswith("Fertig"):
                        break
                    await wf_mistral.send_assistant_message(
                        _markdown(self._view(choice, report, entries, plan, positions))
                    )

        return wf_mistral.ChatAssistantWorkflowOutput(
            content=[
                wf_mistral.TextOutput(text=(
                    f"{euro(report.income_cents)} ein, {euro(report.spent_cents)} aus — "
                    f"Saldo {euro(report.balance_cents)} "
                    f"({euro(report.monthly_balance_cents)} je Monat)."
                )),
                wf_mistral.ResourceOutput(
                    resource=wf_mistral.CanvasResource(
                        uri=f"file://finance/review-{report.end:%Y-%m-%d}",
                        readonly=True,
                        canvas=wf_mistral.CanvasPayload(
                            type="text/markdown",
                            title="Finanzen · Überblick",
                            content=month_summary(report, "Gesamt"),
                        ),
                    )
                ),
            ],
            structuredContent={
                "income_cents": report.income_cents,
                "spent_cents": report.spent_cents,
                "balance_cents": report.balance_cents,
                "months": round(report.months, 2),
            },
        )

    def _view(self, choice, report, entries, plan, positions) -> str:
        """One view as Markdown. Everything comes out of the same report."""
        if choice.startswith("Wofür"):
            return "### Wofür es hingeht\n\n" + _plan_table(report)
        if choice.startswith("Abos"):
            return subscription_summary(report, plan)
        if choice.startswith("Das Boot"):
            return _category_detail(entries, "boat", "Das Boot")
        if choice.startswith("Das KI"):
            return _category_detail(entries, "ai_stack", "Das KI-Setup")
        if choice.startswith("Die größten"):
            rows = sorted(
                [e for e in entries if e.amount_cents < 0 and e.category not in {"transfer"}],
                key=lambda e: e.amount_cents,
            )[:20]
            lines = ["### Die größten Posten", ""]
            lines += [
                f"- {euro(e.amount_cents)} · {e.booked_on:%d.%m.%Y} · "
                f"{config.label(e.category)} · {e.merchant or e.text[:38]}"
                for e in rows
            ]
            return "\n".join(lines)
        if positions:
            total = sum(p.value_cents for p in positions)
            return f"### Depot\n\n**{euro(total)}** in {len(positions)} Positionen."
        return "_(nichts zu zeigen)_"


# Keep the name importable for the subscription view without a second lookup.
_ = subscriptions
