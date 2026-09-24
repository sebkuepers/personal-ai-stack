"""Applying a cleanup plan — the one place in the repo that changes the mailbox.

Both callers use this: the conversation (``inbox-review``) after an explicit
approval, and the nightly round (``inbox-daily``) without one. They must not
drift — if the conversation and the night handle a thread differently, the
mailbox stops being something one can reason about.

What happens here is level 2 of the safety ladder and deliberately nothing
more: archiving is removing the ``INBOX`` label, marking read is removing
``UNREAD``, and both are reversible in Gmail with one click. Level 3 (a draft)
only ever happens for a mailto unsubscribe, and the connector **cannot send** —
which is the property that makes an unattended run acceptable at all.
"""

from __future__ import annotations

from mistralai.workflows import execute_activities_in_parallel

from workflows.inbox import config
from workflows.inbox.cleanup import FINANCE, KEEP, NOISE
from workflows.inbox.gmail import gmail_draft, gmail_ensure_label, gmail_process_thread
from workflows.inbox.models import CleanupAction, CleanupResult, UnsubCandidate

# What a run is allowed to do. The value lives in shared/inbox.json so it can be
# dialled back without touching code.
FULL = "full"  # archive noise, label the rest, draft mailto unsubscribes
LABEL_ONLY = "label_only"  # label everything, archive nothing
NOTHING = "nothing"

# How many label calls may run at once — the same figure the triage uses.
_CONCURRENT = 10


def root_reason(exc: BaseException) -> str:
    """The innermost message of an exception chain, with Temporal's details.

    Temporal wraps an activity failure in ActivityError, whose ``str()`` is the
    useless "Activity task failed", and carries the connector's own answer in
    ``details`` rather than in the message. Both together are the difference
    between "something went wrong" and "Gmail says: Invalid label name".
    """
    current: BaseException = exc
    while current.__cause__ is not None:
        current = current.__cause__
    text = str(current).strip() or type(current).__name__
    for detail in getattr(current, "details", None) or ():
        extra = str(detail).strip()
        if extra and extra not in text:
            text = f"{text} — {extra}"
            break
    return " ".join(text.split())[:300]


async def apply_cleanup(
    plan: list[CleanupAction],
    mailto: list[UnsubCandidate],
    mode: str,
) -> CleanupResult:
    """Run the plan. Returns the receipt — including the reason when it failed.

    Never raises: a failing label must not take down the run that produced the
    report and the dossier, and the caller decides how to show the reason. The
    error text is the ACTUAL one, never a guessed cause — the last two times
    this failed the screen named a missing permission and it was, once, a stale
    OAuth grant and, once, a label name Gmail reserves.
    """
    if mode == NOTHING or not plan:
        return CleanupResult(skipped=len(plan))

    # The label names come from shared/inbox.json, never from here (golden
    # rule 2) — otherwise the run applies different labels than the report
    # claims it did.
    try:
        label_processed = await gmail_ensure_label(name=config.LABELS["processed"])
        label_finance = await gmail_ensure_label(name=config.LABELS["finance"])
        label_reply = await gmail_ensure_label(name=config.LABELS["needs_reply"])
    except Exception as exc:  # noqa: BLE001 — the reason belongs in the receipt
        return CleanupResult(skipped=len(plan), errors=[root_reason(exc)])

    archive = mode == FULL
    result = CleanupResult()
    items: list[dict] = []
    for action in plan:
        if action.action == KEEP or not action.thread_id:
            result.skipped += 1
            continue
        if action.action == NOISE:
            items.append({
                "thread_id": action.thread_id, "label_id": label_processed,
                "archive": archive, "mark_read": archive,
            })
            result.archived += 1 if archive else 0
            result.marked_read += 1 if archive else 0
        elif action.action == FINANCE:
            items.append({
                "thread_id": action.thread_id, "label_id": label_finance,
                "archive": False, "mark_read": False,
            })
            result.labelled_finance += 1
        else:  # NEEDS_REPLY
            items.append({
                "thread_id": action.thread_id, "label_id": label_reply,
                "archive": False, "mark_read": False,
            })
            result.labelled_reply += 1

    # In parallel, like the triage. Sequentially this took ten minutes for one
    # day: two connector calls per thread, sixty threads, one after the other.
    # The concurrency is the same 10 the triage uses — comfortably under the
    # rate limit, measured.
    if items:
        await execute_activities_in_parallel(
            gmail_process_thread, items=items, max_concurrent_scheduled_tasks=_CONCURRENT
        )

    if archive:
        for u in mailto:
            await gmail_draft(
                to=u.url[7:],  # strip "mailto:"
                subject="Abmeldung",
                body="Bitte nehmen Sie diese Adresse von allen Verteilern.",
            )
            result.mailto_drafts += 1
    return result
