"""Deterministic condensation of one triage run — pure, no I/O.

Counting is deliberately not a model's job: shares, groups and ordering are
arithmetic, and arithmetic belongs in Python ("measure before you model").
The reply state comes from the sent window — whoever has written a mail needs
no reminder.
"""

from __future__ import annotations

from workflows.inbox.envelope import replied_recipients
from workflows.inbox.models import (
    FinanceItem,
    InboxEnvelope,
    InboxReview,
    InboxScanReport,
    ReplyItem,
    ReviewItem,
    SentEnvelope,
    UnsubCandidate,
)

# Urgency as a sort key: today before this_week before whenever.
_URGENCY_RANK = {"today": 0, "this_week": 1, "whenever": 2}


def build_report(
    window_days: int,
    envelopes: list[InboxEnvelope],
    reviews: list[InboxReview],
    sent: list[SentEnvelope],
    unsub_links: list[UnsubCandidate],
    pages: int,
    skipped_no_messages: int,
    own_replies: int,
    second_review_indices: set[int] | None = None,
    second_review_changed: int = 0,
) -> InboxScanReport:
    """Condense (envelope, review) pairs, the sent window and the unsubscribe links.

    ``envelopes`` and ``reviews`` have to be ordered pairwise — which is exactly
    how the workflow produces them (``zip(strict=True)`` enforces it).
    ``second_review_indices`` marks which reviews the second stage checked —
    that number decides whether the cascade stays.
    """
    if len(envelopes) != len(reviews):
        raise ValueError(
            f"envelopes and reviews have to be pairwise: {len(envelopes)} vs. {len(reviews)}"
        )
    answered_addresses = replied_recipients(sent)
    second_review_indices = second_review_indices or set()

    type_counts: dict[str, int] = {}
    groups: dict[str, int] = {}
    replies: list[ReplyItem] = []
    finance: list[FinanceItem] = []
    context: list[str] = []
    items: list[ReviewItem] = []

    for index, (mail, review) in enumerate(zip(envelopes, reviews, strict=True)):
        type_counts[review.type] = type_counts.get(review.type, 0) + 1
        if review.subscription_group:
            groups[review.subscription_group] = groups.get(review.subscription_group, 0) + 1
        if review.needs_reply:
            replies.append(
                ReplyItem(
                    sender=mail.sender,
                    subject=mail.subject,
                    urgency=review.urgency,
                    reasoning=review.reasoning,
                    answered=mail.sender.strip().lower() in answered_addresses,
                )
            )
        if review.finance_type != "none":
            finance.append(
                FinanceItem(
                    sender=mail.sender,
                    subject=mail.subject,
                    kind=review.finance_type,
                    amount=review.amount,
                    due_date=review.due_date,
                )
            )
        if review.context_for_vibe:
            context.append(review.context_for_vibe)
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

    # Replies by urgency, then by sender — equal urgency needs a stable,
    # readable order. Already-answered ones go to the back.
    replies.sort(
        key=lambda r: (
            r.answered,  # False < True — open ones first
            _URGENCY_RANK.get(r.urgency, 3),
            r.sender,
        )
    )
    # Subscription groups by noise: the loudest source first, then alphabetically.
    groups_sorted = dict(sorted(groups.items(), key=lambda kv: (-kv[1], kv[0])))

    return InboxScanReport(
        window_days=window_days,
        inbox_found=len(envelopes),
        skipped_no_messages=skipped_no_messages,
        own_replies=own_replies,
        pages=pages,
        second_review_count=len(second_review_indices),
        second_review_changed=second_review_changed,
        type_counts=type_counts,
        subscription_groups=groups_sorted,
        needs_reply=replies,
        finance=finance,
        context=context,
        unsub_links=unsub_links,
        sent=sent,
        reviews=items,
    )
