"""INBOX workflow — the daily triage run over the inbox AND the sent folder.

Category: inbox (Gmail connector → the deployment's identity, see connectors.py).

Three steps, both passes read deterministically (pattern A — no reading agent):

  1. READ: inbox and sent for the window via ``search_threads`` (envelopes;
     bodies are always missing). One's own replies in the inbox are not triage
     candidates — they belong to the sent folder in substance.
  2. TRIAGE: the first stage (small) triages every envelope, IN PARALLEL —
     sequentially, 50 calls blow the workflow timeout (measured: TIMED_OUT).
     The escalation rule (``escalation.needs_second_review``) pulls in the
     second stage (medium) for the critical subset only; it wins.
  3. CONDENSE: pull unsubscribe links for newsletters out of the bodies (pure
     Python, at most max_unsub of them), then condense deterministically.

Phase 1 = DRY RUN: this run changes nothing — no label, no draft, nothing sent.

Foundations verified live (2026-09-23): bodies in search_threads always null;
``messages: null`` varies per run (the normal case, and counted);
resultCountEstimate useless — paginate to the end of the token; 1.2 s page
pause against the rate limit.

Trigger (locally, the worker has to run):
  make inbox-scan
  make inbox-scan input='{"window_days":1,"max_threads":50}'
"""

from __future__ import annotations

from datetime import date

import mistralai.workflows as workflows
from mistralai.workflows import execute_activities_in_parallel, workflow
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors

with workflow.unsafe.imports_passed_through():
    from workflows.crm.agent_tools import get_today
    from workflows.inbox.classify import review_email, second_review_email
    from workflows.inbox.gmail import gmail_search_threads, gmail_thread_body

from workflows.inbox.connectors import gmail_connector  # noqa: E402
from workflows.inbox.envelope import (  # noqa: E402
    own_address,
    thread_to_envelope,
    thread_to_sent,
)
from workflows.inbox.escalation import needs_second_review  # noqa: E402
from workflows.inbox.models import (  # noqa: E402
    InboxEnvelope,
    InboxReview,
    InboxScanInput,
    InboxScanReport,
    UnsubCandidate,
)
from workflows.inbox.report import build_report  # noqa: E402
from workflows.inbox.window import calendar_window, gmail_query  # noqa: E402
from workflows.inbox.unsubscribe import extract_unsub_link  # noqa: E402

# How many triage calls may run at once — 10 sits comfortably under the
# conversations API limit.
_CONCURRENT = 10


def _input_for(envelope: InboxEnvelope, today: date) -> dict:
    """One envelope as keyword arguments for the triage activities."""
    return {
        "sender": envelope.sender,
        "subject": envelope.subject,
        "snippet": envelope.snippet,
        "category": envelope.category,
        "unread": envelope.unread,
        "received_on": envelope.received_on.isoformat() if envelope.received_on else None,
        "today": today.isoformat(),
    }


@workflows.workflow.define(
    name="inbox-scan",
    # The DEPLOYMENT's identity, not a user session — see inbox/connectors.py.
    # That is what makes this workflow schedulable at all (gotcha 19).
    on_behalf_of=False,
    workflow_display_name="Inbox · Scan (dry run)",
    workflow_description=(
        "Täglicher Sichtungs-Lauf: liest Posteingang und Postausgang des Fensters "
        "über direkte Gmail-Tool-Aufrufe, sichtet jeden Umschlag mit der Kaskade "
        "Inbox · Review (small) → Inbox · Second read (medium, kritische Fälle) "
        "und verdichtet deterministisch. Dry run — kein Label, kein Draft, "
        "nichts gesendet."
    ),
)
@uses_connectors(gmail_connector)
class InboxScanWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, params: InboxScanInput) -> InboxScanReport:
        # Step 1 — read both passes over CALENDAR days. today comes through an
        # activity: the workflow body must not read a clock.
        today = date.fromisoformat(await get_today())
        window = calendar_window(today, params.window_days, params.include_today)
        inbox_raw = await gmail_search_threads(
            query=gmail_query("in:inbox", window),
            max_threads=params.max_threads,
        )
        sent_raw = await gmail_search_threads(
            query=gmail_query("in:sent", window),
            max_threads=params.max_threads,
        )

        envelopes: list[InboxEnvelope] = []
        skipped = 0
        for thread in inbox_raw["threads"]:
            envelope = thread_to_envelope(thread)
            if envelope is None:
                skipped += 1
            else:
                envelopes.append(envelope)
        sent = [
            s for t in sent_raw["threads"] if (s := thread_to_sent(t)) is not None
        ]

        # One's own replies in the inbox are not triage candidates: he had the
        # last word; in substance they belong to the sent folder.
        own = own_address(sent)
        candidates = [
            e
            for e in envelopes
            if not own or e.sender.strip().lower() != own.strip().lower()
        ]
        own_replies = len(envelopes) - len(candidates)

        if not candidates:
            return build_report(
                window_days=params.window_days,
                envelopes=[],
                reviews=[],
                sent=sent,
                unsub_links=[],
                pages=inbox_raw["pages"],
                skipped_no_messages=skipped,
                own_replies=own_replies,
                second_review_indices=set(),
                second_review_changed=0,
                window=window,
                truncated=inbox_raw["has_more"],
            )

        # Step 2 — the first stage triages everything, in parallel.
        inputs = [_input_for(e, today) for e in candidates]
        raw = await execute_activities_in_parallel(
            review_email, items=inputs, max_concurrent_scheduled_tasks=_CONCURRENT
        )
        reviews = [InboxReview.model_validate(r) for r in raw]

        # The second stage only for the critical subset — the rule is Python.
        # What is counted is whether it CHANGES ANYTHING (not merely that it
        # looked): that is the cascade's kill switch — on the constructed cases
        # it re-rolled correct first-stage answers too. After a week of real
        # runs that number decides whether the second stage stays.
        # With ``second_review=False`` (chosen in the conversation) it is skipped.
        indices = (
            [i for i, r in enumerate(reviews) if needs_second_review(r)]
            if params.second_review
            else []
        )
        changed = 0
        if indices:
            second_raw = await execute_activities_in_parallel(
                second_review_email,
                items=[inputs[i] for i in indices],
                max_concurrent_scheduled_tasks=_CONCURRENT,
            )
            for i, r in zip(indices, second_raw, strict=True):
                second = InboxReview.model_validate(r)
                # Compare the VERDICT, not the whole answer: reasoning is free
                # text and always differs between two models. See
                # InboxReview.verdict().
                if second.verdict() != reviews[i].verdict():
                    changed += 1
                reviews[i] = second

        # Step 3 — pull the unsubscribe link for newsletters out of the body
        # (pure Python).
        unsub_links: list[UnsubCandidate] = []
        unsub_checked = 0
        for envelope, review in zip(candidates, reviews, strict=True):
            if review.type != "newsletter" or unsub_checked >= params.max_unsub:
                continue
            unsub_checked += 1
            body = await gmail_thread_body(envelope.thread_id)
            url = extract_unsub_link(body)
            if url:
                unsub_links.append(
                    UnsubCandidate(
                        sender=envelope.sender,
                        subject=envelope.subject,
                        thread_id=envelope.thread_id,
                        url=url,
                    )
                )

        # Step 4 — condense deterministically.
        return build_report(
            window_days=params.window_days,
            envelopes=candidates,
            reviews=reviews,
            sent=sent,
            unsub_links=unsub_links,
            pages=inbox_raw["pages"],
            skipped_no_messages=skipped,
            own_replies=own_replies,
            second_review_indices=set(indices),
            second_review_changed=changed,
            window=window,
            truncated=inbox_raw["has_more"],
            unsub_checked=unsub_checked,
        )
