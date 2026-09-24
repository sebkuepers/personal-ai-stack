"""The cleanup plan decides what happens in Gmail — this is its contract.

The dangerous direction is OVER-archiving: a mail that wants a reply or
involves money must never end up in the noise. So the rule checks reply and
finance BEFORE the type — and that ordering is exactly what is on trial here.
"""

from __future__ import annotations

from datetime import date

from workflows.inbox.cleanup import (
    NEEDS_REPLY,
    KEEP,
    FINANCE,
    NOISE,
    cleanup_plan,
    cleanup_summary,
)
from workflows.inbox import config
from workflows.inbox.models import InboxReview, ReviewItem


def review_item(thread_id: str = "t1", **kwargs: object) -> ReviewItem:
    base = {
        "type": "newsletter",
        "needs_reply": False,
        "urgency": "whenever",
        "subscription_group": "",
        "finance_type": "none",
        "amount": "",
        "due_date": "",
        "context_for_vibe": "",
        "reasoning": "",
    }
    base.update(kwargs)
    return ReviewItem(
        thread_id=thread_id,
        sender="a@example.com",
        subject="Betreff",
        received_on=date(2026, 9, 24),
        review=InboxReview(**base),  # type: ignore[arg-type]
    )


def test_routine_noise_is_archived() -> None:
    plan = cleanup_plan([
        review_item("t1", type="newsletter"),
        review_item("t2", type="notification"),
        review_item("t3", type="transaction"),
    ])
    assert [p.action for p in plan] == [NOISE, NOISE, NOISE]


def test_a_needed_reply_beats_noise() -> None:
    # The most dangerous trap: a notification that wants a reaction must
    # NEVER be archived as noise.
    plan = cleanup_plan([review_item("t1", type="notification", needs_reply=True)])
    assert plan[0].action == NEEDS_REPLY


def test_money_beats_noise() -> None:
    # A confirmation with money in it (a direct debit announced) is not a
    # transaction in the noise sense — it stays visible.
    plan = cleanup_plan([review_item("t1", type="transaction", finance_type="direct_debit")])
    assert plan[0].action == FINANCE


def test_correspondence_is_never_noise() -> None:
    plan = cleanup_plan([review_item("t1", type="correspondence")])
    assert plan[0].action == NEEDS_REPLY


def test_the_uncertain_rest_is_kept() -> None:
    plan = cleanup_plan([review_item("t1", type="other")])
    assert plan[0].action == KEEP


def test_cleanup_summary_counts_honestly() -> None:
    plan = cleanup_plan([
        review_item("t1", type="newsletter"),
        review_item("t2", type="invoice_payment"),
        review_item("t3", type="correspondence"),
        review_item("t4", type="other"),
    ])
    text = cleanup_summary(plan, config.LABELS)
    assert "1 archivieren + gelesen setzen" in text
    assert f"1 behalten (Label {config.LABELS['finance']})" in text
    assert f"1 behalten (Label {config.LABELS['needs_reply']})" in text
    assert "1 unangetastet" in text


def test_empty_plan() -> None:
    assert cleanup_plan([]) == []
    assert cleanup_summary([], config.LABELS) == "nichts zu tun"
