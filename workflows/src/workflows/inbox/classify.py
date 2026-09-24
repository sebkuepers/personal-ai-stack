"""Sichtungs-Aktivitäten — triggern die Studio-Agents der inbox-Kaskade.

Wie bei der CRM-Klassifizierung wird der Agent hier NICHT neu implementiert:
Instruktionen, Modell und Antwortschema gehören den Studio-Agents (IDs in
``config``), die Aktivitäten triggern sie nur über die Conversations API und
parsen das strukturierte Ergebnis. Zwei Stufen, identischer Umschlag:

* ``review_email``     — Erstblick (small): sichtet ALLE Umschläge.
* ``second_review_email`` — Zweitblick (medium): prüft nur nach, wo die
  Eskalationsregel es verlangt (``escalation.needs_second_review``); sein
  Ergebnis gewinnt.

Warum die Conversations API und nicht ``Agent(id=...)`` + ``Runner``?
  Der durable-agent ``Agent(id=...)``-Weg ist dokumentiert als *update* —
  er überschreibt den remote Agent mit den (oft lückenhaften) Feldern, die
  man übergibt. ``mistralai_start_conversation`` triggert den Agent exakt
  wie konfiguriert und ändert nichts (Workflows-CLAUDE.md, Gotcha 4).

Der Agent sieht den UMSCHLAG (Absender, Betreff, Snippet, Gmail-Kategorie,
ungelesen, Empfangs- und heutiges Datum) — nie den Body: ``search_threads``
liefert Bodies immer null, und Bodies sind teuer (eine Promo-Mail:
132.689 Zeichen HTML).
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
    """Extrahiert den Assistenten-Text aus einer ConversationResponse.

    Spiegel von ``workflows.crm.classify._extract_text``: ``content`` ist
    entweder ein String oder eine Liste von Chunks mit ``.text``.
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
    """Parst das Agent-JSON in eine InboxReview — defensiv bei Prosa drumherum."""
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
    """Der Envelope as agent input — identisch für Erst- und Zweitblick."""
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


async def _sichten(agent_id: str, payload: str) -> dict:
    """Triggert einen der beiden Sichtungs-Agents und parst die Antwort."""
    request = mistralai_models.ConversationRequest(
        agent_id=agent_id,
        inputs=payload,
        store=False,  # Sichtungsgespräche nicht in Studio persistieren
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
    """Erstblick (small): sichtet einen Umschlag; liefert eine InboxReview als dict.

    ``today`` und ``received_on`` gehören in den Umschlag: Ohne sie kann der
    Agent „Frist heute/morgen" nicht von „irgendwann" unterscheiden — eine
    Dringlichkeit, die er nicht berechnen kann, rät er. Ein dict (JSON mode),
    damit der Temporal-Konverter das Ergebnis sauber über die Sandbox-Grenze
    bringt.
    """
    payload = _envelope_payload(sender, subject, snippet, category, unread, received_on, today)
    return await _sichten(config.INBOX_REVIEW_AGENT_ID, payload)


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
    """Zweitblick (medium): prüft einen kritischen Umschlag nach; gewinnt."""
    payload = _envelope_payload(sender, subject, snippet, category, unread, received_on, today)
    return await _sichten(config.INBOX_SECOND_REVIEW_AGENT_ID, payload)
