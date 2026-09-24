"""Die Sprechstunde — der Sichtungs-Lauf als Gespräch in Le Chat und Vibe Work.

``inbox-scan`` ist stumm: Parameter rein, Report raus. Diese Hülle darum ist
der Ort, an dem man mit dem Ergebnis arbeitet. Sie fragt die Konfiguration im
Gespräch ab (kein Eingabeschema — Gotcha 11: sonst fällt Le Chat auf einen
rohen JSON-Editor zurück), zeigt den Fortschritt live in einer TodoList
(Gotcha 12: sie umschließt die GANZE Sitzung, sonst sieht sie niemand), lässt
den Scan als Kindworkflow laufen (eigene Historie, in Studio aufklappbar),
zeigt das Ergebnis im Canvas und legt das Dossier in die Library — der
Zustellweg, über den Vibe es in jeder Sitzung im Kontext hat.

  Konfiguration     Formular: Fenster · Zweitblick an/aus
    ↓  TodoList     konfigurieren → scannen → ergebnis → abos → abschluss
  inbox-scan        Kindworkflow mit der gewählten Konfiguration
    ↓  Canvas       der volle Report als Markdown-Dokument
  Abo-Ansicht       Abmeldelinks der gewählten Gruppe — zum Klicken
  inbox-senders    optional: die 90-Tage-Absenderstatistik (Kindworkflow)
    ↓  Library      Dossier „Inbox · Kontext, Stand <datum>" — Zustellweg für Vibe

Geschrieben wird in Gmail nichts — auch diese Sitzung ist ein Dry run. Labels
und Drafts sind die nächste Stufe mit eigener Freigabe.

Starten: in Le Chat / Vibe Work den Workflow wählen, oder
  make inbox-review
"""

from __future__ import annotations

from datetime import date, timedelta

import mistralai.workflows as workflows
import mistralai.workflows.plugins.mistralai as wf_mistral
from mistralai.workflows import workflow
from mistralai.workflows.plugins.mistralai.conversational_ui_components import (
    Markdown,
)

with workflow.unsafe.imports_passed_through():
    import mistralai.workflows.conversational as wf_chat
    from workflows.crm.agent_tools import get_today
    from workflows.inbox.gmail import (
        gmail_draft,
        gmail_ensure_label,
        gmail_process_thread,
    )
    from workflows.inbox.library import store_dossier

from workflows.crm.connectors import gmail_connector  # noqa: E402
from workflows.inbox.unsubscribe import ist_mailto  # noqa: E402
from workflows.inbox.senders import InboxSendersWorkflow  # noqa: E402
from workflows.inbox.cleanup import NOISE, cleanup_plan, cleanup_summary  # noqa: E402
from workflows.inbox.render import dossier, headline, report_as_markdown  # noqa: E402
from workflows.inbox.models import (  # noqa: E402
    SenderStats,
    CleanupResult,
    InboxScanInput,
    InboxScanReport,
)
from workflows.inbox.scan import InboxScanWorkflow  # noqa: E402
from workflows.inbox import config  # noqa: E402
from mistralai.workflows.plugins.mistralai.connectors import uses_connectors  # noqa: E402

# Das Fenster als Auswahl — die Erklärung steht in der Workflow-Beschreibung,
# nicht in der Auswahlzeile (im Dropdown wird sie abgeschnitten).
FENSTER = [("1", "Heute (1 Tag)"), ("3", "3 Tage"), ("7", "7 Tage")]
SECOND_REVIEW = [
    ("on", "Second review on (medium re-checks critical cases)"),
    ("off", "Second review off (small only — faster, unverified)"),
]

# Sichtungs-Obergrenze pro Lauf — im Fenster können deutlich mehr Threads
# liegen, als jemand sichten will.
LIMIT = [("25", "25 Mails"), ("50", "50 Mails"), ("100", "100 Mails")]


def _konfiguration() -> type[wf_chat.FormInput]:
    class Konfiguration(wf_chat.FormInput):
        fenster: str = wf_chat.SingleChoice(
            options=FENSTER, description="Welches Fenster?", prefilled_value="1"
        )
        second_review: str = wf_chat.SingleChoice(
            options=SECOND_REVIEW, description="Kaskade?", prefilled_value="on"
        )
        limit: str = wf_chat.SingleChoice(
            options=LIMIT, description="Höchstens so viele Mails sichten?", prefilled_value="50"
        )

    return Konfiguration


def _weiter() -> type[wf_chat.FormInput]:
    """Was nach dem Ergebnis? Eine Ansicht zur Zeit — kein Menü aus allem."""

    class Weiter(wf_chat.FormInput):
        wahl: str = wf_chat.SingleChoice(
            options=[
                ("abos", "Abbestell-Kandidaten ansehen"),
                ("statistik", "Absender-Statistik über 90 Tage"),
                ("fertig", "Fertig — Dossier ablegen"),
            ],
            description="Weiter?",
            prefilled_value="fertig",
        )

    return Weiter


def _abo_auswahl(report: InboxScanReport) -> type[wf_chat.FormInput]:
    gruppen = list(report.subscription_groups)[:20]

    class AboAuswahl(wf_chat.FormInput):
        gruppe: str = wf_chat.SingleChoice(
            options=[(g, f"{g} ({report.subscription_groups[g]})") for g in gruppen],
            description="Welche Gruppe?",
            prefilled_value=gruppen[0] if gruppen else "",
        )

    return AboAuswahl


def _markdown_nachricht(inhalt: str) -> list:
    """Eine Nachricht mit Markdown-Komponente — die Form aus book-editing."""
    return [
        wf_mistral.ResourceOutput(
            resource=wf_mistral.UIComponentResource(component=Markdown(content=inhalt))
        )
    ]


@workflows.workflow.define(
    name="inbox-review",
    on_behalf_of=True,  # der Kindworkflow (inbox-scan) braucht die Gmail-OAuth
    workflow_display_name="Inbox · Review (conversational)",
    workflow_description=(
        "Der Sichtungs-Lauf als Gespräch: Konfiguration im Chat wählen, "
        "inbox-scan läuft als Kindworkflow mit Fortschritt, das Ergebnis steht "
        "im Canvas, Abbestell-Links und Absender-Statistik sind eine Ansicht "
        "entfernt — und das Dossier für Vibe landet in der Library. "
        "Dry run — nichts wird in Gmail verändert."
    ),
)
@uses_connectors(gmail_connector)
class InboxReviewWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> wf_mistral.ChatAssistantWorkflowOutput:
        schritt = {
            "konfigurieren": wf_chat.TodoListItem(title="Konfiguration"),
            "scannen": wf_chat.TodoListItem(title="Sichtung laufen lassen"),
            "ergebnis": wf_chat.TodoListItem(title="Ergebnis & Ansichten"),
            "aufräumen": wf_chat.TodoListItem(title="Aufräumen (mit Freigabe)"),
            "abschluss": wf_chat.TodoListItem(title="Dossier in die Library"),
        }
        # Gotcha 12: Die TodoList umschließt die GANZE Sitzung, inklusive der
        # Wartezeiten auf Eingaben — sonst ist sie weg, bevor jemand hinsieht.
        async with wf_chat.TodoList(items=list(schritt.values())):
            return await self._sitzung(schritt)

    async def _sitzung(
        self, schritt: dict[str, wf_chat.TodoListItem]
    ) -> wf_mistral.ChatAssistantWorkflowOutput:
        # --- Konfiguration -----------------------------------------------
        async with schritt["konfigurieren"]:
            await wf_mistral.send_assistant_message(
                "Wie soll der Sichtungs-Lauf konfiguriert werden? Der Zweitblick "
                "(medium) prüft Antwortbedarf, Finanzen und Korrespondenz nach — "
                "ohne ihn sichtet nur der Erstblick (small)."
            )
            konfig = await self.wait_for_input(
                _konfiguration(), label="Fenster und Kaskade", timeout=timedelta(hours=8)
            )
            fenster = int(konfig.fenster)
            limit = int(konfig.limit)
            second_review = konfig.second_review == "on"

        # --- Scan als Kindworkflow ---------------------------------------
        async with schritt["scannen"]:
            roh = await workflows.workflow.execute_workflow(
                InboxScanWorkflow,
                params=InboxScanInput(
                    window_days=fenster, max_threads=limit, second_review=second_review
                ),
                execution_timeout=timedelta(minutes=15),
            )
            report = InboxScanReport.model_validate(
                roh if isinstance(roh, dict) else roh.model_dump()
            )

        # --- Ergebnis: Ansichten im Chat, alles im Canvas ----------------
        async with schritt["ergebnis"]:
            await wf_mistral.send_assistant_message(f"{headline(report)}")
            while True:
                wahl = await self.wait_for_input(
                    _weiter(), label="Ansicht", timeout=timedelta(hours=8)
                )
                if wahl.wahl == "abos":
                    await self._abos(report)
                elif wahl.wahl == "statistik":
                    await self._statistik()
                else:
                    break

        # --- Aufräumen: Stufe 2/3, NUR mit Freigabe pro Sitzung ----------
        async with schritt["aufräumen"]:
            aufgeraeumt = await self._aufräumen(report)

        # --- Abschluss: Dossier in die Library, Canvas als Gabe ----------
        async with schritt["abschluss"]:
            heute = date.fromisoformat(await get_today())
            ablage = await store_dossier(
                name=f"inbox-context-{heute.isoformat()}.md",
                text=dossier(report, heute.isoformat()),
            )

        inhalt: list = [
            wf_mistral.TextOutput(
                text=(
                    f"{headline(report)}\n\n"
                    + (
                        f"Aufgeräumt: {aufgeraeumt.archiviert} archiviert + gelesen, "
                        f"{aufgeraeumt.gelabelt_finanzen}× {config.LABELS['finance']}, "
                        f"{aufgeraeumt.gelabelt_antwort}× {config.LABELS['needs_reply']}, "
                        f"{aufgeraeumt.mailto_drafts} Abmeldungs-Draft(s).\n\n"
                        if aufgeraeumt.archiviert or aufgeraeumt.gelabelt_finanzen
                        or aufgeraeumt.gelabelt_antwort or aufgeraeumt.mailto_drafts
                        else ""
                    )
                    + f"Dossier abgelegt: **{ablage['name']}** — Vibe hat es "
                    "damit in jeder Sitzung im Kontext."
                )
            ),
            wf_mistral.ResourceOutput(
                resource=wf_mistral.CanvasResource(
                    uri=f"file://inbox/sichtung-{heute.isoformat()}",
                    readonly=True,
                    canvas=wf_mistral.CanvasPayload(
                        type="text/markdown",
                        title=f"Inbox · Sichtung ({fenster} Tage)",
                        content=report_as_markdown(report),
                    ),
                )
            ),
        ]
        return wf_mistral.ChatAssistantWorkflowOutput(
            content=inhalt,
            structuredContent={
                "report": report.model_dump(mode="json"),
                "aufgeraeumt": aufgeraeumt.model_dump(mode="json"),
            },
        )

    async def _aufräumen(self, report: InboxScanReport) -> CleanupResult:
        """Der Plan steht fest (deterministisch), die Freigabe kommt von dir.

        Stufe 2/3 der Sicherheitsleiter: Lärm archivieren + gelesen setzen,
        Finanzen/Antworten labeln (bleiben ungelesen), mailto-Abmeldungen als
        Draft. Ohne Freigabe passiert nichts — auch nicht teilweise.
        """
        plan = cleanup_plan(report.reviews)
        mailto = [u for u in report.unsub_links if ist_mailto(u.url)]
        vorschau = cleanup_summary(plan)
        if mailto:
            vorschau += f", {len(mailto)} Abmeldungs-Draft(s) vorbereiten"
        if vorschau == "nichts zu tun":
            await wf_mistral.send_assistant_message("Nichts aufzuräumen — das Fenster trägt.")
            return CleanupResult()

        await wf_mistral.send_assistant_message(
            f"Der Plan: {vorschau}. Gesendet wird nichts — Drafts und Labels nur."
        )
        wahl = await self.wait_for_input(
            wf_chat.ConfirmationInput(
                options=[
                    ("aufräumen", "Aufräumen wie geplant"),
                    ("nur_labeln", "Nur labeln — nichts archivieren"),
                    ("nichts", "Nichts verändern"),
                ],
                description="Aufräumen: freigeben?",
            ),
            label="Freigabe",
            timeout=timedelta(hours=8),
        )
        modus = getattr(wahl, "choice", None) or getattr(wahl, "value", "nichts")
        if modus == "nichts":
            return CleanupResult(skipped=len(plan))

        archivieren = modus == "aufräumen"
        # Die Namen stehen in shared/inbox.json, nicht hier (Goldregel 2) —
        # sonst laeuft der Plan gegen andere Labels als der Report behauptet.
        label_verarbeitet = await gmail_ensure_label(name=config.LABELS["processed"])
        label_finanzen = await gmail_ensure_label(name=config.LABELS["finance"])
        label_antwort = await gmail_ensure_label(name=config.LABELS["needs_reply"])

        ergebnis = CleanupResult()
        for a in plan:
            if a.aktion == "behalten" or not a.thread_id:
                ergebnis.skipped += 1
                continue
            if a.aktion == NOISE:
                await gmail_process_thread(
                    thread_id=a.thread_id, label_id=label_verarbeitet,
                    archivieren=archivieren, gelesen=archivieren,
                )
                ergebnis.archiviert += 1 if archivieren else 0
                ergebnis.gelesen += 1 if archivieren else 0
            elif a.aktion == "finanzen":
                await gmail_process_thread(
                    thread_id=a.thread_id, label_id=label_finanzen,
                    archivieren=False, gelesen=False,
                )
                ergebnis.gelabelt_finanzen += 1
            else:  # antwort
                await gmail_process_thread(
                    thread_id=a.thread_id, label_id=label_antwort,
                    archivieren=False, gelesen=False,
                )
                ergebnis.gelabelt_antwort += 1

        for u in mailto:
            await gmail_draft(
                to=u.url[7:],  # mailto: abschneiden
                subject="Abmeldung",
                body="Bitte nehmen Sie diese Adresse von allen Verteilern.",
            )
            ergebnis.mailto_drafts += 1
        return ergebnis

    async def _abos(self, report: InboxScanReport) -> None:
        """Abmeldelinks der gewählten Gruppe — zum Klicken, nicht zum Abschreiben."""
        if not report.subscription_groups:
            await wf_mistral.send_assistant_message("Keine Abo-Gruppen im Fenster.")
            return
        wahl = await self.wait_for_input(
            _abo_auswahl(report), label="Gruppe", timeout=timedelta(hours=8)
        )
        # Die Links gehören über den Absender zur Gruppe: Die Sichtung trägt
        # die Gruppe, der Link den Absender — beides kommt aus demselben Lauf.
        senders = {r.sender for r in report.reviews if r.review.subscription_group == wahl.gruppe}
        treffer = [u for u in report.unsub_links if u.sender in senders]
        z = [f"### {wahl.gruppe}", ""]
        if treffer:
            z += [f"- [{u.sender}]({u.url}) — *{u.subject}*" for u in treffer]
        else:
            z += [
                "Kein Abmeldelink für diese Gruppe im Fenster — entweder kein "
                "Newsletter dabei, oder der Linktext sagt nicht "
                "„Abmelden/unsubscribe“."
            ]
        await wf_mistral.send_assistant_message(_markdown_nachricht("\n".join(z)))

    async def _statistik(self) -> None:
        """Die 90-Tage-Absenderstatistik als Kindworkflow — reine Arithmetik."""
        roh = await workflows.workflow.execute_workflow(
            InboxSendersWorkflow,
            params={"window_days": 90, "max_threads": 4000},
            execution_timeout=timedelta(minutes=15),
        )
        stats = SenderStats.model_validate(
            roh if isinstance(roh, dict) else roh.model_dump()
        )
        z = [
            "### Absender über 90 Tage",
            f"{stats.threads} mails · {len(stats.senders)} senders · "
            f"{stats.unread_total} ungelesen",
            "",
        ]
        z += [
            f"- **{a.mails}** ({a.unread} ungelesen) — {a.sender}"
            for a in stats.senders[:15]
        ]
        z += [
            "",
            "_Scope: alles Empfangene, das dich erreicht (Spam und Trash wie "
            "von der Gmail-Suche standardmäßig ausgeschlossen)._",
        ]
        await wf_mistral.send_assistant_message(_markdown_nachricht("\n".join(z)))
