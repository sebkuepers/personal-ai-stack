"""Der Aufräum-Plan entscheidet, was in Gmail passiert — hier ist sein Vertrag.

Die gefährliche Richtung ist das OVER-archivieren: Eine Mail, die Antwort oder
Geld verlangt, darf nie im Lärm landen. Deshalb prüft die Regel Antwort und
Finanzen VOR dem Typ — und genau diese Rangfolge steht hier auf Probe.
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
from workflows.inbox.models import InboxReview, ReviewItem


def sichtung(thread_id: str = "t1", **kwargs: object) -> ReviewItem:
    basis = {
        "type": "newsletter",
        "needs_reply": False,
        "urgency": "whenever",
        "subscription_group": "",
        "finance_type": "none",
        "betrag": "",
        "due_date": "",
        "context_for_vibe": "",
        "reasoning": "",
    }
    basis.update(kwargs)
    return ReviewItem(
        thread_id=thread_id,
        sender="a@example.com",
        subject="Betreff",
        received_on=date(2026, 9, 24),
        review=InboxReview(**basis),  # type: ignore[arg-type]
    )


def test_routine_lärm_wird_archiviert() -> None:
    plan = cleanup_plan([
        sichtung("t1", type="newsletter"),
        sichtung("t2", type="notification"),
        sichtung("t3", type="transaction"),
    ])
    assert [p.aktion for p in plan] == [NOISE, NOISE, NOISE]


def test_antwortbedarf_geht_vor_lärm() -> None:
    # Die gefährlichste Falle: Eine Notification, die eine Reaktion verlangt,
    # darf NIEMALS als Lärm archiviert werden.
    plan = cleanup_plan([sichtung("t1", type="notification", needs_reply=True)])
    assert plan[0].aktion == NEEDS_REPLY


def test_finanzen_gehen_vor_lärm() -> None:
    # Eine Bestätigung mit Geldfluss (Lastschrift angekündigt) ist keine
    # Transaktion im Lärm-Sinn — sie bleibt sichtbar.
    plan = cleanup_plan([sichtung("t1", type="transaction", finance_type="direct_debit")])
    assert plan[0].aktion == FINANCE


def test_korrespondenz_ist_nie_lärm() -> None:
    plan = cleanup_plan([sichtung("t1", type="correspondence")])
    assert plan[0].aktion == NEEDS_REPLY


def test_unsicherer_rest_bleibt() -> None:
    plan = cleanup_plan([sichtung("t1", type="other")])
    assert plan[0].aktion == KEEP


def test_cleanup_summary_zaehlt_ehrlich() -> None:
    plan = cleanup_plan([
        sichtung("t1", type="newsletter"),
        sichtung("t2", type="invoice_payment"),
        sichtung("t3", type="correspondence"),
        sichtung("t4", type="other"),
    ])
    text = cleanup_summary(plan)
    assert "1 archivieren + gelesen setzen" in text
    assert "1 behalten (label inbox/finance)" in text
    assert "1 behalten (label inbox/needs-reply)" in text
    assert "1 unangetastet" in text


def test_leerer_plan() -> None:
    assert cleanup_plan([]) == []
    assert cleanup_summary([]) == "nichts zu tun"
