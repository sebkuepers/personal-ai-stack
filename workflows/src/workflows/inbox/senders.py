"""INBOX workflow — the sender statistic: the falsifiable basis for unsubscribing.

Pure arithmetic, not a single model call — just like the measurement it rests
on (measured live 2026-09-23): "647 mails, 0 read" beats "feels like too much".

Default scope: ``-in:sent newer_than:<n>d`` — everything RECEIVED that reaches
him. Two deliberate limits, verified live:
- Spam and trash are EXCLUDED from the Gmail search by default. The trash
  mostly holds mails he deleted himself, the spam what Gmail buried. Neither is
  *current* noise — whoever wants to see everything passes ``in:anywhere`` in
  the query.
- Sent mails are excluded — they are not noise.

A complete 90-day run: ~70+ pages at 1.2 s pause each, around four minutes.

Trigger (locally, the worker has to run):
  make inbox-senders window=90
"""

from __future__ import annotations

from collections import Counter

import mistralai.workflows as workflows
from mistralai.workflows import workflow
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors

with workflow.unsafe.imports_passed_through():
    from workflows.inbox.gmail import gmail_search_threads

from workflows.crm.connectors import gmail_connector  # noqa: E402 — reuses the slot
from workflows.inbox.models import (  # noqa: E402
    SenderItem,
    SenderStats,
    SenderStatsInput,
)
from workflows.inbox.envelope import thread_to_envelope  # noqa: E402


@workflows.workflow.define(
    name="inbox-senders",
    on_behalf_of=True,  # required: acts with your Gmail OAuth credentials
    workflow_display_name="Inbox · Sender Stats",
    workflow_description=(
        "Zählt Mails und ungelesene Mails pro Absender im Fenster — reine "
        "Arithmetik, kein Modellaufruf. Die Grundlage für Abbestell-Entscheidungen: "
        "Rangfolge nach Lärm, nicht nach Gefühl."
    ),
)
@uses_connectors(gmail_connector)
class InboxSendersWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, params: SenderStatsInput) -> SenderStats:
        query = params.query or f"-in:sent newer_than:{params.window_days}d"
        raw = await gmail_search_threads(query=query, max_threads=params.max_threads)

        mails: Counter[str] = Counter()
        unread: Counter[str] = Counter()
        skipped = 0
        for thread in raw["threads"]:
            envelope = thread_to_envelope(thread)
            if envelope is None:
                skipped += 1
                continue
            mails[envelope.sender] += 1
            if envelope.unread:
                unread[envelope.sender] += 1

        senders = [
            SenderItem(sender=s, mails=n, unread=unread[s])
            for s, n in sorted(mails.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        return SenderStats(
            window_days=params.window_days,
            query=query,
            threads=sum(mails.values()),
            skipped_no_messages=skipped,
            senders=senders,
            unread_total=sum(unread.values()),
        )
