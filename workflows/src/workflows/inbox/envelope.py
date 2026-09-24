"""Pure parsing of the Gmail answers into envelopes — the pitfalls live here.

Verified live (2026-09-23, measured against the account):
- ``search_threads`` returns bodies ALWAYS as null (644 messages, two runs).
- Some threads come back with ``messages: null`` — non-deterministically,
  26–57 per run on an identical query. Not an error, just a state.
- The category (UPDATES/PROMOTIONS/…) sits in ``labelIds`` as ``CATEGORY_*``.
- Spam and trash are excluded from the search by default.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from workflows.inbox.models import InboxEnvelope, SentEnvelope


def _to_date(text: str | None) -> date | None:
    """Shorten an ISO datetime („2026-09-23T12:59:32-07:00") to the date."""
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def thread_to_envelope(thread: dict) -> InboxEnvelope | None:
    """A raw thread from search_threads → envelope; None on ``messages: null``.

    The envelope is the LAST message of the thread — for a reply written by
    Sebastian himself his own address stands there (see own_address()).
    """
    messages = thread.get("messages")
    if not messages:
        return None
    m = messages[-1]
    labels = m.get("labelIds") or []
    category = next(
        (label[len("CATEGORY_") :] for label in labels if label.startswith("CATEGORY_")),
        "",
    )
    return InboxEnvelope(
        thread_id=thread.get("id") or "",
        message_id=m.get("id") or "",
        sender=m.get("sender") or "",
        subject=m.get("subject") or "",
        snippet=m.get("snippet") or "",
        labels=labels,
        category=category,
        unread="UNREAD" in labels,
        received_on=_to_date(m.get("date")),
    )


def thread_to_sent(thread: dict) -> SentEnvelope | None:
    """A raw thread from the sent search → sent envelope; None without messages."""
    messages = thread.get("messages")
    if not messages:
        return None
    m = messages[-1]
    to = m.get("toRecipients") or []
    if isinstance(to, str):
        to = [to]
    return SentEnvelope(
        thread_id=thread.get("id") or "",
        message_id=m.get("id") or "",
        sender=m.get("sender") or "",
        to=[a for a in to if a],
        subject=m.get("subject") or "",
        received_on=_to_date(m.get("date")),
    )


def own_address(sent: list[SentEnvelope]) -> str:
    """One's own address — the most frequent sender address in the sent window.

    Empty when nothing was sent; all inbox envelopes then stay triage
    candidates (the filter only bites with a known address).
    """
    counter = Counter(s.sender for s in sent if s.sender)
    if not counter:
        return ""
    return counter.most_common(1)[0][0]


def replied_recipients(sent: list[SentEnvelope]) -> set[str]:
    """Every address (lower-cased) written to within the window.

    The basis for the reply state: a "needs a reply" candidate whose sender is
    in here has probably been answered already.
    """
    addresses: set[str] = set()
    for s in sent:
        for address in s.to:
            addresses.add(address.strip().lower())
    return addresses
