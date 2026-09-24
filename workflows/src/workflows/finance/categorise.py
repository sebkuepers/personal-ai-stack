"""Asking the Studio agent to categorise a booking.

Pattern from ``crm/classify.py``: trigger the existing agent with
``mistralai_start_conversation`` and ``store=False``. The agent is the source of
truth for the prompt; nothing here re-implements it.

``store=False`` matters more here than anywhere else in this repo. It is the
difference between a booking text passing through a model and a booking text
being kept by one.
"""

from __future__ import annotations

import json
from datetime import timedelta

import mistralai.workflows as workflows

from workflows.finance import config as c
from workflows.finance.models import FinanceCategory, LedgerEntry


def prompt_for(entry: LedgerEntry) -> str:
    """One booking as the agent sees it.

    The bank text goes in unabridged — shortening it here is invisible and
    costs accuracy on exactly the long Girokonto lines where the purpose is at
    the end.
    """
    parts = [
        f"Buchungstext: {entry.text}",
        f"Betrag: {entry.amount_cents / 100:.2f} {entry.currency}",
        f"Datum: {entry.booked_on:%d.%m.%Y}",
        f"Konto: {entry.account}",
    ]
    if entry.counterparty:
        parts.append(f"Gegenüber laut Bank: {entry.counterparty}")
    if entry.bank_category:
        parts.append(f"Kategorie laut Bank: {entry.bank_category}")
    return "\n".join(parts)


def _text_of(outputs: object) -> str:
    """The agent's answer as text, whatever shape the SDK returns it in."""
    from mistralai.client import models as m

    chunks = []
    for entry in getattr(outputs, "outputs", outputs) or []:
        content = getattr(entry, "content", None)
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            chunks.extend(c.text for c in content if isinstance(c, m.TextChunk))
    return "\n".join(chunks).strip()


def parse(answer: str) -> FinanceCategory:
    """Validate the agent's answer, tolerating a fenced code block.

    The defensive parser from ``crm/classify.py``: a strict schema makes this
    rare, not impossible, and a crash here would cost the whole batch.
    """
    text = answer.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Keine JSON-Antwort vom Agenten: {answer[:200]}")
    return FinanceCategory.model_validate(json.loads(text[start : end + 1]))


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=90),
)
async def categorise_booking(prompt: str) -> dict:
    """Trigger ``Finance · Categorise`` for one booking."""
    from mistralai.client import models as m
    from mistralai.workflows.plugins.mistralai.activities import (
        mistralai_start_conversation,
    )

    agent_id = c.AGENTS["finance_categorise_agent_id"]
    if not agent_id:
        raise RuntimeError(
            "shared/finance.json: agent.finance_categorise_agent_id fehlt — "
            "agents/build_finance_agents.py laufen lassen und make sync-agents."
        )  # author-facing: stays German
    response = await mistralai_start_conversation(
        m.ConversationRequest(agent_id=agent_id, inputs=prompt, store=False)
    )
    return parse(_text_of(response)).model_dump()
