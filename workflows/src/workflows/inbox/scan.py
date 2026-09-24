"""INBOX workflow — der tägliche Sichtungs-Lauf über Posteingang UND Postausgang.

Category: inbox (Gmail connector → on_behalf_of + OAuth).

Drei Schritte, beide Pässe deterministisch gelesen (Muster A — kein Lese-Agent):

  1. LESEN: INBOX und SENT des Fensters über ``search_threads`` (Umschläge,
     Bodies fehlen immer). Eigene Antworten im Posteingang sind keine
     Sichtungs-Kandidaten — sie gehören inhaltlich zum Postausgang.
  2. SICHTEN: Erstblick (small) sichtet jeden Umschlag, PARALLEL — sequenziell
     sprengen 50 Aufrufe das Workflow-Timeout (gemessen: TIMED_OUT). Die
     Eskalationsregel (``escalation.needs_second_review``) holt den Zweitblick
     (medium) nur für die kritische Teilmenge nach; er gewinnt.
  3. VERDICHTEN: Abmeldelinks für Newsletter aus den Bodies ziehen (reines
     Python, max_unsub Stück), dann deterministisch verdichten.

Phase 1 = DRY RUN: Dieser Lauf verändert nichts — kein Label, kein Draft,
nichts gesendet.

Live verifizierte Grundlagen (2026-09-23): Bodies in search_threads immer
null; ``messages: null`` schwankt pro Lauf (Normalfall, wird gezählt);
resultCountEstimate unbrauchbar — paginiert bis zum Tokenende; Seitenpause
1,2 s gegen Rate-Limit.

Trigger (lokal, Worker muss laufen):
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
    from workflows.inbox.gmail import gmail_search_threads, gmail_thread_body
    from workflows.inbox.classify import review_email, second_review_email

from workflows.crm.connectors import gmail_connector  # noqa: E402 — Wiederverwendung des Slots
from workflows.inbox.unsubscribe import extract_unsub_link  # noqa: E402
from workflows.inbox.escalation import needs_second_review  # noqa: E402
from workflows.inbox.models import (  # noqa: E402
    InboxEnvelope,
    InboxReview,
    InboxScanInput,
    InboxScanReport,
    UnsubCandidate,
)
from workflows.inbox.report import build_report  # noqa: E402
from workflows.inbox.envelope import (  # noqa: E402
    own_address,
    thread_to_sent,
    thread_to_envelope,
)

# Wie viele Sichtungen gleichzeitig laufen dürfen — 10 ist mit dem
# Conversations-API-Limit komfortabel unter dem Deckel.
_GLEICHZEITIG = 10


def _eingabe(u: InboxEnvelope, heute: date) -> dict:
    """Ein Umschlag als Stichwort-Argument für die Sichtungs-Aktivitäten."""
    return {
        "sender": u.sender,
        "subject": u.subject,
        "snippet": u.snippet,
        "category": u.category,
        "unread": u.unread,
        "received_on": u.received_on.isoformat() if u.received_on else None,
        "today": heute.isoformat(),
    }


@workflows.workflow.define(
    name="inbox-scan",
    on_behalf_of=True,  # required: acts with your Gmail OAuth credentials
    workflow_display_name="Inbox · Scan (dry run)",
    workflow_description=(
        "Täglicher Sichtungs-Lauf: liest Posteingang und Postausgang des Fensters "
        "über direkte Gmail-Tool-Aufrufe, sichtet jeden Umschlag mit der Kaskade "
        "Inbox · Review (small) → Inbox · Zweitblick (medium, kritische Fälle) "
        "und verdichtet deterministisch. Dry run — kein Label, kein Draft, "
        "nichts gesendet."
    ),
)
@uses_connectors(gmail_connector)
class InboxScanWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, params: InboxScanInput) -> InboxScanReport:
        # Step 1 — beide Pässe lesen (deterministisch, Null-Guard im Parser).
        inbox_roh = await gmail_search_threads(
            query=f"in:inbox newer_than:{params.window_days}d",
            max_threads=params.max_threads,
        )
        sent_roh = await gmail_search_threads(
            query=f"in:sent newer_than:{params.window_days}d",
            max_threads=params.max_threads,
        )

        umschlaege: list[InboxEnvelope] = []
        skipped = 0
        for thread in inbox_roh["threads"]:
            u = thread_to_envelope(thread)
            if u is None:
                skipped += 1
            else:
                umschlaege.append(u)
        gesendet = [
            g for t in sent_roh["threads"] if (g := thread_to_sent(t)) is not None
        ]

        # Eigene Antworten im Posteingang sind keine Sichtungs-Kandidaten:
        # Er hatte das letzte Wort; sie gehören inhaltlich zum Postausgang.
        eigene = own_address(gesendet)
        kandidaten = [
            u
            for u in umschlaege
            if not eigene or u.sender.strip().lower() != eigene.strip().lower()
        ]
        eigene_antworten = len(umschlaege) - len(kandidaten)

        if not kandidaten:
            return build_report(
                window_days=params.window_days,
                envelopes=[],
                reviews=[],
                gesendet=gesendet,
                abmeldungen=[],
                pages=inbox_roh["pages"],
                skipped_no_messages=skipped,
                own_replies=eigene_antworten,
                second_review_indices=set(),
                second_review_changed=0,
            )

        # Step 2 — Erstblick sichtet alles, parallel. today über die Aktivität:
        # Der Workflow-Körper darf keine Uhr lesen.
        heute = date.fromisoformat(await get_today())
        eingaben = [_eingabe(u, heute) for u in kandidaten]
        roh = await execute_activities_in_parallel(
            review_email, items=eingaben, max_concurrent_scheduled_tasks=_GLEICHZEITIG
        )
        reviews = [InboxReview.model_validate(r) for r in roh]

        # Zweitblick nur für die kritische Teilmenge — die Regel ist Python.
        # Gezählt wird, ob er ETWAS ÄNDERT (nicht nur nachsieht): Das ist der
        # Kill-Switch der Kaskade — auf den konstruierten Fällen re-rollte er
        # auch korrekte Erstblick-Antworten. Nach einer Woche echter Läufe
        # entscheidet diese Zahl, ob die zweite Stufe bleibt.
        # Mit ``second_review=False`` (Konfiguration der Sprechstunde) entfällt sie.
        indizes = (
            [i for i, r in enumerate(reviews) if needs_second_review(r)]
            if params.second_review
            else []
        )
        geaendert = 0
        if indizes:
            zweite_roh = await execute_activities_in_parallel(
                second_review_email,
                items=[eingaben[i] for i in indizes],
                max_concurrent_scheduled_tasks=_GLEICHZEITIG,
            )
            for i, r in zip(indizes, zweite_roh, strict=True):
                if r != roh[i]:
                    geaendert += 1
                reviews[i] = InboxReview.model_validate(r)

        # Step 3 — Abmeldelink für Newsletter aus dem Body ziehen (reines Python).
        abmeldungen: list[UnsubCandidate] = []
        for u, r in zip(kandidaten, reviews, strict=True):
            if r.type != "newsletter" or len(abmeldungen) >= params.max_unsub:
                continue
            body = await gmail_thread_body(u.thread_id)
            url = extract_unsub_link(body)
            if url:
                abmeldungen.append(
                    UnsubCandidate(
                        sender=u.sender,
                        subject=u.subject,
                        thread_id=u.thread_id,
                        url=url,
                    )
                )

        # Step 4 — deterministisch verdichten.
        return build_report(
            window_days=params.window_days,
            envelopes=kandidaten,
            reviews=reviews,
            gesendet=gesendet,
            abmeldungen=abmeldungen,
            pages=inbox_roh["pages"],
            skipped_no_messages=skipped,
            own_replies=eigene_antworten,
            second_review_indices=set(indizes),
            second_review_changed=geaendert,
        )
