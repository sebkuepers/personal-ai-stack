"""Deterministische Verdichtung einer Sichtungs-Runde — pur, ohne I/O.

Das Zählen ist bewusst kein Modell-Job: Anteile, Gruppen und Sortierung sind
Mathematik, und Mathematik gehört in Python („messen vor modellieren").
Der Antwort-Zustand kommt aus dem Sent-Fenster — wer eine Mail geschrieben
hat, braucht keine Erinnerung mehr.
"""

from __future__ import annotations

from workflows.inbox.models import (
    ReplyItem,
    FinanceItem,
    InboxEnvelope,
    InboxReview,
    InboxScanReport,
    ReviewItem,
    SentEnvelope,
    UnsubCandidate,
)
from workflows.inbox.envelope import replied_recipients

# Dringlichkeit als Sortierschlüssel: today vor this_week vor whenever.
_URGENCY_RANK = {"today": 0, "this_week": 1, "whenever": 2}


def build_report(
    window_days: int,
    envelopes: list[InboxEnvelope],
    reviews: list[InboxReview],
    gesendet: list[SentEnvelope],
    abmeldungen: list[UnsubCandidate],
    pages: int,
    skipped_no_messages: int,
    own_replies: int,
    second_review_indices: set[int] | None = None,
    second_review_changed: int = 0,
) -> InboxScanReport:
    """Verdichtet (Umschlag, Sichtung)-Paare, das Sent-Fenster und die Abmeldelinks.

    ``envelopes`` und ``reviews`` müssen paarweise geordnet sein — genau so
    erzeugt sie der Workflow (``zip(strict=True)`` erzwingt es).
    ``second_review_indices`` markiert, welche Sichtungen die zweite Stufe
    geprüft hat — die Zahl entscheidet, ob die Kaskade bleibt.
    """
    if len(envelopes) != len(reviews):
        raise ValueError(
            f"envelopes und reviews müssen paarweise sein: {len(envelopes)} vs. {len(reviews)}"
        )
    beantwortet = replied_recipients(gesendet)
    second_review_indices = second_review_indices or set()

    type_counts: dict[str, int] = {}
    subscription_groups: dict[str, int] = {}
    antwort: list[ReplyItem] = []
    finanzen: list[FinanceItem] = []
    kontext: list[str] = []
    items: list[ReviewItem] = []

    for index, (mail, review) in enumerate(zip(envelopes, reviews, strict=True)):
        type_counts[review.type] = type_counts.get(review.type, 0) + 1
        if review.subscription_group:
            subscription_groups[review.subscription_group] = subscription_groups.get(review.subscription_group, 0) + 1
        if review.needs_reply:
            antwort.append(
                ReplyItem(
                    sender=mail.sender,
                    subject=mail.subject,
                    urgency=review.urgency,
                    reasoning=review.reasoning,
                    beantwortet=mail.sender.strip().lower() in beantwortet,
                )
            )
        if review.finance_type != "none":
            finanzen.append(
                FinanceItem(
                    sender=mail.sender,
                    subject=mail.subject,
                    art=review.finance_type,
                    betrag=review.betrag,
                    due_date=review.due_date,
                )
            )
        if review.context_for_vibe:
            kontext.append(review.context_for_vibe)
        items.append(
            ReviewItem(
                thread_id=mail.thread_id,
                sender=mail.sender,
                subject=mail.subject,
                received_on=mail.received_on,
                second_review=index in second_review_indices,
                review=review,
            )
        )

    # Antwortbedarf nach Dringlichkeit, dann nach Absender — gleiche Dringlichkeit
    # braucht eine stabile, lesbare Reihenfolge. Beantwortete nach hinten.
    antwort.sort(
        key=lambda a: (
            a.beantwortet,  # False < True — Offene zuerst
            _URGENCY_RANK.get(a.urgency, 3),
            a.sender,
        )
    )
    # Abo-Gruppen nach Lärm: die lauteste Quelle zuerst, dann alphabetisch.
    abo_sortiert = dict(sorted(subscription_groups.items(), key=lambda kv: (-kv[1], kv[0])))

    return InboxScanReport(
        window_days=window_days,
        inbox_found=len(envelopes),
        skipped_no_messages=skipped_no_messages,
        own_replies=own_replies,
        pages=pages,
        second_review_count=len(second_review_indices),
        second_review_changed=second_review_changed,
        type_counts=type_counts,
        subscription_groups=abo_sortiert,
        needs_reply=antwort,
        finanzen=finanzen,
        kontext=kontext,
        unsub_links=abmeldungen,
        sent=gesendet,
        reviews=items,
    )
