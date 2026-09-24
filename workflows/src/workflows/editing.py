"""The edit as a conversation — the workplace in Le Chat and Vibe Work.

The other book workflows are mute: text in, findings out. This one is the shell
around them, in which the work actually happens. It asks what to do, shows every
finding individually, collects the approval and records what was decided.

    list_sections()           chapters and sections from Scrivener
      ↓  form                 chapter · levels
      ↓  form                 section (filtered to the chapter)
    read_section()            paragraphs together with hashes
      ↓  TodoList             one line per level, live
    book-copyedit             child workflow, own history
      ↓  diff per finding     natively as search/replace, not as running text
      ↓  approval             all · one by one · skip
    apply level 1             before level 2 looks at the same text
    book-style                child workflow on the corrected text
      ↓  per finding          accept/reject, and on rejection: why
    canvas + EditingSession   the result, and the input for the write-back

**Why the levels run in sequence and are applied in between.** A style
suggestion that refers to a sentence still missing a comma no longer fits after
the correction — its ``search`` finds nothing. The alternative would be conflict
logic between overlapping changes. An extra pass is cheaper than that.

**Why child workflows and not activities.** Every level gets its own event
history: it retries independently, and in Studio it can be expanded on its own.
The same workflow also still runs headless from the CLI — the shell only adds
the conversation, not the logic.

**Why the rejection reasons are suggested.** A freely typed reason is anecdote.
Four suggestions plus a free field yield a signal that can be counted — and that
is exactly what later becomes the acceptance rate per voice-profile rule.

Nothing is written here. The session ends with ``EditingSession``; writing back
into the manuscript is a separate, guarded step.

The user-facing strings are German: the author reads them.

Start it by choosing the workflow in Le Chat, or
  make book-editing work=immer-wieder-ruegen
"""

from __future__ import annotations

import re
from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    import mistralai.workflows.plugins.mistralai as wf_mistral
    from workflows.book.local import (
        claim_section,
        list_sections,
        list_works,
        load_voice_profile,
        read_section,
        release_section,
        write_decisions,
    )

import mistralai.workflows.conversational as wf_chat  # noqa: E402
from mistralai.workflows.plugins.mistralai.conversational_ui_components import (  # noqa: E402
    Alert,
    Markdown,
)

from workflows.book.models import (  # noqa: E402
    Decision,
    EditingInput,
    EditingResult,
    EditingSession,
    SectionInput,
)
from workflows.book.copyedit import BookCopyeditWorkflow  # noqa: E402
from workflows.book.style import BookStyleWorkflow  # noqa: E402

# The same display as in ``book-overview`` — imported, not rebuilt. One does not
# pick a section from a list of 48 titles but because one knows where the book
# is thin.
from workflows.overview import button_label, outliner  # noqa: E402

# Suggested rejection reasons. Deliberately short and in his words — a
# suggestion you tap gets used; an empty text field does not.
REJECTION_REASONS = [
    "klingt nicht nach mir",
    "verändert die Bedeutung",
    "zu glatt",
    "die Wiederholung ist Absicht",
    "stimmt sachlich nicht",
]

# Short labels. The explanation belongs in the workflow description, not in
# every option line — in the dropdown it gets truncated and helps nobody.
LEVELS = [("copyedit", "Korrektorat"), ("style", "Stil")]

# Ceilings per level — deliberately not a setting in the form.
#
# For COPYEDIT a limit would be harmful: it simply truncates the list, and on a
# section with fifteen comma errors three vanish silently. An error nobody
# reports is worse than a long list. Hence 99 — practically no limit, but a
# guard against an agent going haywire.
#
# For STYLE the limit is a decision: the voice profile has at most twelve rules,
# and nobody works through more than a handful of suggestions in one go.
MAX_FINDINGS = {"copyedit": 99, "style": 12}


def _work_choice(works: list[tuple[str, str]]) -> type[wf_chat.FormInput]:
    class WorkChoice(wf_chat.FormInput):
        work: str = wf_chat.SingleChoice(
            options=works, description="An welchem Buch?", prefilled_value=works[0][0]
        )

    return WorkChoice


def _selection(options: list[tuple[str, str]]) -> type[wf_chat.FormInput]:
    """Section and levels in ONE form.

    The documentation is unambiguous: there is no table component, and no row
    can be made selectable in itself. ``SingleChoice`` is a dropdown,
    ``ConfirmationInput`` are buttons — nothing else is available. So: the table
    to scan, below it **one** form. A row of buttons repeating every table row
    is no advance over the dropdown, just the same list twice.
    """

    class Selection(wf_chat.FormInput):
        uuid: str = wf_chat.SingleChoice(
            options=options,
            description="Abschnitt",
            prefilled_value=options[0][0],
        )
        levels: list[str] = wf_chat.MultiChoice(
            options=LEVELS,
            description="Ebenen",
            prefilled_value=["copyedit"],
        )
    return Selection


def _diff_task(
    title: str, uuid: str, text: str, findings: list[dict]
) -> wf_chat.ChatAssistantWorkingTask:
    """Findings as a native search/replace diff.

    Le Chat renders ``FileToolUIState`` with ``ReplaceFileOperation`` as a
    code-review view: before and after beneath each other, the change marked.
    The same findings as running text would be a wall of quotation marks — and
    the difference between „Die" and „Sie" invisible inside it.
    """
    return wf_chat.ChatAssistantWorkingTask(
        type="tool",
        title=title,
        content=f"{len(findings)} Befund(e)",
        toolUIState=wf_chat.FileToolUIState(
            toolCallId=uuid,
            operations=[
                wf_chat.ReplaceFileOperation(
                    uri=f"file://section/{uuid}",
                    fileContentBefore=text,
                    blocks=[
                        wf_chat.SearchReplaceBlock(search=f["search"], replace=f["replace"])
                        for f in findings
                    ],
                )
            ],
        ),
    )


# Sentence boundaries. Deliberately coarse: abbreviations like „z. B." split
# wrongly here, but one sentence too many does no harm — one too few does.
_BOUNDARY = re.compile(r"(?<=[.!?…])[\s ]+(?=[„\"'(A-ZÄÖÜ])")


def _sentence_around(paragraph: str, search: str) -> tuple[str, int, int]:
    """The whole sentence containing ``search`` — plus its position within it.

    A finding shows only what changes: „wenn" → „wenn,". That cannot be judged.
    Only the surrounding sentence makes it visible whether the comma belongs
    there. If the search text is not found, the whole paragraph comes back —
    better too much context than none.
    """
    at = paragraph.find(search)
    if at < 0:
        return paragraph, -1, -1
    start = 0
    for m in _BOUNDARY.finditer(paragraph):
        if m.end() > at:
            break
        start = m.end()
    end = len(paragraph)
    for m in _BOUNDARY.finditer(paragraph):
        if m.start() >= at + len(search):
            end = m.start()
            break
    return paragraph[start:end].strip(), at - start, at - start + len(search)


def _before_after(paragraphs: list[str], f: dict) -> str:
    """The sentence before and after the change, the change itself highlighted."""
    i = f.get("paragraph_index", 0)
    if not 0 <= i < len(paragraphs):
        return f"− {f['search']}\n+ {f['replace']}"
    sentence, a, e = _sentence_around(paragraphs[i], f["search"])
    if a < 0:
        return f"> {sentence}\n\n− {f['search']}\n+ {f['replace']}"
    return (
        f"> {sentence[:a]}**{sentence[a:e]}**{sentence[e:]}\n\n"
        f"> {sentence[:a]}**{f['replace']}**{sentence[e:]}"
    )


def _listing(findings: list[dict], paragraphs: list[str]) -> str:
    lines = []
    for i, f in enumerate(findings, start=1):
        head = f"**{i}.** `{f['kind']}`  ·  Absatz {f.get('paragraph_index', 0)}"
        if f.get("rule_id"):
            head += f" · {f['rule_id']}"
        lines += [head, "", _before_after(paragraphs, f), "", f"_{f.get('why', '')}_", ""]
    return "\n".join(lines)


def _apply(paragraphs: list[str], decisions: list[Decision]) -> tuple[list[str], list[str]]:
    """Apply accepted findings to the paragraphs — in memory, not on disk.

    The same strictness as when writing into the manuscript later: the search
    text has to occur exactly once. No fuzzy matching. Whatever does not match
    unambiguously is reported and skipped instead of guessed.
    """
    updated = list(paragraphs)
    notes: list[str] = []
    for d in decisions:
        if d.decision != "angenommen":
            continue
        if not 0 <= d.paragraph_index < len(updated):
            notes.append(f"Absatz {d.paragraph_index} gibt es nicht — {d.search!r} übersprungen.")
            continue
        if d.own_version:
            # The author's version replaces the whole paragraph. Further
            # findings on the same paragraph will mostly grasp at nothing
            # afterwards — and rightly so: he rewrote the paragraph, he did not
            # patch it.
            updated[d.paragraph_index] = d.own_version
            continue
        hits = updated[d.paragraph_index].count(d.search)
        if hits != 1:
            notes.append(
                f"{d.search!r} kommt in Absatz {d.paragraph_index} {hits}-mal vor — übersprungen."
            )
            continue
        updated[d.paragraph_index] = updated[d.paragraph_index].replace(d.search, d.replace, 1)
    return updated, notes


@workflows.workflow.define(
    name="book-editing",
    workflow_display_name="Book · Editing (conversational)",
    workflow_description=(
        "Lektoriert einen Abschnitt im Dialog: Kapitel und Ebenen wählen, Befunde als Diff "
        "ansehen, einzeln freigeben oder ablehnen. Schreibt nichts ins Manuskript — das "
        "Ergebnis ist eine Sitzung, die man danach anwenden kann."
    ),
    execution_timeout=timedelta(hours=12),
    # No search_keys: they exist only as paths into the ENTRYPOINT INPUT, and
    # this workflow deliberately has none (see run()). A runtime API to add them
    # later does not exist in the SDK — checked, not assumed. Sessions are found
    # through the decision log, which carries work, section and session ID on
    # every line.
)
class BookEditingWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> wf_mistral.ChatAssistantWorkflowOutput:
        # NO input parameter. It took three attempts before starting it in Le
        # Chat stopped being annoying:
        #   1. model with an extra field ``werk``   -> raw JSON editor
        #   2. ``message`` with a default            -> JSON editor as well
        #   3. ``message`` as a required field       -> Le Chat asks for the
        #      typed message a SECOND time
        # The workflow does not need the message — everything necessary is asked
        # through forms. Without an input schema there is nothing to ask, and
        # the workflow starts immediately.
        #
        # The progress list comes FIRST, with every step that can follow — the
        # two selection steps included. Creating it only after the selection was
        # a bad trade: at the start one knows least about where one is, and that
        # was exactly when the field was empty. If a level is not chosen, its two
        # entries stay open — that is the truth and reads like it.
        step = {
            "work": wf_chat.TodoListItem(
                title="Buch wählen", description="Welches Manuskript"
            ),
            "selection": wf_chat.TodoListItem(
                title="Abschnitt und Ebenen wählen", description="Aus der Gliederung"
            ),
            "copyedit_check": wf_chat.TodoListItem(
                title="Korrektorat prüfen",
                description="Rechtschreibung, Zeichensetzung, Grammatik — dann gegenlesen",
            ),
            "copyedit_approve": wf_chat.TodoListItem(
                title="Korrektorat freigeben", description="Befunde übernehmen oder ablehnen"
            ),
            "style_check": wf_chat.TodoListItem(
                title="Stil prüfen", description="Gegen das Stimmprofil, mit Regelbezug"
            ),
            "style_approve": wf_chat.TodoListItem(
                title="Stil freigeben", description="Vorschläge übernehmen oder ablehnen"
            ),
            "finish": wf_chat.TodoListItem(
                title="Sitzung abschließen",
                description="Text zusammensetzen, Entscheidungen sichern",
            ),
        }
        async with wf_chat.TodoList(items=list(step.values())):
            return await self._session(step)

    async def _session(
        self, step: dict[str, wf_chat.TodoListItem]
    ) -> wf_mistral.ChatAssistantWorkflowOutput:
        """The session proper — extracted so the TodoList can wrap it."""
        works = await list_works()
        if not works:
            return wf_mistral.ChatAssistantWorkflowOutput(
                content=[wf_mistral.TextOutput(text="Kein Werk in `shared/book/` gefunden.")],
                isError=True,
            )
        await step["work"].set_status("in_progress")
        if len(works) == 1:
            work = works[0]["slug"]
        else:
            # Only ask when there is something to choose. A form with a single
            # option is a delay, not a choice.
            chosen = await self.wait_for_input(
                _work_choice([(w["slug"], w["title"]) for w in works]),
                label="Werk",
                timeout=timedelta(hours=8),
            )
            work = chosen.work
        await step["work"].set_status("done")

        catalogue = await list_sections(work)
        everything = catalogue["sections"]

        if not everything:
            return wf_mistral.ChatAssistantWorkflowOutput(
                content=[wf_mistral.TextOutput(text=f"In {work!r} steht noch kein Text.")],
                isError=True,
            )

        async with step["selection"]:
            uuid, levels = await self._choose(catalogue, everything)

        section = await read_section(work, uuid)
        # One identifier per session, replay-safe from the workflow's own
        # randomness. `workflow.info()` does not exist in Mistral's wrapper —
        # that is temporalio, and the call made the activation fail with an
        # AttributeError, silently, after the first approval.
        session_id = str(workflow.uuid4())

        # Is someone already working on this section? Warn, do not block — see
        # claim_section(). The lock is cleared again at the end.
        warning = await claim_section(work, uuid, session_id, section["title"])
        if warning:
            await wf_mistral.send_assistant_message(
                [
                    wf_mistral.ResourceOutput(
                        resource=wf_mistral.UIComponentResource(
                            component=Alert(variant="warning", title="Zweite Sitzung",
                                            children=warning)
                        )
                    )
                ]
            )

        paragraphs: list[str] = list(section["paragraphs"])
        hashes: list[str] = list(section["hashes"])
        session = EditingSession(
            work=work,
            section_uuid=section["uuid"],
            section_title=section["title"],
            levels=levels,
            text_before="\n\n".join(paragraphs),
        )

        voice_profile = await load_voice_profile(work) if "style" in levels else ""
        if "style" in levels and not voice_profile:
            levels = [level for level in levels if level != "style"]
            session.notes.append(
                "Ohne Stimmprofil wäre die Stilebene generische Stilkritik — übersprungen. "
                "Erst `make book-voiceprofile` laufen lassen."
            )

        for level in levels:
            async with step[f"{level}_check"]:
                payload = EditingInput(
                    work=work,
                    section=SectionInput(
                        uuid=section["uuid"],
                        title=section["title"],
                        text="\n\n".join(paragraphs),
                        path=section.get("path") or [],
                    ),
                    paragraphs=paragraphs,
                    voice_profile_text=voice_profile if level == "style" else "",
                    max_findings=MAX_FINDINGS[level],
                )
                raw = await workflows.workflow.execute_workflow(
                    BookCopyeditWorkflow if level == "copyedit" else BookStyleWorkflow,
                    params=payload,
                    execution_timeout=timedelta(minutes=15),
                )
                result = EditingResult.model_validate(
                    raw if isinstance(raw, dict) else raw.model_dump()
                )

            async with step[f"{level}_approve"]:
                try:
                    decisions = await self._walk_through(
                        level, result, paragraphs, hashes, section
                    )
                except TimeoutError:
                    # The author is gone. What was decided up to here is already
                    # in the log (see below) — the session ends as a partial
                    # session instead of a loss.
                    session.aborted = True
                    session.notes.append(
                        f"{level}: Zeitüberschreitung beim Warten auf Freigaben — "
                        "Sitzung als Teilsitzung beendet."
                    )
                    break
            session.decisions += decisions
            session.notes += result.notes

            # STRAIGHT into the log, not only at the end. If something aborts
            # afterwards, these decisions are still there. The log is the
            # capital of the system — every tapped rejection reason is a data
            # point for the voice profile, and up to here it was simply thrown
            # away when the chat was closed.
            if decisions:
                await write_decisions(
                    work=work,
                    section=section,
                    session_id=session_id,
                    decisions=[d.model_dump(mode="json") for d in decisions],
                )

            # Apply level 1 BEFORE level 2 sees the same text.
            paragraphs, notes = _apply(paragraphs, decisions)
            session.notes += notes

        async with step["finish"]:
            session.text_after = "\n\n".join(paragraphs)
            output = self._finish(session)
            await release_section(work, uuid, session_id)
        return output

    # ------------------------------------------------------------------
    async def _choose(
        self, catalogue: dict, everything: list[dict]
    ) -> tuple[str, list[str]]:
        """A table to scan, one form to choose from.

        Key figures and two pie charts used to stand here. They pushed the
        choice two screens down and answered a question nobody asks at this
        point. Whoever wants to know how far the book is calls ``book-overview``.
        """
        await wf_mistral.send_assistant_message(
            [
                wf_mistral.TextOutput(text=f"**{catalogue['title']}**"),
                wf_mistral.ResourceOutput(
                    resource=wf_mistral.UIComponentResource(
                        component=Markdown(content=outliner(everything, with_chapters=True))
                    )
                ),
            ]
        )
        choice = await self.wait_for_input(
            _selection([(s["uuid"], button_label(s)) for s in everything]),
            label="Abschnitt und Ebenen",
            timeout=timedelta(hours=8),
        )
        levels = [lv for lv, _ in LEVELS if lv in (choice.levels or [])] or ["copyedit"]
        return choice.uuid, levels

    # ------------------------------------------------------------------
    async def _walk_through(
        self,
        level: str,
        result: EditingResult,
        paragraphs: list[str],
        hashes: list[str],
        section: dict,
    ) -> list[Decision]:
        """Show a level's findings and collect the approvals."""
        findings = [f.model_dump(mode="json") for f in result.findings]
        name = "Korrektorat" if level == "copyedit" else "Stil"

        if result.blocked:
            await wf_mistral.send_assistant_message(
                f"**{name}:** {len(result.blocked)} Vorschlag/Vorschläge hat das Gegenlesen "
                "zurückgehalten, bevor sie dich erreicht haben:\n\n"
                + "\n".join(f"- `{f.search}` — {f.block_reason}" for f in result.blocked)
            )

        if not findings:
            await wf_mistral.send_assistant_message(
                f"**{name}:** keine Befunde. Der Abschnitt trägt."
            )
            return []

        # The diff first, then the list: the picture before the reasoning.
        async with wf_chat.Task[wf_chat.ChatAssistantWorkingTask](
            type="working",
            state=_diff_task(
                f"{name} · {section['title']}",
                section["uuid"],
                "\n\n".join(paragraphs),
                findings,
            ),
        ):
            pass

        by_kind = " · ".join(f"{n}× {kind}" for kind, n in sorted(result.by_kind.items()))
        await wf_mistral.send_assistant_message(
            f"**{name} — {len(findings)} Befund(e)**  ({by_kind})\n\n"
            + _listing(findings, paragraphs)
        )

        how = await self.wait_for_input(
            wf_chat.ConfirmationInput(
                options=[
                    ("all", f"Alle {len(findings)} übernehmen"),
                    ("one_by_one", "Einzeln durchgehen"),
                    ("skip", "Diese Ebene überspringen"),
                ],
                description=f"{name}: wie willst du damit umgehen?",
            ),
            label=f"{name} — Freigabe",
            timeout=timedelta(hours=8),
        )
        mode = getattr(how, "choice", None) or getattr(how, "value", "one_by_one")

        def build(f: dict, decision: str, reason: str = "") -> Decision:
            i = f["paragraph_index"]
            return Decision(
                level=level,
                paragraph_index=i,
                paragraph_hash=hashes[i] if 0 <= i < len(hashes) else "",
                search=f["search"],
                replace=f["replace"],
                kind=f["kind"],
                why=f.get("why", ""),
                rule_id=f.get("rule_id"),
                decision=decision,
                reason=reason,
            )

        if mode == "all":
            return [build(f, "angenommen") for f in findings]
        if mode == "skip":
            return [build(f, "zurueckgestellt") for f in findings]

        decisions: list[Decision] = []
        for i, f in enumerate(findings, start=1):
            answer = await self.wait_for_input(
                wf_chat.ConfirmationInput(
                    options=[
                        ("accept", "Übernehmen"),
                        ("own", "Selbst formulieren"),
                        ("reject", "Ablehnen"),
                    ],
                    description=(
                        f"**{i}/{len(findings)}** · `{f['kind']}` · Absatz {f['paragraph_index']}"
                        + (f" · {f['rule_id']}" if f.get("rule_id") else "")
                        + "\n\n"
                        + _before_after(paragraphs, f)
                        + f"\n\n_{f.get('why', '')}_"
                    ),
                ),
                label=f"{name} {i}/{len(findings)}",
                timeout=timedelta(hours=8),
            )
            choice = getattr(answer, "choice", "reject")

            if choice == "accept":
                decisions.append(build(f, "angenommen"))
                continue

            if choice == "own":
                # The most valuable outcome: the author accepts the idea and
                # words it himself. That pair — suggestion and his version — was
                # produced by no model, and it goes into the log as such. The
                # canvas shows the paragraph WITH the suggestion applied,
                # because that is the starting point, not the original.
                idx = f["paragraph_index"]
                if 0 <= idx < len(paragraphs):
                    template = paragraphs[idx].replace(f["search"], f["replace"], 1)
                    uri = f"file://canvas/{section['uuid']}/{idx}/{i}"
                    await wf_mistral.send_assistant_message(
                        "Formuliere den Absatz so, wie du ihn haben willst, und schick ihn zurück.",
                        canvas=wf_mistral.CanvasResource(
                            uri=uri,
                            canvas=wf_mistral.CanvasPayload(
                                type="text/markdown",
                                title=f"Absatz {idx} — deine Fassung",
                                content=template,
                            ),
                        ),
                    )
                    own = await self.wait_for_input(
                        wf_chat.CanvasInput(uri),
                        label=f"{name} {i}/{len(findings)} — eigene Fassung",
                        timeout=timedelta(hours=8),
                    )
                    version = own.canvas.content.strip()
                    decision = build(f, "angenommen")
                    if version and version != template:
                        decision.own_version = version
                    decisions.append(decision)
                    continue

            # The reason is this session's yield — which is why it is asked, and
            # why it stands there as a suggestion rather than an empty field.
            why = await self.wait_for_input(
                wf_chat.ChatInput(
                    "Warum nicht? (antippen oder frei schreiben)",
                    suggestions=[[wf_chat.TextChunk(text=r)] for r in REJECTION_REASONS],
                ),
                label=f"{name} {i}/{len(findings)} — Grund",
                timeout=timedelta(hours=8),
            )
            decisions.append(
                build(f, "abgelehnt", " ".join(c.text for c in why.message).strip())
            )
        return decisions

    # ------------------------------------------------------------------
    def _finish(self, s: EditingSession) -> wf_mistral.ChatAssistantWorkflowOutput:
        """Canvas with the result, plus the session as structured output."""
        yes = len(s.accepted)
        no = len([d for d in s.decisions if d.decision == "abgelehnt"])
        open_ = len([d for d in s.decisions if d.decision == "zurueckgestellt"])

        head = [f"**{s.section_title}** — {yes} übernommen"]
        if no:
            head.append(f"{no} abgelehnt")
        if open_:
            head.append(f"{open_} zurückgestellt")
        text = ", ".join(head)
        if s.notes:
            # Reported separately: what stands here never reached him — these
            # are suggestions that failed the invariants or the second read. In
            # one list with his own decisions it reads like a mistake he made.
            text += (
                "\n\n_Vorher automatisch aussortiert, ohne dass du sie zu sehen "
                "bekamst:_\n"
                + "\n".join(f"- {n}" for n in s.notes)
            )
        if yes:
            text += (
                "\n\nDas Manuskript ist unverändert. Zum Anwenden: "
                f"`make book-apply work={s.work} uuid={s.section_uuid[:8]}`"
            )

        content: list = [wf_mistral.TextOutput(text=text)]
        if yes:
            content.append(
                wf_mistral.ResourceOutput(
                    resource=wf_mistral.CanvasResource(
                        uri=f"file://canvas/{s.section_uuid}",
                        readonly=True,
                        canvas=wf_mistral.CanvasPayload(
                            type="text/markdown",
                            title=f"{s.section_title} — lektoriert",
                            content=s.text_after,
                        ),
                    )
                )
            )
        return wf_mistral.ChatAssistantWorkflowOutput(
            content=content,
            structuredContent=s.model_dump(mode="json"),
        )
