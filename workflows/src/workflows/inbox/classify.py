"""Triage activities — trigger the Studio agents of the inbox cascade.

As with the CRM classification, the agent is NOT reimplemented here:
instructions, model and answer schema belong to the Studio agents (IDs in
``config``); the activities only trigger them through the conversations API and
parse the structured result. Two stages, identical envelope:

* ``review_email``        — first stage (small): triages EVERY envelope.
* ``second_review_email`` — second stage (medium): re-checks only where the
  escalation rule demands it (``escalation.needs_second_review``); its result
  wins.

Why the conversations API and not ``Agent(id=...)`` + ``Runner``?
  The durable-agent ``Agent(id=...)`` route is documented as an *update* — it
  overwrites the remote agent with the (often sparse) fields one passes.
  ``mistralai_start_conversation`` triggers the agent exactly as configured and
  changes nothing (workflows/CLAUDE.md, gotcha 4).

The agent sees the ENVELOPE (sender, subject, snippet, Gmail category, unread,
received date and today's date) — never the body: ``search_threads`` always
returns bodies as null, and bodies are expensive (one promotional mail: 132,689
characters of HTML).
"""

from __future__ import annotations

import json
from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.client import models as mistralai_models
from mistralai.workflows.plugins.mistralai.activities import mistralai_start_conversation

from . import config
from .models import InboxReview


def _extract_text(response: mistralai_models.ConversationResponse) -> str:
    """Extract the assistant text from a ConversationResponse.

    Mirror of ``workflows.crm.classify._extract_text``: ``content`` is either a
    string or a list of chunks with ``.text``.
    """
    parts: list[str] = []
    for output in response.outputs:
        content = getattr(output, "content", None)
        if content is None:
            continue
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for chunk in content:
                text = getattr(chunk, "text", None)
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _parse_review(text: str) -> InboxReview:
    """Parse the agent JSON into an InboxReview — defensive about prose around it."""
    try:
        return InboxReview.model_validate_json(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return InboxReview.model_validate(json.loads(text[start : end + 1]))
        raise


def _envelope_payload(
    sender: str,
    subject: str,
    snippet: str,
    category: str,
    unread: bool,
    received_on: str | None,
    today: str,
) -> str:
    """The envelope as agent input — identical for both stages."""
    return (
        f"From: {sender}\n"
        f"Subject: {subject}\n"
        f"Snippet: {snippet}\n"
        f"Gmail category: {category or '(none)'}\n"
        f"Unread: {'yes' if unread else 'no'}\n"
        f"Received: {received_on or '(unknown)'}\n"
        f"Today: {today}\n"
        "\n--- This is the full envelope. No body is available. ---\n"
    )


async def _triage(agent_id: str, payload: str) -> dict:
    """Trigger one of the two triage agents and parse the answer."""
    request = mistralai_models.ConversationRequest(
        agent_id=agent_id,
        inputs=payload,
        store=False,  # triage conversations need not persist in Studio
    )
    response = await mistralai_start_conversation(request)
    review = _parse_review(_extract_text(response))
    return review.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=90),
)
async def review_email(
    sender: str,
    subject: str,
    snippet: str,
    category: str,
    unread: bool,
    received_on: str | None,
    today: str,
) -> dict:
    """First stage (small): triages one envelope; returns an InboxReview as a dict.

    ``today`` and ``received_on`` belong in the envelope: without them the agent
    cannot tell "due today/tomorrow" from "whenever" — an urgency it cannot
    compute, it guesses. A dict (JSON mode) so that Temporal's converter carries
    the result cleanly across the sandbox boundary.
    """
    payload = _envelope_payload(sender, subject, snippet, category, unread, received_on, today)
    return await _triage(config.INBOX_REVIEW_AGENT_ID, payload)


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=90),
)
async def second_review_email(
    sender: str,
    subject: str,
    snippet: str,
    category: str,
    unread: bool,
    received_on: str | None,
    today: str,
) -> dict:
    """Second stage (medium): re-checks one critical envelope; it wins."""
    payload = _envelope_payload(sender, subject, snippet, category, unread, received_on, today)
    return await _triage(config.INBOX_SECOND_REVIEW_AGENT_ID, payload)
