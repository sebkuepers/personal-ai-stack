"""Die Verdichtung eines Sichtungs-Laufs ist deterministisch — hier ist ihr Vertrag.

``report.build_report`` zählt und sortiert; kein Modell, kein I/O. Die Zahlen
landen im täglichen Report, ein Fehler hier verfälscht jede Entscheidung, die
darauf basiert. Der Langweilfall ist ausdrücklich dabei: eine leere Runde muss
einen leeren, aber wohlgeformten Report ergeben. Und der Antwort-Zustand kommt
aus dem Sent-Fenster — Offene vor Beantworteten, das ist der Punkt des Digests.
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


# ---------------------------------------------------------------------------
# Der Langweilfall zuerst: nichts gefunden, nichts zu melden
# ---------------------------------------------------------------------------


def test_leerer_lauf_gibt_leeren_bericht() -> None:
    report = build_report(
        window_days=1, envelopes=[], reviews=[], gesendet=[], abmeldungen=[],
        pages=3, skipped_no_messages=4, own_replies=0,
    )
    assert report.inbox_found == 0
    assert report.skipped_no_messages == 4
    assert report.type_counts == {}
    assert report.subscription_groups == {}
    assert report.needs_reply == []
    assert report.finanzen == []
    assert report.sent == []


def test_envelopes_und_reviews_muessen_paarweise_sein() -> None:
    with pytest.raises(ValueError, match="paarweise"):
        build_report(
            window_days=1, envelopes=[umschlag()], reviews=[], gesendet=[],
            abmeldungen=[], pages=1, skipped_no_messages=0, own_replies=0,
        )


# ---------------------------------------------------------------------------
# Antwort-Zustand — der Grund, warum der Digest auch den Postausgang liest
# ---------------------------------------------------------------------------


def test_beantwortete_landen_hinten_offene_vorne() -> None:
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
        gesendet=[gesendet(to=["b@example.com"])],
        abmeldungen=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert [(a.sender, a.beantwortet) for a in report.needs_reply] == [
        ("a@example.com", False),
        ("b@example.com", True),
    ]


def test_antwortbedarf_nur_bei_flag_sortiert_nach_urgency() -> None:
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
        gesendet=[],
        abmeldungen=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert [a.urgency for a in report.needs_reply] == [
        "today",
        "this_week",
        "whenever",
    ]
    assert all(a.subject != "Ohne Antwortbedarf" for a in report.needs_reply)


def test_gleiche_urgency_nach_absender() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag("A", "z@example.com"), umschlag("B", "a@example.com")],
        reviews=[
            sicht(type="correspondence", needs_reply=True, urgency="today"),
            sicht(type="correspondence", needs_reply=True, urgency="today"),
        ],
        gesendet=[], abmeldungen=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert [a.sender for a in report.needs_reply] == ["a@example.com", "z@example.com"]


# ---------------------------------------------------------------------------
# Zählen und Gruppieren
# ---------------------------------------------------------------------------


def test_typ_zaehlung_und_leere_subscription_group_zaehlt_nicht() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag(), umschlag("Re: Termin", "mensch@example.com"), umschlag()],
        reviews=[
            sicht(type="newsletter", subscription_group="LinkedIn"),
            sicht(type="correspondence"),
            sicht(type="notification", subscription_group=""),
        ],
        gesendet=[], abmeldungen=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert report.type_counts == {"newsletter": 1, "notification": 1, "correspondence": 1}
    assert report.subscription_groups == {"LinkedIn": 1}


def test_subscription_groups_nach_laerm_sortiert_dann_alphabetisch() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag()] * 4,
        reviews=[
            sicht(subscription_group="Zeit"),
            sicht(subscription_group="LinkedIn"),
            sicht(subscription_group="LinkedIn"),
            sicht(subscription_group="Amazon"),
        ],
        gesendet=[], abmeldungen=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert list(report.subscription_groups) == ["LinkedIn", "Amazon", "Zeit"]


def test_finanzen_nur_bei_art_und_mit_allen_feldern() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag("Mahnung"), umschlag("Newsletter")],
        reviews=[
            sicht(
                type="invoice_payment",
                finance_type="reminder",
                betrag="89,00 EUR",
                due_date="2026-09-25",
            ),
            sicht(type="newsletter", finance_type="none"),
        ],
        gesendet=[], abmeldungen=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert len(report.finanzen) == 1
    f = report.finanzen[0]
    assert (f.art, f.betrag, f.due_date) == ("reminder", "89,00 EUR", "2026-09-25")


def test_kontext_sammelt_nur_nicht_leere_eintraege() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag(), umschlag(), umschlag("Re: Termin")],
        reviews=[
            sicht(context_for_vibe="Zusage für Freitag, 10 Uhr."),
            sicht(context_for_vibe=""),
            sicht(type="notification", context_for_vibe="Zahnarzttermin morgen 9 Uhr."),
        ],
        gesendet=[], abmeldungen=[],
        pages=1, skipped_no_messages=0, own_replies=0,
    )
    assert report.kontext == ["Zusage für Freitag, 10 Uhr.", "Zahnarzttermin morgen 9 Uhr."]


# ---------------------------------------------------------------------------
# Sent-Sektion, Abmeldelinks und Kopfzahlen
# ---------------------------------------------------------------------------


def test_second_review_flag_and_count() -> None:
    report = build_report(
        window_days=1,
        envelopes=[umschlag("Re: Termin", "mensch@example.com"), umschlag("Rundbrief")],
        reviews=[
            sicht(type="correspondence"),
            sicht(type="newsletter"),
        ],
        gesendet=[], abmeldungen=[],
        pages=1, skipped_no_messages=0, own_replies=0,
        second_review_indices={0},
    )
    assert report.second_review_count == 1
    assert report.reviews[0].second_review is True
    assert report.reviews[1].second_review is False


def test_sent_und_abmeldungen_werden_durchgereicht() -> None:
    s = gesendet(to=["marie@example.com"])
    kandidat = UnsubCandidate(
        sender="news@example.com", subject="Rundbrief", thread_id="t1",
        url="https://news.example.com/out",
    )
    report = build_report(
        window_days=1,
        envelopes=[umschlag("Rundbrief", "news@example.com")],
        reviews=[sicht(reasoning="Massenversand mit Abbestell-Link.")],
        gesendet=[s],
        abmeldungen=[kandidat],
        pages=7, skipped_no_messages=26, own_replies=2,
    )
    assert report.sent == [s]
    assert report.unsub_links == [kandidat]
    assert report.pages == 7
    assert report.skipped_no_messages == 26
    assert report.own_replies == 2
    assert len(report.reviews) == 1
    assert report.reviews[0].review.type == "newsletter"
