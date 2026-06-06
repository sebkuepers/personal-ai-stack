"""Pydantic models for the personal-CRM workflows.

Two layers:

1. ``CRMClassification`` — an exact mirror of the Studio CRM Classification
   agent's JSON schema (draft-07, ``additionalProperties: false``).  This is
   what the classifier activity returns.

2. The "intended writes" models (``IntendedInteraction`` / ``IntendedContact`` /
   ``IntendedOrganization`` / ``InteractionTriage``) — a Notion-shaped view of
   what *would* be written.  Stage 1 returns these as a dry run; Stage 2 feeds
   them to the Notion writer.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Layer 1 — mirror of the Studio agent's output schema
# ---------------------------------------------------------------------------


class CRMClassification(BaseModel):
    """Mirrors the CRM Classification Agent's structured output exactly.

    Field names, optionality, and the ``extra="forbid"`` (additionalProperties:
    false) all match the draft-07 schema so the same prompt produces the same
    shape whether called via the Studio agent or via ``chat_parse``.
    """

    model_config = ConfigDict(extra="forbid")

    # Required
    interaction_type: str = Field(description="Email|Meeting|Call|Message|Application|Interview|Other")
    category: str = Field(description="Primary category of the interaction")
    organizations_mentioned: list[str] = Field(default_factory=list)
    people_mentioned: list[str] = Field(default_factory=list)
    sentiment: str = Field(description="Positive|Neutral|Negative|Urgent")
    priority: str = Field(description="High|Medium|Low")

    # Optional
    summary: str | None = None
    analysis: str | None = None
    action_items: list[str] = Field(default_factory=list)
    sub_category: str | None = None
    suggested_follow_up_date: date | None = None


# ---------------------------------------------------------------------------
# Layer 2 — Notion-shaped "intended writes"
# ---------------------------------------------------------------------------


class IntendedContact(BaseModel):
    """A contact we would find-or-create in the Contacts database."""

    name: str
    email: str | None = None
    auto_tags: list[str] = Field(default_factory=list)
    priority: str | None = None  # High|Medium|Low — lives on Contacts, not Interactions


class IntendedOrganization(BaseModel):
    """An organization we would find-or-create in the Organizations database."""

    name: str
    status: str = "Potential"  # Active|Past|Potential|Rejected


class IntendedInteraction(BaseModel):
    """The Interactions row we would create, with relations resolved by name.

    The Notion writer is responsible for turning ``contact_names`` /
    ``organization_names`` into page-id relations (find-or-create).
    """

    title: str
    subject: str | None = None
    raw_content: str | None = None
    category: str | None = None       # None when classifier said "unknown"
    sub_category: str | None = None
    interaction_type: str | None = None
    channel: str | None = None
    sentiment: str | None = None
    ai_summary: str | None = None
    ai_analysis: str | None = None    # action_items folded in here (no Notion field for them)
    occurred_on: date | None = None   # maps to Notion Interactions "Date" (named to avoid shadowing the `date` type)
    follow_up_date: date | None = None
    follow_up_needed: bool = False
    contact_names: list[str] = Field(default_factory=list)
    organization_names: list[str] = Field(default_factory=list)


class InteractionTriage(BaseModel):
    """Full dry-run result: the classification plus the mapped intended writes.

    This is the Stage-1 output — it shows exactly what Stage 2 will write to
    Notion without touching Notion at all.
    """

    classification: CRMClassification
    interaction: IntendedInteraction
    contacts: list[IntendedContact] = Field(default_factory=list)
    organizations: list[IntendedOrganization] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)  # mapping decisions / warnings


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------


class InteractionInput(BaseModel):
    """Input for classifying a single raw interaction (email, note, message)."""

    text: str = Field(description="The full text content of the interaction")
    subject: str | None = Field(default=None, description="Email/meeting subject, if any")
    interaction_type: str = Field(default="Email", description="Hint for the classifier")
    channel: str = Field(default="Email", description="Communication channel")
    occurred_on: date | None = Field(default=None, description="When it happened (defaults to today)")


class EmailItem(BaseModel):
    """A single email pulled from Gmail (shape we normalise the connector into)."""

    message_id: str = ""           # Gmail message id — used for dedup
    direction: str = "received"    # received | sent
    sender: str = ""
    subject: str = ""
    snippet: str = ""
    body: str = ""
    received_on: date | None = None


class EmailTriageInput(BaseModel):
    """Input for the inbox-triage workflow."""

    query: str = Field(
        default="newer_than:7d -category:promotions -category:social",
        description="Gmail search query for the emails to triage",
    )
    max_emails: int = Field(default=10, description="Max emails to pull and classify")


class EmailTriageReport(BaseModel):
    """Dry-run inbox triage: classifications + intended writes, nothing written."""

    query: str
    emails_found: int
    triages: list[InteractionTriage] = Field(default_factory=list)


class FollowUpDigestInput(BaseModel):
    """Input for the follow-up digest workflow."""

    draft_reminders: bool = Field(
        default=True, description="If true, draft reminder emails in Gmail (never sends)."
    )
    horizon_days: int = Field(
        default=0, description="Include follow-ups due within this many days from today (0 = overdue/today)."
    )


class IngestRecentInput(BaseModel):
    """Input for the twice-daily batch ingest workflow."""

    window_hours: int = Field(
        default=13, description="Look back this many hours (13 overlaps a 12h schedule gap)."
    )
    max_emails: int = Field(default=50, description="Max emails to process per run.")
    dry_run: bool = Field(
        default=True, description="If true, classify only and write nothing to Notion."
    )


class IngestItem(BaseModel):
    """One processed email in the ingest report."""

    message_id: str = ""
    direction: str = "received"
    subject: str = ""
    category: str | None = None
    contact_names: list[str] = Field(default_factory=list)
    organization_names: list[str] = Field(default_factory=list)
    action: str = "classified"  # classified (dry run) | written | skipped | error
    detail: str | None = None


class IngestRecentReport(BaseModel):
    """Result of a batch ingest run."""

    window_hours: int
    dry_run: bool
    found: int
    processed: int
    items: list[IngestItem] = Field(default_factory=list)
