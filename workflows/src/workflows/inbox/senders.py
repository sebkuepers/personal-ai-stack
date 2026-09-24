"""INBOX workflow — Absender-Statistik: die falsifizierbare Abbestell-Grundlage.

Category: inbox (Gmail connector → on_behalf_of + OAuth). Reine Arithmetik,
kein einziger Modellaufruf — genau wie die Messung, auf der sie beruht
(2026-09-23 live gemessen): „647 Mails, 0 gelesen" schlägt „fühlt sich nach
zu viel an".

Default-Scope: ``-in:sent newer_than:<n>d`` — alles EMPFANGENE, das ihn
erreicht. Zwei bewusste Grenzen, live verifiziert:
- Spam und Trash sind von der Gmail-Suche standardmäßig AUSGESCHLOSSEN. In der
  Trash liegen meist selbst gelöschte Mails (gemessen: my-hammer — dielöschte
  Sebastian von Hand, Gmail hat dort nichts weggefiltert), im Spam das, was
  Gmail begraben hat. Beides ist kein *aktueller* Lärm — wer alles sehen
  will, übergibt ``in:anywhere`` im query.
- Gesendete Mails sind ausgeschlossen — sie sind kein Lärm.

Ein kompletter 90-Tage-Lauf: ~70+ Seiten à 1,2 s Pause, rund 4 Minuten.

Trigger (lokal, Worker muss laufen):
  make inbox-senders fenster=90
"""

from __future__ import annotations

from collections import Counter

import mistralai.workflows as workflows
from mistralai.workflows import workflow
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors

with workflow.unsafe.imports_passed_through():
    from workflows.inbox.gmail import gmail_search_threads

from workflows.crm.connectors import gmail_connector  # noqa: E402 — Wiederverwendung des Slots
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
        roh = await gmail_search_threads(query=query, max_threads=params.max_threads)

        mails: Counter[str] = Counter()
        unread: Counter[str] = Counter()
        skipped = 0
        for thread in roh["threads"]:
            u = thread_to_envelope(thread)
            if u is None:
                skipped += 1
                continue
            mails[u.sender] += 1
            if u.unread:
                unread[u.sender] += 1

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
