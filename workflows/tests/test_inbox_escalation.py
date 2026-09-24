"""The escalation rule decides about money and replies — this is its contract.

Its failure directions are asymmetric, hence the boundaries:
- Small meldet zu viel → Zweitblick korrigiert (billig, gewollt).
- Small verpasst etwas Kritisches → muss trotzdem eskalieren. Deshalb
  the rule escalates at type level for correspondence/other, even when small
  says "no reply needed" — that is precisely the dangerous gap.
"""

from __future__ import annotations

from workflows.inbox.escalation import needs_second_review
from workflows.inbox.models import InboxReview


def sicht(**kwargs: object) -> InboxReview:
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
    assert needs_second_review(sicht(type="newsletter")) is False
    assert needs_second_review(sicht(type="notification")) is False
    assert needs_second_review(sicht(type="transaction")) is False


def test_a_needed_reply_escalates() -> None:
    assert needs_second_review(sicht(type="notification", needs_reply=True)) is True


def test_money_escalates() -> None:
    assert needs_second_review(sicht(type="invoice_payment", finance_type="invoice")) is True
    assert needs_second_review(sicht(finance_type="direct_debit")) is True


def test_urgency_today_escalates() -> None:
    assert needs_second_review(sicht(urgency="today")) is True


def test_correspondence_escalates_even_without_flags() -> None:
    # Die entscheidende Lücke: Small sagt „keine Antwort nötig" zu einer Mail
    # of a real human — the rule must not trust that and escalates at type
    # level. PERSONAL is rare, so the insurance is cheap.
    assert needs_second_review(sicht(type="correspondence")) is True


def test_other_escalates() -> None:
    # "Other" is the uncertainty bucket — look again.
    assert needs_second_review(sicht(type="other")) is True


def test_this_week_alone_does_not_escalate() -> None:
    # this_week allein (ohne Antwortbedarf/Finanzen) ist keine Kritikalität.
    assert needs_second_review(sicht(type="notification", urgency="this_week")) is False


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
