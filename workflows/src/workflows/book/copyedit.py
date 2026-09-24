"""Level 1 of the edit — copyediting ONE section, on the four-eyes principle.

Spelling, punctuation, grammar, tense, typography. Style is not touched; that is
what ``book-style`` is for.

    copyedit()        findings of the first stage
      ↓
    invariants        index, non-findings, character speech — deterministic, no model
      ↓
    second_read()     second pair of eyes on THE SAME section: what is missing, what is not a finding
      ↓
    done

**Why the second pair of eyes sees the whole section.** Its predecessor was a
judge that ran per finding and received only ``search`` and ``replace`` — a
snippet without the sentence it sits in. It therefore could not do two things:
judge whether an error is really fixed, and notice that one is missing. The
second was the graver defect: at zero findings it never even started, so a
missed error was invisible. A reviewer who sees only the first reader's
suggestions does not review that reader's work, only their word choice.

**Why there is no feedback loop.** An earlier version handed rejected findings
back to the agent. Measured, that did harm: it took "narrow it down" literally
and reduced findings into meaninglessness instead of withdrawing them. What the
second pair of eyes discards is now discarded; what it finds is added. Both
without a second round.

**Why the control structure lives here and not in the agent.** Mistral knows
``handoffs`` — but there the *agent* decides whether to hand off. That is right
for a division of labour and wrong for a QA gate: there would be no fixed order
and no access to the intermediate states. This way every step is in the event
history.

Trigger with:
  make book-copyedit section="Einführung Strand"
"""

from __future__ import annotations

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    from workflows.book.checks import (
        drop_duplicates,
        drop_edits_in_speech,
        drop_intentional_colloquialisms,
        drop_non_findings,
        fix_paragraph_index,
        split_blocked,
        work_context,
    )
    from workflows.book.models import (
        Corrections,
        EditingInput,
        EditingResult,
        JudgedFinding,
        SecondRead,
    )
    import workflows.book.config as config
    from workflows.book.agents import copyedit, second_read


def _to_findings(raw: dict, limit: int) -> list[JudgedFinding]:
    # Validate only the payload field: the activity may put extras alongside it,
    # and Corrections forbids extra fields.
    raw = {"corrections": raw.get("corrections", [])}
    return [
        JudgedFinding(
            level="copyedit",
            paragraph_index=c.paragraph_index,
            search=c.search,
            replace=c.replace,
            kind=c.kind,
            why=c.why,
            confidence=c.confidence,
        )
        for c in Corrections.model_validate(raw).corrections[:limit]
    ]


def _invariants(
    findings: list[JudgedFinding], paragraphs: list[str]
) -> tuple[list[JudgedFinding], list[str]]:
    """Checks without discretion — cheap, absolute, before every model call.

    Deliberately separate from what the second pair of eyes judges: whether a
    search text can be located unambiguously is a fact. Whether a correction is
    warranted is a judgement.
    """
    notes: list[str] = []
    findings, n = fix_paragraph_index(findings, paragraphs)
    notes += n
    findings, n = drop_duplicates(findings)
    notes += n
    findings, n = drop_non_findings(findings)
    notes += n
    findings, n = drop_edits_in_speech(findings, paragraphs)
    notes += n
    findings, n = drop_intentional_colloquialisms(findings)
    notes += n
    return findings, notes


def _apply_second_read(
    findings: list[JudgedFinding], review: SecondRead
) -> tuple[list[JudgedFinding], list[str]]:
    """Record the second pair of eyes' verdict.

    Discarded findings are blocked, not deleted — they appear in the result
    under ``blocked`` with a reason. Only that makes it possible to evaluate
    later whether the second pair of eyes is too strict.
    """
    notes: list[str] = []

    for u in review.unfounded:
        i = u.number - 1
        if 0 <= i < len(findings):
            findings[i].blocked = True
            findings[i].block_reason = f"second read: {u.why}"
        else:
            notes.append(f"Second read points at finding {u.number}, which does not exist.")

    for m in review.missed:
        findings.append(
            JudgedFinding(
                level="copyedit",
                paragraph_index=m.paragraph_index,
                search=m.search,
                replace=m.replace,
                kind=m.kind,
                why=f"[added by the second read] {m.why}",
            )
        )
    if review.missed:
        notes.append(f"Second read added {len(review.missed)} missed error(s).")
    return findings, notes


@workflows.workflow.define(
    name="book-copyedit",
    workflow_display_name="Book · Copyedit (level 1)",
    workflow_description=(
        "Prüft einen Abschnitt auf Rechtschreibung, Zeichensetzung, Grammatik, Tempus und "
        "Typografie. Ein zweites Augenpaar liest denselben Abschnitt gegen und meldet, was "
        "fehlt und was kein Befund ist — auch dann, wenn die erste Stufe nichts gefunden hat."
    ),
    # Searchable in Studio by work and section — "what had I already seen on
    # this section?" is otherwise scrolling through the timeline. Identifiers
    # and titles only, no text: search_keys are stored UNENCRYPTED.
    search_keys=["work", "section.uuid", "section.title"],
)
class BookCopyeditWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: EditingInput) -> EditingResult:
        paragraphs = inp.paragraphs or [inp.section.text]
        notes: list[str] = []

        raw = await copyedit(title=inp.section.title, paragraphs=paragraphs)
        findings = _to_findings(raw, inp.max_findings)

        findings, n = _invariants(findings, paragraphs)
        notes += n

        # The second pair of eyes ALWAYS runs — the empty finding list is
        # precisely the case nobody else checks.
        if inp.with_second_read and config.AGENTS.get("second_read"):
            raw_review = await second_read(
                title=inp.section.title,
                paragraphs=paragraphs,
                findings=[f.model_dump(mode="json") for f in findings],
                context=work_context("berechtigung"),
            )
            findings, n = _apply_second_read(findings, SecondRead.model_validate(raw_review))
            notes += n
            # Added findings through the invariants once more: the second pair
            # of eyes can mistype a search text too.
            findings, n = _invariants(findings, paragraphs)
            notes += n
        elif inp.with_second_read:
            notes.append("Ohne Gegenlesen: keine Agent-ID in shared/book.json.")

        shown, blocked = split_blocked(findings)
        return EditingResult(
            work=inp.work,
            section_uuid=inp.section.uuid,
            section_title=inp.section.title,
            level="copyedit",
            findings=shown,
            blocked=blocked,
            notes=notes,
        )
