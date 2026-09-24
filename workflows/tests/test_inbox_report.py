"""Die Verdichtung eines Sichtungs-Laufs ist deterministisch — hier ist ihr Vertrag.

``report.build_report`` counts and sorts; no model, no I/O. The numbers land
in the daily report, and a mistake here distorts every decision based on it.
The boring case is explicitly included: an empty round has to yield an empty
but well-formed report. And the reply state comes from the sent window — open
before answered, which is the point of the digest.
"""

from __future__ import annotations

from datetime import date

import pytest

from workflows.inbox.models import (
    InboxEnvelope,
    InboxReview,
    SentEnvelope,
    UnsubCandidate,
)
from workflows.inbox.report import build_report


def umschlag(subject: str = "Betreff", sender: str = "a@example.com") -> InboxEnvelope:
    return InboxEnvelope(thread_id="t1", sender=sender, subject=subject, unread=True)


def gesendet(to: list[str], subject: str = "Re: Betreff") -> SentEnvelope:
    return SentEnvelope(
        thread_id="t9", sender="seb@example.com", to=to, subject=subject,
        received_on=date(2026, 9, 23),
    )


def sicht(**kwargs: object) -> InboxReview:
    """Eine gültige Sichtung mit übersteuerbaren Feldern."""
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
    return InboxReview(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Der Langweilfall zuerst: nichts gefunden, nichts zu melden
# ---------------------------------------------------------------------------


def test_an_empty_run_yields_an_empty_report() -> None:
    report = build_report(
        window_days=1, envelopes=[], reviews=[], sent=[], unsub_links=[],
        pages=3, skipped_no_messages=4, own_replies=0,
    )
    assert report.inbox_found == 0
    assert report.skipped_no_messages == 4
    assert report.type_counts == {}
    assert report.subscription_groups == {}
    assert report.needs_reply == []
    assert report.finance == []
    assert report.sent == []


def test_envelopes_and_reviews_have_to_be_pairwise() -> None:
    with pytest.raises(ValueError, match="pairwise"):
        build_report(
            window_days=1, envelopes=[umschlag()], reviews=[], sent=[],
            unsub_links=[], pages=1, skipped_no_messages=0, own_replies=0,
        )


# ---------------------------------------------------------------------------
# Reply state — the reason the digest reads the sent folder too
# ---------------------------------------------------------------------------


def test_answered_go_last_open_go_first() -> None:
    report = build_report(
        window_days=1,
        envelopes=[
            umschlag("Offen heute", "a@example.com"),
            umschlag("Schon beantwortet", "b@example.com"),
        ],
        reviews=[
            sicht(type="correspondence", needs_reply=True, urgency="today"),
            sicht(type="correspondence", needs_reply=True, urgency="today"),
        ],
        sent=[gesendet(to=["b@example.com"])],
        unsub_links=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert [(a.sender, a.answered) for a in report.needs_reply] == [
        ("a@example.com", False),
        ("b@example.com", True),
    ]


def test_replies_only_on_the_flag_sorted_by_urgency() -> None:
    report = build_report(
        window_days=1,
        envelopes=[
            umschlag("Später", "z@example.com"),
            umschlag("Heute!", "a@example.com"),
            umschlag("Ohne Antwortbedarf", "b@example.com"),
            umschlag("Diese Woche", "y@example.com"),
        ],
        reviews=[
            sicht(type="correspondence", needs_reply=True, urgency="whenever"),
            sicht(type="correspondence", needs_reply=True, urgency="today"),
            sicht(type="notification", needs_reply=False),
            sicht(type="correspondence", needs_reply=True, urgency="this_week"),
        ],
        sent=[],
        unsub_links=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert [a.urgency for a in report.needs_reply] == [
        "today",
        "this_week",
        "whenever",
    ]
    assert all(a.subject != "Ohne Antwortbedarf" for a in report.needs_reply)


def test_equal_urgency_sorts_by_sender() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag("A", "z@example.com"), umschlag("B", "a@example.com")],
        reviews=[
            sicht(type="correspondence", needs_reply=True, urgency="today"),
            sicht(type="correspondence", needs_reply=True, urgency="today"),
        ],
        sent=[], unsub_links=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert [a.sender for a in report.needs_reply] == ["a@example.com", "z@example.com"]


# ---------------------------------------------------------------------------
# Counting and grouping
# ---------------------------------------------------------------------------


def test_type_counts_and_an_empty_group_does_not_count() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag(), umschlag("Re: Termin", "mensch@example.com"), umschlag()],
        reviews=[
            sicht(type="newsletter", subscription_group="LinkedIn"),
            sicht(type="correspondence"),
            sicht(type="notification", subscription_group=""),
        ],
        sent=[], unsub_links=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert report.type_counts == {"newsletter": 1, "notification": 1, "correspondence": 1}
    assert report.subscription_groups == {"LinkedIn": 1}


def test_groups_sorted_by_noise_then_alphabetically() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag()] * 4,
        reviews=[
            sicht(subscription_group="Zeit"),
            sicht(subscription_group="LinkedIn"),
            sicht(subscription_group="LinkedIn"),
            sicht(subscription_group="Amazon"),
        ],
        sent=[], unsub_links=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert list(report.subscription_groups) == ["LinkedIn", "Amazon", "Zeit"]


def test_finance_only_with_a_kind_and_with_every_field() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag("Mahnung"), umschlag("Newsletter")],
        reviews=[
            sicht(
                type="invoice_payment",
                finance_type="reminder",
                amount="89,00 EUR",
                due_date="2026-09-25",
            ),
            sicht(type="newsletter", finance_type="none"),
        ],
        sent=[], unsub_links=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert len(report.finance) == 1
    f = report.finance[0]
    assert (f.kind, f.amount, f.due_date) == ("reminder", "89,00 EUR", "2026-09-25")


def test_context_collects_only_non_empty_entries() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag(), umschlag(), umschlag("Re: Termin")],
        reviews=[
            sicht(context_for_vibe="Zusage für Freitag, 10 Uhr."),
            sicht(context_for_vibe=""),
            sicht(type="notification", context_for_vibe="Zahnarzttermin morgen 9 Uhr."),
        ],
        sent=[], unsub_links=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert report.context == ["Zusage für Freitag, 10 Uhr.", "Zahnarzttermin morgen 9 Uhr."]


# ---------------------------------------------------------------------------
# Sent section, unsubscribe links and the headline figures
# ---------------------------------------------------------------------------


def test_second_review_flag_and_count() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag("Re: Termin", "mensch@example.com"), umschlag("Rundbrief")],
        reviews=[
            sicht(type="correspondence"),
            sicht(type="newsletter"),
        ],
        sent=[], unsub_links=[],
        pages=1, skipped_no_messages=0, own_replies=0,
        second_review_indices={0},
    )
    assert report.second_review_count == 1
    assert report.reviews[0].second_review is True
    assert report.reviews[1].second_review is False


def test_sent_and_unsub_links_are_passed_through() -> None:
    s = gesendet(to=["marie@example.com"])
    kandidat = UnsubCandidate(
        sender="news@example.com", subject="Rundbrief", thread_id="t1",
        url="https://news.example.com/out",
    )
    report = build_report(
        window_days=1,
        envelopes=[umschlag("Rundbrief", "news@example.com")],
        reviews=[sicht(reasoning="Massenversand mit Abbestell-Link.")],
        sent=[s],
        unsub_links=[kandidat],
        pages=7, skipped_no_messages=26, own_replies=2,
    )
    assert report.sent == [s]
    assert report.unsub_links == [kandidat]
    assert report.pages == 7
    assert report.skipped_no_messages == 26
    assert report.own_replies == 2
    assert len(report.reviews) == 1
    assert report.reviews[0].review.type == "newsletter"
