"""Die Eskalationsregel entscheidet über Geld und Antworten — hier ihr Vertrag.

Die Fehlrichtungen sind asymmetrisch, deshalb die Grenzen:
- Small meldet zu viel → Zweitblick korrigiert (billig, gewollt).
- Small verpasst etwas Kritisches → muss trotzdem eskalieren. Deshalb
  eskaliert die Regel auf Typ-Ebene bei correspondence/other, selbst wenn
  small „keine Antwort nötig" sagt — genau das ist die gefährliche Lücke.
"""

from __future__ import annotations

from workflows.inbox.escalation import needs_second_review
from workflows.inbox.models import InboxReview


def sicht(**kwargs: object) -> InboxReview:
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
    return InboxReview(**basis)  # type: ignore[arg-type]


def test_routine_laeuft_nicht_zur_zweiten_stufe() -> None:
    # Die Masse: Newsletter und Notifications ohne Antwortbedarf — small genügt.
    assert needs_second_review(sicht(type="newsletter")) is False
    assert needs_second_review(sicht(type="notification")) is False
    assert needs_second_review(sicht(type="transaction")) is False


def test_antwortbedarf_eskaliert() -> None:
    assert needs_second_review(sicht(type="notification", needs_reply=True)) is True


def test_finanzen_eskaliert() -> None:
    assert needs_second_review(sicht(type="invoice_payment", finance_type="invoice")) is True
    assert needs_second_review(sicht(finance_type="direct_debit")) is True


def test_urgency_heute_eskaliert() -> None:
    assert needs_second_review(sicht(urgency="today")) is True


def test_korrespondenz_eskaliert_auch_ohne_flags() -> None:
    # Die entscheidende Lücke: Small sagt „keine Antwort nötig" zu einer Mail
    # eines echten Menschen — die Regel darf dem nicht trauen und eskaliert
    # auf Typ-Ebene. PERSONAL ist selten, die Versicherung ist billig.
    assert needs_second_review(sicht(type="correspondence")) is True


def test_other_eskaliert() -> None:
    # „Sonstiges" ist der Unsicherheits-Bucket — nachsehen.
    assert needs_second_review(sicht(type="other")) is True


def test_nur_urgency_this_week_ohne_alles_escalationsfrei() -> None:
    # this_week allein (ohne Antwortbedarf/Finanzen) ist keine Kritikalität.
    assert needs_second_review(sicht(type="notification", urgency="this_week")) is False
