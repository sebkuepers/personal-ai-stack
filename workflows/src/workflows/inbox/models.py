"""Pydantic models for the inbox domain.

Two layers as in CRM: ``InboxReview`` mirrors the JSON schema of the Studio
agent ``Inbox · Review`` exactly (``extra="forbid"``), and the report is the
deterministic condensation of one triage run.

The envelope models are deliberately body-less: ``search_threads`` returns
bodies ALWAYS as null (verified live, 644 messages over two runs) — the
envelope (sender, subject, snippet, labels) carries the classification, and
bodies are fetched individually through ``get_thread`` only where an
unsubscribe link is needed.

The enum values stay English here because the agent produces them and they are
this system's vocabulary, not German subject matter.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Envelopes — what the Gmail search returns
# --------------------------------------------------------------------------- #


class InboxEnvelope(BaseModel):
    """Envelope of a received mail. The body is always missing — see the module docstring."""

    thread_id: str = ""
    message_id: str = ""
    sender: str = ""
    subject: str = ""
    snippet: str = ""
    labels: list[str] = Field(default_factory=list)
    category: str = ""  # CATEGORY_* without the prefix, e.g. "UPDATES"; "" when uncategorised
    unread: bool = False
    received_on: date | None = None


class SentEnvelope(BaseModel):
    """A sent mail — recipients and subject carry context and reply state."""

    thread_id: str = ""
    message_id: str = ""
    sender: str = ""  # one's own address (it is in the envelope of the sent mail)
    to: list[str] = Field(default_factory=list)
    subject: str = ""
    received_on: date | None = None


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


class InboxScanInput(BaseModel):
    """Input of the triage workflow. The window is in days — Gmail search knows no hours."""

    window_days: int = Field(
        default=1, description="Time window in days, for both passes (inbox and sent)."
    )
    max_threads: int = Field(default=50, description="Triage at most this many inbox threads.")
    max_unsub: int = Field(
        default=15, description="Fetch at most this many bodies for unsubscribe links."
    )
    second_review: bool = Field(
        default=True,
        description=(
            "Second review stage (medium) for critical cases. False = "
            "first stage (small) only — faster and cheaper, unverified."
        ),
    )


class SenderStatsInput(BaseModel):
    """Input of the sender statistic — pure arithmetic, no model."""

    window_days: int = Field(default=90, description="Time window in days.")
    query: str | None = Field(
        default=None,
        description=(
            "Gmail search expression. Default: '-in:sent newer_than:<n>d' — everything "
            "received that reaches you. Careful: spam and trash are EXCLUDED from the "
            "search by default (verified live); 'in:anywhere' includes them."
        ),
    )
    max_threads: int = Field(default=4000, description="Upper bound of the sweep.")


# --------------------------------------------------------------------------- #
# Triage — mirror of the Studio agent schema
# --------------------------------------------------------------------------- #


class InboxReview(BaseModel):
    """Mirrors the answer schema of the Studio agent ``Inbox · Review`` exactly."""

    model_config = ConfigDict(extra="forbid")

    type: str  # newsletter|notification|transaction|invoice_payment|correspondence|other
    needs_reply: bool
    urgency: str  # today|this_week|whenever
    subscription_group: str = ""  # sender cluster, "" if not applicable
    finance_type: str = "none"  # invoice|reminder|direct_debit|confirmation|none
    amount: str = ""
    due_date: str = ""  # YYYY-MM-DD or ""
    context_for_vibe: str = ""
    reasoning: str = ""


# --------------------------------------------------------------------------- #
# Report building blocks
# --------------------------------------------------------------------------- #


class ReplyItem(BaseModel):
    """A mail awaiting a reply — including the reply state."""

    sender: str
    subject: str
    urgency: str
    reasoning: str
    answered: bool  # the recipient is in the sent window — probably already answered


class FinanceItem(BaseModel):
    """A mail with money in it — recognised, not booked."""

    sender: str
    subject: str
    kind: str
    amount: str
    due_date: str


class UnsubCandidate(BaseModel):
    """An unsubscribe link, pulled deterministically out of the HTML — no model."""

    sender: str
    subject: str
    thread_id: str
    url: str  # https link or mailto:


class ReviewItem(BaseModel):
    """One triaged mail with its classification — the full per-mail finding."""

    thread_id: str = ""  # Gmail thread ID — the cleanup plan addresses it through this
    sender: str
    subject: str
    received_on: date | None
    second_review: bool = False  # the second stage re-checked this review
    review: InboxReview


class InboxScanReport(BaseModel):
    """Result of a triage run — pure data, nothing was changed."""

    window_days: int
    inbox_found: int
    skipped_no_messages: int  # threads that came without an envelope — varies per run (26–57)
    own_replies: int  # threads in the inbox where he had the last word
    pages: int
    second_review_count: int = 0  # how many reviews the second stage checked
    second_review_changed: int = 0  # how often it ACTUALLY changed the result (kill switch)
    type_counts: dict[str, int] = Field(default_factory=dict)
    subscription_groups: dict[str, int] = Field(default_factory=dict)
    needs_reply: list[ReplyItem] = Field(default_factory=list)
    finance: list[FinanceItem] = Field(default_factory=list)
    context: list[str] = Field(default_factory=list)
    unsub_links: list[UnsubCandidate] = Field(default_factory=list)
    sent: list[SentEnvelope] = Field(default_factory=list)
    reviews: list[ReviewItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Sender statistic — the falsifiable basis for unsubscribing
# --------------------------------------------------------------------------- #


class SenderItem(BaseModel):
    """One sender with mails and unread in the window — arithmetic, not an opinion."""

    sender: str
    mails: int
    unread: int


class SenderStats(BaseModel):
    """Result of the sender sweep: ranked by noise, not by feeling."""

    window_days: int
    query: str
    threads: int
    skipped_no_messages: int
    senders: list[SenderItem] = Field(default_factory=list)
    unread_total: int = 0


# --------------------------------------------------------------------------- #
# Cleanup — level 2/3 of the safety ladder, only with approval per run
# --------------------------------------------------------------------------- #


class CleanupAction(BaseModel):
    """What should happen to ONE thread, derived from its review."""

    thread_id: str
    action: str  # noise | finance | reply | keep
    sender: str
    subject: str


class CleanupResult(BaseModel):
    """What the run actually did — the receipt, per action."""

    archived: int = 0
    marked_read: int = 0
    labelled_finance: int = 0
    labelled_reply: int = 0
    mailto_drafts: int = 0
    errors: list[str] = Field(default_factory=list)
    skipped: int = 0
