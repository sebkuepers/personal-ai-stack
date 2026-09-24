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
