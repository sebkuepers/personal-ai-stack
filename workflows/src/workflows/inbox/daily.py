"""INBOX workflow — the nightly round, unattended.

Category: inbox (Gmail connector → the deployment's identity, see connectors.py).

The conversational sibling (``inbox-review``) is the workplace: it asks, it
shows, it waits for an approval before it touches anything. This one is the
opposite — it runs while nobody is there, and therefore it does exactly two
things and nothing else:

  1. triage YESTERDAY, the complete calendar day (``include_today=False``),
  2. apply the cleanup plan — archive the noise, label what wants a reply and
     what involves money, prepare mailto unsubscribes as drafts, and
  3. write the dossier into the library, receipt included.

It was read-only at first, on the argument that level 2 of the safety ladder
needs an approval per session and a scheduled run has nobody to ask. That was
the wrong way round: **the nightly round is the norm**, and the approval was
guarding something that does not hurt. Archiving is removing the ``INBOX``
label, marking read is removing ``UNREAD`` — both reversible in Gmail with one
click. What is genuinely irreversible stays impossible: the connector has no
tool to send, so the worst case is a draft nobody asked for.

What it does is in ``shared/inbox.json`` (``schedule.cleanup``), so it can be
dialled back to ``label_only`` or ``nothing`` without touching code. The plan
itself runs through ``inbox/apply.py`` — the same code the conversation uses,
so the night and the chat can never handle a thread differently.

Why the window is a calendar day and not ``newer_than:1d``: consecutive runs
have to tile the calendar without gap or overlap, or a daily job cannot be
reasoned about at all. See ``window.calendar_window``.

Why ``on_behalf_of=False``: a scheduled execution carries no user identity, so
the connector runs as the deployment. This is the whole reason the inbox domain
has its own connector slot — workflows/CLAUDE.md gotcha 19.

The schedule lives HERE, in the code, not in a cron somewhere else: the worker
registers it with Studio at startup and refreshes it, so the repo stays the
single source of truth for when this runs.

Trigger by hand (the worker has to run):
  make inbox-daily
"""

from __future__ import annotations

from datetime import date

import mistralai.workflows as workflows
from mistralai.workflows import workflow
from mistralai.workflows.models import ScheduleDefinition
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors

with workflow.unsafe.imports_passed_through():
    from workflows.crm.agent_tools import get_today
    from workflows.inbox.apply import apply_cleanup
    from workflows.inbox.library import store_dossier

from workflows.inbox import config  # noqa: E402
from workflows.inbox.connectors import gmail_connector  # noqa: E402
from workflows.inbox.models import (  # noqa: E402
    DailyResult,
    InboxScanInput,
    InboxScanReport,
)
from workflows.inbox.cleanup import cleanup_plan  # noqa: E402
from workflows.inbox.render import dossier  # noqa: E402
from workflows.inbox.scan import InboxScanWorkflow  # noqa: E402
from workflows.inbox.unsubscribe import is_mailto  # noqa: E402

# 06:00 Europe/Berlin — before the working day, after the night's mail has
# landed. The window is the day BEFORE that, complete. Time and zone come from
# shared/inbox.json, not from here (golden rule 2).
DAILY_SCHEDULE = ScheduleDefinition(
    input={},
    cron_expressions=[config.DAILY_CRON],
    time_zone_name=config.SCHEDULE_TIME_ZONE,
)

# ONLY the deployment named in shared/inbox.json carries the schedule. A worker
# registers schedules under its own deployment name, so with two workers — the
# laptop and the Cloudflare container — the round would run twice a day. And a
# schedule owned by the laptop fires only while the laptop is awake, which is
# the one thing a nightly job must not depend on. Everywhere else this workflow
# is trigger-only (`make inbox-daily`).
SCHEDULES = [DAILY_SCHEDULE] if config.schedules_here() else []

# The brake, not a filter: a quiet day brings ~46 threads. If a day ever exceeds
# this the report says so (``truncated``) instead of silently dropping the rest.
_MAX_THREADS = 200


@workflows.workflow.define(
    name="inbox-daily",
    on_behalf_of=False,  # the deployment's identity — see inbox/connectors.py
    schedules=SCHEDULES,
    workflow_display_name="Inbox · Täglich (unbeaufsichtigt)",
    workflow_description=(
        "Der Nachtlauf: sichtet den kompletten Vortag und legt das Dossier in "
        "der Library ab. Verändert nichts im Postfach — kein Label, kein "
        "Entwurf, kein Archivieren. Läuft ohne Rückfrage, weil er nichts zu "
        "fragen hat."
    ),
)
@uses_connectors(gmail_connector)
class InboxDailyWorkflow:
    @workflows.workflow.entrypoint
    async def run(self) -> DailyResult:
        report: InboxScanReport = await workflows.execute_workflow(
            InboxScanWorkflow,
            params=InboxScanInput(
                window_days=1,
                include_today=False,  # yesterday, complete — never today's half day
                max_threads=_MAX_THREADS,
            ),
        )

        # Tidy up. The plan is deterministic (cleanup.py) and the execution is
        # shared with the conversation (apply.py) — nothing here decides
        # anything of its own.
        cleaned = await apply_cleanup(
            cleanup_plan(report.reviews),
            [u for u in report.unsub_links if is_mailto(u.url)],
            mode=config.SCHEDULE_CLEANUP,
        )

        # The dossier is named after the day it describes, not after the day it
        # was written: a re-run replaces its predecessor instead of doubling it,
        # and the library reads as a history rather than as a pile. The receipt
        # goes in with it — the morning after, "what did it touch" is the first
        # question, and the answer must not be only in the event history.
        day = report.window_start or date.fromisoformat(await get_today())
        stored = await store_dossier(
            name=f"inbox-context-{day.isoformat()}.md",
            text=dossier(report, day.isoformat(), cleaned=cleaned),
        )
        if stored.get("kept"):
            # Not an error, but not silence either: this run's findings are in
            # the execution, not in the library, and the reason matters.
            cleaned.errors.append(
                "Dossier NICHT ersetzt — das vorhandene ist ausführlicher. "
                "Ein zweiter Lauf desselben Tages sieht nur noch, was nach dem "
                "Aufräumen im Posteingang übrig war."
            )
        return DailyResult(report=report, cleaned=cleaned)
