"""The consultation — the triage run as a conversation in Le Chat and Vibe Work.

``inbox-scan`` is mute: parameters in, report out. This shell around it is
where one works with the result. It asks for the configuration in the
conversation (no input schema — gotcha 11: otherwise Le Chat falls back to a
raw JSON editor), shows progress live in a TodoList (gotcha 12: it wraps the
WHOLE session, otherwise nobody sees it), runs the scan as a child workflow
(its own history, expandable in Studio), shows the result in a canvas and puts
the dossier into the library — the delivery route through which Vibe has it in
context in every session.

  configuration     form: window · second stage on/off
    ↓  TodoList     configure → scan → result → cleanup → finish
  inbox-scan        child workflow with the chosen configuration
    ↓  canvas       the full report as a Markdown document
  unsubscribe view  unsubscribe links of the chosen group — to click
  inbox-senders     optional: the 90-day sender statistic (child workflow)
    ↓  library      dossier "Inbox · Kontext, Stand <date>" — the route for Vibe

Writing to Gmail happens only behind the explicit approval in the cleanup step,
never silently. The connector cannot send at all.

The user-facing strings are German: the author reads them.

Start it by choosing the workflow in Le Chat / Vibe Work, or
  make inbox-review
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as wf_mistral
from mistralai.workflows import workflow
from mistralai.workflows.plugins.mistralai.conversational_ui_components import (
    Markdown,
)

with workflow.unsafe.imports_passed_through():
    from workflows.inbox.connectors import gmail_connector
    from workflows.inbox.cleanup import (
        cleanup_plan,
        cleanup_summary,
    )
    from workflows.inbox.models import (
        CleanupResult,
        InboxScanInput,
        InboxScanReport,
        SenderStats,
        SenderStatsInput,
    )
    from workflows.inbox.render import dossier, headline, report_as_markdown
    from workflows.inbox.scan import InboxScanWorkflow
    from workflows.inbox.senders import InboxSendersWorkflow
    from workflows.inbox.unsubscribe import is_mailto
    # Config modules read a JSON file at import. Inside the Temporal sandbox that
    # is a restricted call (pathlib.Path.read_text) and the WORKER REFUSES TO
    # START — 'Failed validating workflow …'. Whether it trips depends on import
    # order, so it can pass locally and kill the container. Passthrough, always —
# and as `import a.b.c as x`, never `from a.b import c`: the second form is an
# ATTRIBUTE access on the package and the sandbox bites anyway (gotcha 10).
    import workflows.inbox.config as config
    import mistralai.workflows.conversational as wf_chat
    from workflows.crm.agent_tools import get_today
    from workflows.inbox.apply import FULL, LABEL_ONLY, apply_cleanup
    from workflows.inbox.library import store_dossier

from mistralai.workflows.plugins.mistralai.connectors import uses_connectors  # noqa: E402


# Vibe renders the chosen VALUE in its summary card, not the option label. So
# the values are written to be readable on their own ("3 Tage", not "3") and
# parsed back below. The label carries the explanation, the value carries the
# answer — otherwise the card reads "Kaskade? on".
# The window is counted in CALENDAR days ending today — so "Nur heute" really
# means today, and two runs on the same choice cover the same ground. The
# labels say days, because that is what the window is.
WINDOWS = [
    ("Nur heute", "Nur heute"),
    ("Letzte 2 Tage", "Letzte 2 Tage — heute und gestern"),
    ("Letzte 7 Tage", "Letzte 7 Tage"),
]
SECOND_REVIEW = [
    (
        "Gründlich — zweite Prüfung",
        "Gründlich — wo eine Antwort oder eine Rechnung im Spiel ist, sieht ein "
        "zweites Modell noch mal hin",
    ),
    ("Schnell — ein Durchgang", "Schnell — ein Durchgang, ungeprüft"),
]
LIMITS = [("25 Mails", "25 Mails"), ("50 Mails", "50 Mails"), ("100 Mails", "100 Mails")]


def _days(choice: str) -> int:
    """'Nur heute' → 1, 'Letzte 7 Tage' → 7."""
    found = re.search(r"\d+", choice)
    return int(found.group()) if found else 1


def _count(choice: str) -> int:
    """'50 Mails' → 50."""
    found = re.search(r"\d+", choice)
    return int(found.group()) if found else 50


def _configuration() -> type[wf_chat.FormInput]:
    class Configuration(wf_chat.FormInput):
        window: str = wf_chat.SingleChoice(
            options=WINDOWS, description="Welcher Zeitraum?", prefilled_value="Nur heute"
        )
        second_review: str = wf_chat.SingleChoice(
            options=SECOND_REVIEW, description="Wie genau?", prefilled_value="Gründlich — zweite Prüfung"
        )
        limit: str = wf_chat.SingleChoice(
            options=LIMITS, description="Wie viele Mails höchstens?", prefilled_value="50 Mails"
        )

    return Configuration


def _next_view() -> type[wf_chat.FormInput]:
    """What after the result? One view at a time — not a menu of everything."""

    class NextView(wf_chat.FormInput):
        choice: str = wf_chat.SingleChoice(
            options=[
                ("Abbestell-Kandidaten", "Abbestell-Kandidaten ansehen"),
                ("Absender-Statistik", "Absender-Statistik über 90 Tage"),
                ("Fertig", "Fertig — Dossier ablegen"),
            ],
            description="Was als Nächstes?",
            prefilled_value="Fertig",
        )

    return NextView


def _group_choice(report: InboxScanReport) -> type[wf_chat.FormInput]:
    groups = list(report.subscription_groups)[:20]

    class GroupChoice(wf_chat.FormInput):
        group: str = wf_chat.SingleChoice(
            options=[(g, f"{g} ({report.subscription_groups[g]})") for g in groups],
            description="Absender-Gruppe",
            prefilled_value=groups[0] if groups else "",
        )

    return GroupChoice


def _markdown_message(content: str) -> list:
    """A message with a Markdown component — the shape from book-editing."""
    return [
        wf_mistral.ResourceOutput(
            resource=wf_mistral.UIComponentResource(component=Markdown(content=content))
        )
    ]


@workflows.workflow.define(
    name="inbox-review",
    on_behalf_of=False,  # the deployment's identity — see inbox/connectors.py
    workflow_display_name="Inbox · Review (conversational)",
    workflow_description=(
        "Der Sichtungs-Lauf als Gespräch: Konfiguration im Chat wählen, "
        "inbox-scan läuft als Kindworkflow mit Fortschritt, das Ergebnis steht "
        "im Canvas, Abbestell-Links und Absender-Statistik sind eine Ansicht "
        "entfernt — und das Dossier für Vibe landet in der Library. Aufgeräumt "
        "wird nur nach ausdrücklicher Freigabe; gesendet wird nie."
    ),
)
@uses_connectors(gmail_connector)
class InboxReviewWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> wf_mistral.ChatAssistantWorkflowOutput:
        # description is REQUIRED on TodoListItem (the SDK takes both positionally).
        # Without it the workflow dies at construction with a TypeError — before
        # the first form, so all Le Chat shows is "Workflow failed".
        step = {
            "configure": wf_chat.TodoListItem(
                title="Konfiguration", description="Fenster, Kaskade, Obergrenze"
            ),
            "scan": wf_chat.TodoListItem(
                title="Sichtung laufen lassen", description="inbox-scan als Kindworkflow"
            ),
            "result": wf_chat.TodoListItem(
                title="Ergebnis & Ansichten", description="Report, Abos, Absender-Statistik"
            ),
            "cleanup": wf_chat.TodoListItem(
                title="Aufräumen (mit Freigabe)", description="Labeln, archivieren, Entwürfe"
            ),
            "finish": wf_chat.TodoListItem(
                title="Dossier in die Library", description="Kontext für Vibe ablegen"
            ),
        }
        # Gotcha 12: the TodoList wraps the WHOLE session, waiting times for
        # input included — otherwise it is gone before anyone looks.
        async with wf_chat.TodoList(items=list(step.values())):
            return await self._session(step)

    async def _session(
        self, step: dict[str, wf_chat.TodoListItem]
    ) -> wf_mistral.ChatAssistantWorkflowOutput:
        # --- configuration ------------------------------------------------
        async with step["configure"]:
            await wf_mistral.send_assistant_message(
                "Wie soll der Sichtungs-Lauf konfiguriert werden? Der Zweitblick "
                "(medium) prüft Antwortbedarf, Finanzen und Korrespondenz nach — "
                "ohne ihn sichtet nur der Erstblick (small)."
            )
            chosen = await self.wait_for_input(
                _configuration(), label="Konfiguration", timeout=timedelta(hours=8)
            )
            window = _days(chosen.window)
            limit = _count(chosen.limit)
            second_review = chosen.second_review.startswith("Gründlich")

        # --- scan as a child workflow -------------------------------------
        async with step["scan"]:
            raw = await workflows.workflow.execute_workflow(
                InboxScanWorkflow,
                params=InboxScanInput(
                    window_days=window, max_threads=limit, second_review=second_review
                ),
                execution_timeout=timedelta(minutes=15),
            )
            report = InboxScanReport.model_validate(
                raw if isinstance(raw, dict) else raw.model_dump()
            )

        # --- result: views in the chat, everything in the canvas ----------
        async with step["result"]:
            await wf_mistral.send_assistant_message(f"{headline(report)}")
            while True:
                view = await self.wait_for_input(
                    _next_view(), label="Ansicht", timeout=timedelta(hours=8)
                )
                if view.choice == "Abbestell-Kandidaten":
                    await self._unsub_view(report)
                elif view.choice == "Absender-Statistik":
                    await self._sender_stats_view()
                else:
                    break

        # --- cleanup: level 2/3, ONLY with approval per session -----------
        async with step["cleanup"]:
            cleaned = await self._clean_up(report)

        # --- finish: dossier into the library, canvas as the parting gift --
        async with step["finish"]:
            today = date.fromisoformat(await get_today())
            stored = await store_dossier(
                name=f"inbox-context-{today.isoformat()}.md",
                # The receipt goes in here too — the conversation and the
                # nightly round must leave the same kind of document behind.
                text=dossier(report, today.isoformat(), cleaned=cleaned),
            )

        content: list = [
            wf_mistral.TextOutput(
                text=(
                    f"{headline(report)}\n\n"
                    + (
                        f"Aufgeräumt: {cleaned.archived} archiviert + gelesen, "
                        f"{cleaned.labelled_finance}× {config.LABELS['finance']}, "
                        f"{cleaned.labelled_reply}× {config.LABELS['needs_reply']}, "
                        f"{cleaned.mailto_drafts} Abmeldungs-Draft(s).\n\n"
                        if cleaned.archived or cleaned.labelled_finance
                        or cleaned.labelled_reply or cleaned.mailto_drafts
                        else ""
                    )
                    + f"Dossier abgelegt: **{stored['name']}** — Vibe hat es "
                    "damit in jeder Sitzung im Kontext."
                )
            ),
            wf_mistral.ResourceOutput(
                resource=wf_mistral.CanvasResource(
                    uri=f"file://inbox/triage-{today.isoformat()}",
                    readonly=True,
                    canvas=wf_mistral.CanvasPayload(
                        type="text/markdown",
                        title=f"Inbox · Sichtung ({window} Tage)",
                        content=report_as_markdown(report),
                    ),
                )
            ),
        ]
        return wf_mistral.ChatAssistantWorkflowOutput(
            content=content,
            structuredContent={
                "report": report.model_dump(mode="json"),
                "cleaned": cleaned.model_dump(mode="json"),
            },
        )

    async def _clean_up(self, report: InboxScanReport) -> CleanupResult:
        """The plan is fixed (deterministic), the approval comes from you.

        Level 2/3 of the safety ladder: archive noise and mark it read, label
        finance and replies (they stay unread), prepare mailto unsubscribes as
        drafts. Without approval nothing happens — not even partially.
        """
        plan = cleanup_plan(report.reviews)
        mailto = [u for u in report.unsub_links if is_mailto(u.url)]
        preview = cleanup_summary(plan, config.LABELS)
        if mailto:
            preview += f", {len(mailto)} Abmeldungs-Draft(s) vorbereiten"
        if preview == "nichts zu tun":
            await wf_mistral.send_assistant_message("Nichts aufzuräumen — das Fenster trägt.")
            return CleanupResult()

        await wf_mistral.send_assistant_message(
            f"Der Plan: {preview}. Gesendet wird nichts — Drafts und Labels nur."
        )
        answer = await self.wait_for_input(
            wf_chat.ConfirmationInput(
                options=[
                    ("clean", "Aufräumen wie geplant"),
                    ("label_only", "Nur labeln — nichts archivieren"),
                    ("nothing", "Nichts verändern"),
                ],
                description="Aufräumen: freigeben?",
            ),
            label="Freigabe",
            timeout=timedelta(hours=8),
        )
        mode = getattr(answer, "choice", None) or getattr(answer, "value", "nothing")
        if mode == "nothing":
            return CleanupResult(skipped=len(plan))

        # The plan runs through inbox/apply.py — the ONE place that changes the
        # mailbox, shared with the nightly round. If the conversation and the
        # night handled a thread differently, the mailbox would stop being
        # something one can reason about.
        result = await apply_cleanup(
            plan, mailto, mode=FULL if mode == "clean" else LABEL_ONLY
        )
        if result.errors:
            # The ACTUAL reason, never a guessed cause: the last two times this
            # failed the screen named a missing permission and it was, once, a
            # stale grant and, once, a label name Gmail reserves.
            await wf_mistral.send_assistant_message(
                f"Aufräumen ist fehlgeschlagen: {result.errors[0]} — nichts wurde "
                "verändert. Der Report und das Dossier stehen davon unberührt."
            )
        return result

    async def _unsub_view(self, report: InboxScanReport) -> None:
        """Unsubscribe links of the chosen group — to click, not to copy out."""
        if not report.subscription_groups:
            await wf_mistral.send_assistant_message("Keine Abo-Gruppen im Fenster.")
            return
        chosen = await self.wait_for_input(
            _group_choice(report), label="Gruppe", timeout=timedelta(hours=8)
        )
        # The links belong to the group through the sender: the review carries
        # the group, the link the sender — both come from the same run.
        senders = {
            r.sender for r in report.reviews if r.review.subscription_group == chosen.group
        }
        hits = [u for u in report.unsub_links if u.sender in senders]
        lines = [f"### {chosen.group}", ""]
        if hits:
            lines += [f"- [{u.sender}]({u.url}) — *{u.subject}*" for u in hits]
        else:
            lines += [
                "Kein Abmeldelink für diese Gruppe im Fenster — entweder kein "
                "Newsletter dabei, oder der Linktext sagt nicht "
                "„Abmelden/unsubscribe“."
            ]
        await wf_mistral.send_assistant_message(_markdown_message("\n".join(lines)))

    async def _sender_stats_view(self) -> None:
        """The 90-day sender statistic as a child workflow — pure arithmetic."""
        raw = await workflows.workflow.execute_workflow(
            InboxSendersWorkflow,
            # A Pydantic model, not a dict: the SDK serialises params with
            # .model_dump_json(), so a dict dies with AttributeError.
            params=SenderStatsInput(window_days=90, max_threads=4000),
            execution_timeout=timedelta(minutes=15),
        )
        stats = SenderStats.model_validate(
            raw if isinstance(raw, dict) else raw.model_dump()
        )
        lines = [
            "### Absender über 90 Tage",
            f"{stats.threads} Mails · {len(stats.senders)} Absender · "
            f"{stats.unread_total} ungelesen",
            "",
        ]
        lines += [
            f"- **{s.mails}** ({s.unread} ungelesen) — {s.sender}"
            for s in stats.senders[:15]
        ]
        lines += [
            "",
            "_Umfang: alles Empfangene, das dich erreicht (Spam und Trash sind "
            "von der Gmail-Suche standardmäßig ausgeschlossen)._",
        ]
        await wf_mistral.send_assistant_message(_markdown_message("\n".join(lines)))
