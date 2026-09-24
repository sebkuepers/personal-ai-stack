"""The escalation rule of the inbox cascade — deterministic, and tested here.

Small triages everything (fast, cheap — the bulk is newsletters and
notifications). Medium re-checks only where a small mistake would be expensive:
a needed reply, money, a deadline today — plus the two small but delicate types
(correspondence and "other", where a missed reply would sink out of sight
before anyone looks).

The rule is deliberately Python and not a model's feeling: it decides about
money, and its failure directions are asymmetric —
- small reports too much → medium corrects it (cheap).
- small misses something critical → it has to escalate anyway.
So it escalates at TYPE level for correspondence/other and at FIELD level for
needs_reply / finance / urgency.
"""

from __future__ import annotations

from workflows.inbox.models import InboxReview

# Types that are ALWAYS re-checked: rare in volume, critical when wrong.
ALWAYS_ESCALATE = {"correspondence", "other"}


def needs_second_review(review: InboxReview) -> bool:
    """True when the second stage (medium) has to check this review."""
    return (
        review.needs_reply
        or review.finance_type != "none"
        or review.urgency == "today"
        or review.type in ALWAYS_ESCALATE
    )


# Urgencies that make a note worth carrying into a working session.
RELEVANT_URGENCIES = {"today", "this_week"}


def matters_for_vibe(review: InboxReview) -> bool:
    """True when this mail's note belongs in the dossier.

    The dossier is not a digest: it holds what changes what he does next. The
    first real run put fourteen notes in it, ten of which ended in "keine
    direkte Handlung erforderlich" — a GitHub PR summary, a weekly digest, a
    discount code. The agent writes ``context_for_vibe`` for everything, so the
    cut is made here, on the same fields the escalation rule uses.
    """
    return (
        review.needs_reply
        or review.finance_type != "none"
        or review.urgency in RELEVANT_URGENCIES
        or review.type in ALWAYS_ESCALATE
    )
