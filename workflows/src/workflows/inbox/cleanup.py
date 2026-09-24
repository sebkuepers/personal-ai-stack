"""The cleanup plan — what happens in Gmail follows from the triage.

Deterministic and therefore testable: the plan is pure arithmetic over the
reviews, not a model decision at runtime. The dangerous direction is
OVER-archiving: a mail that wants a reply or involves money must never end up
in the noise — which is why the rule checks ``needs_reply`` and
``finance_type`` BEFORE the type. The plan only ever runs behind a per-session
approval; it is never applied silently.
"""

from __future__ import annotations

from workflows.inbox.models import CleanupAction, ReviewItem

# These types are noise — ONLY as long as no reply and no money is involved.
NOISE_TYPES = {"newsletter", "notification", "transaction"}

NOISE = "noise"            # archive + mark read + processed label
FINANCE = "finance"        # label labels.finance, stays unread in the inbox
NEEDS_REPLY = "reply"      # label labels.needs_reply, stays unread
KEEP = "keep"              # no action — the uncertain rest stays where it is


def cleanup_plan(reviews: list[ReviewItem]) -> list[CleanupAction]:
    """One review → one action per thread."""
    plan: list[CleanupAction] = []
    for r in reviews:
        if r.review.needs_reply:
            action = NEEDS_REPLY
        elif r.review.finance_type != "none" or r.review.type == "invoice_payment":
            # The type itself counts as a signal: a mail the first stage took
            # for money is never handled by noise logic — even when the
            # finance_type field stayed empty (a contradictory review).
            action = FINANCE
        elif r.review.type in NOISE_TYPES:
            action = NOISE
        elif r.review.type == "correspondence":
            action = NEEDS_REPLY  # a human wrote — never noise, deadline or not
        else:
            action = KEEP
        plan.append(
            CleanupAction(
                thread_id=r.thread_id,
                action=action,
                sender=r.sender,
                subject=r.subject,
            )
        )
    return plan


def cleanup_summary(plan: list[CleanupAction], labels: dict[str, str]) -> str:
    """The plan in one sentence — for the confirmation before cleaning up.

    ``labels`` comes from the configuration so that the preview names the same
    labels the run will actually apply. German, because the author reads it.
    """
    noise = [a for a in plan if a.action == NOISE]
    finance = [a for a in plan if a.action == FINANCE]
    reply = [a for a in plan if a.action == NEEDS_REPLY]
    keep = [a for a in plan if a.action == KEEP]
    parts = []
    if noise:
        parts.append(f"{len(noise)} archivieren + gelesen setzen")
    if finance:
        parts.append(f"{len(finance)} behalten (Label {labels['finance']})")
    if reply:
        parts.append(f"{len(reply)} behalten (Label {labels['needs_reply']})")
    if keep:
        parts.append(f"{len(keep)} unangetastet")
    return ", ".join(parts) if parts else "nichts zu tun"
