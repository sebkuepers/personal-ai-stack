"""Reusable CRM functions — both as pure helpers and as agent-callable tools.

Two audiences:

1. Workflows call the *pure* helpers (``derive_auto_tags``, ``suggest_priority``,
   ``compute_follow_up_date``, ``classification_to_triage``) directly in
   deterministic workflow code. They take any "today" date as an argument so
   they never read the clock themselves (Temporal determinism).

2. Durable agents call the *activity* versions (``tool_*`` / ``get_today``) by
   passing them in ``Agent(tools=[...])``. The model invokes them like
   functions during a conversation.

Keeping one implementation (the pure function) and a thin activity wrapper means
the agent tools and the workflow logic can never disagree.
"""

from __future__ import annotations

from datetime import date, timedelta

import mistralai.workflows as workflows

from .config import AUTO_TAGS, USER_ALIASES
from .models import (
    CRMClassification,
    IntendedContact,
    IntendedInteraction,
    IntendedOrganization,
    InteractionInput,
    InteractionTriage,
)

# ---------------------------------------------------------------------------
# Pure helpers (deterministic — safe to call from workflow code)
# ---------------------------------------------------------------------------


def derive_auto_tags(category: str, sub_category: str | None, priority: str) -> list[str]:
    """Map a classification onto the Contacts 'Auto-Tags' multi-select vocabulary."""
    tags: list[str] = []
    if sub_category in {"job_application_ongiini", "job_application_foundation"}:
        tags.append(sub_category)
    if category == "business_opportunity":
        tags.append("business_opportunity")
    if category == "personal":
        tags.append("personal")
    if category == "networking":
        tags.append("networking")
    if category == "support":
        tags.append("support")
    if priority == "High":
        tags.append("high_priority")
    # Only keep tags that actually exist in the Notion vocabulary.
    return [t for t in dict.fromkeys(tags) if t in AUTO_TAGS]


def suggest_priority(category: str, sentiment: str) -> str:
    """Deterministic priority rule (High/Medium/Low).

    Mirrors common-sense CRM triage: urgent sentiment or job applications are
    High; opportunities/sales are at least Medium; everything else Low.
    """
    if sentiment == "Urgent":
        return "High"
    if category in {"job_application", "business_opportunity"}:
        return "High"
    if category in {"sales", "collaboration", "follow_up", "networking"}:
        return "Medium"
    return "Low"


def compute_follow_up_date(category: str, sentiment: str, base: date) -> date | None:
    """Suggest a follow-up date relative to ``base`` (no follow-up → None)."""
    if sentiment == "Urgent":
        return base + timedelta(days=1)
    offsets = {
        "job_application": 3,
        "business_opportunity": 4,
        "sales": 5,
        "follow_up": 5,
        "collaboration": 7,
        "networking": 14,
    }
    days = offsets.get(category)
    return base + timedelta(days=days) if days else None


def build_interaction_title(subject: str | None, people: list[str], category: str, when: date) -> str:
    """Compose a readable Interactions title."""
    who = people[0] if people else "Unknown"
    label = subject.strip() if subject else category.replace("_", " ").title()
    return f"{when.isoformat()} · {who} · {label}"[:120]


def classification_to_triage(
    classification: CRMClassification,
    inp: InteractionInput,
    today: date,
) -> InteractionTriage:
    """Pure mapping: classification + input → Notion-shaped intended writes.

    This is the heart of the dry run. It applies the three documented mapping
    decisions:
      - category/sub_category 'unknown' → leave the Notion select empty.
      - priority → Contacts (not Interactions).
      - action_items → folded into the interaction's AI Analysis text.
    """
    notes: list[str] = []

    # Drop the user from people_mentioned — you are not a contact in your own CRM.
    people = [p for p in classification.people_mentioned if p.strip().lower() not in USER_ALIASES]
    if len(people) != len(classification.people_mentioned):
        notes.append("filtered self (USER_ALIASES) out of contacts")

    occurred = inp.occurred_on or today
    category = None if classification.category == "unknown" else classification.category
    if classification.category == "unknown":
        notes.append("category was 'unknown' → Interactions.Category left empty")
    sub_category = None if classification.sub_category in (None, "unknown") else classification.sub_category

    priority = classification.priority or suggest_priority(classification.category, classification.sentiment)

    follow_up = classification.suggested_follow_up_date or compute_follow_up_date(
        classification.category, classification.sentiment, occurred
    )

    analysis = classification.analysis or ""
    if classification.action_items:
        bullet = "\n".join(f"- {a}" for a in classification.action_items)
        analysis = (analysis + "\n\nAction items:\n" + bullet).strip()
        notes.append("action_items folded into Interactions.AI Analysis")

    interaction = IntendedInteraction(
        title=build_interaction_title(
            inp.subject, people, classification.category, occurred
        ),
        subject=inp.subject,
        raw_content=inp.text,
        category=category,
        sub_category=sub_category,
        interaction_type=classification.interaction_type or inp.interaction_type,
        channel=inp.channel,
        sentiment=classification.sentiment,
        ai_summary=classification.summary,
        ai_analysis=analysis or None,
        occurred_on=occurred,
        follow_up_date=follow_up,
        follow_up_needed=follow_up is not None,
        contact_names=people,
        organization_names=classification.organizations_mentioned,
    )

    auto_tags = derive_auto_tags(classification.category, classification.sub_category, priority)
    contacts = [
        IntendedContact(name=name, auto_tags=auto_tags, priority=priority)
        for name in people
    ]
    organizations = [
        IntendedOrganization(name=name) for name in classification.organizations_mentioned
    ]

    return InteractionTriage(
        classification=classification,
        interaction=interaction,
        contacts=contacts,
        organizations=organizations,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Activity wrappers — pass these to Agent(tools=[...]) so agents can call them
# ---------------------------------------------------------------------------


@workflows.activity()
async def get_today() -> str:
    """Return today's date as an ISO string (agents/workflows can't read the clock)."""
    import datetime as _dt

    return _dt.date.today().isoformat()


@workflows.activity(name="extract-agent-text")
async def extract_agent_text(outputs: object) -> str:
    """Extract the assistant text from a durable agent's FinalOutputs.

    Runs as an activity (outside the workflow sandbox) so it can import the
    mistral client models. Mirrors the SDK's own connector examples.
    """
    from mistralai.client import models as mistralai_models

    return "\n".join(
        chunk.text for chunk in outputs if isinstance(chunk, mistralai_models.TextChunk)
    )


def parse_email_array(text: str) -> list[dict]:
    """Best-effort parse of a JSON array of emails returned by the Gmail agent."""
    import json

    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        data = json.loads(text[start : end + 1])
        return data if isinstance(data, list) else []
    except Exception:
        return []


@workflows.activity()
async def tool_suggest_priority(category: str, sentiment: str) -> str:
    """Agent tool: suggest a CRM priority (High/Medium/Low) for a category+sentiment."""
    return suggest_priority(category, sentiment)


@workflows.activity()
async def tool_derive_auto_tags(category: str, sub_category: str, priority: str) -> list[str]:
    """Agent tool: derive Notion Auto-Tags for a contact from its classification."""
    return derive_auto_tags(category, sub_category or None, priority)
