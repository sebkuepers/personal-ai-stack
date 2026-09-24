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
from pathlib import Path

from workflows.inbox import apply, config, render
from workflows.inbox.models import CleanupResult, InboxReview, InboxScanReport, ReviewItem


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


# ---------------------------------------------------------------------------
# The receipt — what an unattended run changed
# ---------------------------------------------------------------------------


class TestReceipt:
    """The nightly round changes the mailbox while nobody watches.

    The morning after brings two questions — what came in, and what did it
    touch. An unattended job that answers only the first is one you stop
    trusting, so the receipt goes into the dossier next to the report.
    """

    def test_an_error_is_named_and_nothing_else_is_claimed(self) -> None:
        text = render.receipt(
            CleanupResult(skipped=12, errors=["Gmail: Invalid label name"])
        )
        assert text == "Aufräumen fehlgeschlagen: Gmail: Invalid label name"

    def test_a_quiet_run_says_so_instead_of_staying_empty(self) -> None:
        assert render.receipt(CleanupResult()) == "nichts verändert"

    def test_every_action_appears_with_its_configured_label(self) -> None:
        text = render.receipt(
            CleanupResult(archived=7, labelled_finance=2, labelled_reply=1, mailto_drafts=1)
        )
        assert "7 archiviert" in text
        assert config.LABELS["finance"] in text
        assert config.LABELS["needs_reply"] in text
        assert "Abmeldungs-Entwurf" in text

    def test_the_dossier_carries_it_only_when_a_run_cleaned_up(self) -> None:
        report = InboxScanReport(
            window_days=1, inbox_found=0, skipped_no_messages=0,
            own_replies=0, pages=1,
        )
        assert "Was der Lauf verändert hat" not in render.dossier(report, "2026-09-23")
        with_receipt = render.dossier(report, "2026-09-23", cleaned=CleanupResult(archived=3))
        assert "Was der Lauf verändert hat" in with_receipt
        assert "3 archiviert" in with_receipt


class TestApplyModes:
    """``full`` archives, ``label_only`` must not — the whole point of the switch."""

    def test_label_only_never_archives(self) -> None:
        assert apply.LABEL_ONLY != apply.FULL
        # The archive flag is derived from the mode and from nothing else.
        assert "archive = mode == FULL" in (
            Path(apply.__file__).read_text(encoding="utf-8")
        )

    def test_the_configured_mode_is_one_the_code_knows(self) -> None:
        assert config.SCHEDULE_CLEANUP in {apply.FULL, apply.LABEL_ONLY, apply.NOTHING}
