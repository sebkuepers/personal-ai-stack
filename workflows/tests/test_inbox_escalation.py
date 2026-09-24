"""The escalation rule decides about money and replies — this is its contract.

Its failure directions are asymmetric, hence the boundaries:
- Small reports too much → the second stage corrects it (cheap, wanted).
- Small misses something critical → it has to escalate anyway. So
  the rule escalates at type level for correspondence/other, even when small
  says "no reply needed" — that is precisely the dangerous gap.
"""

from __future__ import annotations

from workflows.inbox.escalation import matters_for_vibe, needs_second_review
from workflows.inbox.models import InboxReview


def review(**kwargs: object) -> InboxReview:
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


def test_routine_does_not_reach_the_second_stage() -> None:
    # The bulk: newsletters and notifications with no reply needed — small suffices.
    assert needs_second_review(review(type="newsletter")) is False
    assert needs_second_review(review(type="notification")) is False
    assert needs_second_review(review(type="transaction")) is False


def test_a_needed_reply_escalates() -> None:
    assert needs_second_review(review(type="notification", needs_reply=True)) is True


def test_money_escalates() -> None:
    assert needs_second_review(review(type="invoice_payment", finance_type="invoice")) is True
    assert needs_second_review(review(finance_type="direct_debit")) is True


def test_urgency_today_escalates() -> None:
    assert needs_second_review(review(urgency="today")) is True


def test_correspondence_escalates_even_without_flags() -> None:
    # Die entscheidende Lücke: Small sagt „keine Antwort nötig" zu einer Mail
    # of a real human — the rule must not trust that and escalates at type
    # level. PERSONAL is rare, so the insurance is cheap.
    assert needs_second_review(review(type="correspondence")) is True


def test_other_escalates() -> None:
    # "Other" is the uncertainty bucket — look again.
    assert needs_second_review(review(type="other")) is True


def test_this_week_alone_does_not_escalate() -> None:
    # this_week allein (ohne Antwortbedarf/Finanzen) ist keine Kritikalität.
    assert needs_second_review(review(type="notification", urgency="this_week")) is False


# ---------------------------------------------------------------------------
# The cascade's kill switch
# ---------------------------------------------------------------------------


def _review(**kwargs: object) -> InboxReview:
    base = {
        "type": "notification", "needs_reply": False, "urgency": "whenever",
        "subscription_group": "", "finance_type": "none", "amount": "",
        "due_date": "", "context_for_vibe": "", "reasoning": "",
    }
    base.update(kwargs)
    return InboxReview(**base)  # type: ignore[arg-type]


def test_reworded_reasoning_is_not_a_change():
    """The kill switch must not count prose.

    The first real run reported 5 of 5 reviews "changed" because the whole
    answer was compared and two models never word `reasoning` identically. A
    number that can never read zero decides nothing.
    """
    first = _review(reasoning="Automatische Benachrichtigung.")
    second = _review(reasoning="Eine automatische Dienst-Mail ohne Frist.")
    assert first.verdict() == second.verdict()


def test_context_for_vibe_is_not_a_change():
    first = _review(context_for_vibe="Kein Handlungsbedarf.")
    second = _review(context_for_vibe="Nichts zu tun hier.")
    assert first.verdict() == second.verdict()


def test_a_different_classification_is_a_change():
    assert _review(needs_reply=True).verdict() != _review(needs_reply=False).verdict()
    assert _review(urgency="today").verdict() != _review(urgency="whenever").verdict()
    assert _review(finance_type="invoice").verdict() != _review(finance_type="none").verdict()
    assert _review(type="correspondence").verdict() != _review(type="notification").verdict()


# ---------------------------------------------------------------------------
# The conversational form: Vibe shows the VALUE, not the label
# ---------------------------------------------------------------------------


def test_form_values_are_readable_on_their_own():
    """Vibe's summary card renders the chosen value, so "on" and "1" read as noise.

    The values therefore carry words, and the parsers below turn them back into
    numbers. If a value ever becomes a bare key again, this fails.
    """
    from workflows.inbox.review import LIMITS, SECOND_REVIEW, WINDOWS

    for options in (WINDOWS, SECOND_REVIEW, LIMITS):
        for value, _label in options:
            assert not value.isdigit(), f"{value!r} shows as a bare number in the summary"
            assert value not in ("on", "off"), f"{value!r} says nothing on its own"


def test_the_parsers_match_the_options():
    """Every offered value has to survive its parser — otherwise the run dies on a choice."""
    from workflows.inbox.review import LIMITS, WINDOWS, _count, _days

    assert [_days(v) for v, _ in WINDOWS] == [1, 3, 7]
    assert [_count(v) for v, _ in LIMITS] == [25, 50, 100]


class TestMattersForVibe:
    """The dossier holds what changes what he does next — not a digest.

    Measured on the first real run (2026-09-24, 50 mails): the dossier carried
    fourteen notes, nine of which said in so many words that nothing had to
    happen — GitHub PR summaries, a weekly digest, a bank inbox notice. The cut
    below leaves the five that name a deadline, money or an owed reply.
    """

    def test_a_notification_without_urgency_stays_out(self) -> None:
        assert not matters_for_vibe(
            review(type="notification", context_for_vibe="PR #1810, keine Handlung nötig")
        )

    def test_a_newsletter_stays_out(self) -> None:
        assert not matters_for_vibe(review(type="newsletter"))

    def test_money_gets_in(self) -> None:
        assert matters_for_vibe(review(type="notification", finance_type="reminder"))

    def test_a_deadline_this_week_gets_in(self) -> None:
        assert matters_for_vibe(review(type="newsletter", urgency="this_week"))

    def test_an_owed_reply_gets_in(self) -> None:
        assert matters_for_vibe(review(type="notification", needs_reply=True))

    def test_correspondence_always_gets_in(self) -> None:
        # Same asymmetry as the escalation rule: a missed conversation is the
        # expensive direction, a superfluous line in the dossier is not.
        assert matters_for_vibe(review(type="correspondence"))
