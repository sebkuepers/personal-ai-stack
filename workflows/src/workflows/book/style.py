"""Level 2 of the edit — style for ONE section.

The brief is not to make the text better but to make it **more like the
author**. Smoothing and standardising is exactly what does harm here. So this
workflow works against the voice profile and discards everything that cannot
cite one of its rules.

Two filters in sequence, both in deterministic code:

1. **Rule reference** — a suggestion without a valid ``rule_id`` is dropped,
   except at severity „hoch". Without this filter the agent cites the profile
   decoratively at best.
2. **Second read** — a second pair of eyes with exactly one question per
   suggestion: does it deliver what its rule promises? Measured over seven cases
   taken from real bad suggestions: of ten suggestions, five rightly failed, and
   the three about a genuine break of voice stayed.

   It deliberately does NOT ask whether something is missing — unlike level 1. A
   missed style lapse costs nothing; an imposed suggestion costs the author his
   voice. That is not a symmetric trade.

Trigger with:
  make book-style work=immer-wieder-ruegen uuid=<section-uuid>
"""

from __future__ import annotations

import re

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    from workflows.book.checks import (
        drop_duplicates,
        drop_without_rule,
        fix_paragraph_index,
        split_blocked,
    )
    from workflows.book.models import (
        EditingInput,
        EditingResult,
        JudgedFinding,
        StyleSecondRead,
        StyleSuggestions,
    )
    import workflows.book.config as config
    from workflows.book.agents import check_style, second_read_style


# Rule IDs in the rendered profile sit as "[R-...]" at the start of a line.
_RULE_ID = re.compile(r"^\[(R-[a-zA-Z0-9-]+)\]", re.M)


@workflows.workflow.define(
    name="book-style",
    workflow_display_name="Book · Style (level 2)",
    workflow_description=(
        "Prüft einen Abschnitt gegen das Stimmprofil des Autors. Jeder Vorschlag muss eine "
        "Regel des Profils zitieren; Vorschläge ohne Regelbezug werden verworfen."
    ),
    # Searchable in Studio by work and section — "what had I already seen on
    # this section?" is otherwise scrolling through the timeline. Identifiers
    # and titles only, no text: search_keys are stored UNENCRYPTED.
    search_keys=["work", "section.uuid", "section.title"],
)
class BookStyleWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: EditingInput) -> EditingResult:
        paragraphs = inp.paragraphs or [inp.section.text]
        notes: list[str] = []

        if not inp.voice_profile_text:
            return EditingResult(
                work=inp.work,
                section_uuid=inp.section.uuid,
                section_title=inp.section.title,
                level="style",
                notes=[
                    "Kein Stimmprofil übergeben. Ohne Profil wäre das hier generische "
                    "Stilkritik — erst `make book-voiceprofile` laufen lassen."
                ],
            )

        raw = await check_style(
            title=inp.section.title,
            paragraphs=paragraphs,
            voice_profile_text=inp.voice_profile_text,
            max_findings=inp.max_findings,
        )
        suggestions = StyleSuggestions.model_validate(raw).suggestions

        findings = [
            JudgedFinding(
                level="style",
                paragraph_index=s.paragraph_index,
                search=s.search,
                replace=s.replace,
                kind=s.problem,
                severity=s.severity,
                why=s.why,
                rule_id=s.rule_id,
            )
            for s in suggestions
        ]

        # Filter 0 — check the anchor: the agent does not count paragraphs reliably.
        findings, index_notes = fix_paragraph_index(findings, paragraphs)
        notes += index_notes
        findings, duplicate_notes = drop_duplicates(findings)
        notes += duplicate_notes

        # Filter 1 — rule reference against the IDs actually present in the profile.
        known = set(_RULE_ID.findall(inp.voice_profile_text))
        findings, filter_notes = drop_without_rule(findings, known)
        notes += filter_notes

        # Order by severity, then cap.
        rank = {"hoch": 0, "mittel": 1, "niedrig": 2}
        findings.sort(key=lambda f: rank.get(f.severity or "niedrig", 3))
        findings = findings[: inp.max_findings]

        # Filter 2 — the second pair of eyes. Runs AFTER the cap: it costs one
        # model call per section, and nobody needs to judge suggestions that are
        # not going to be shown anyway.
        if inp.with_second_read and findings and config.AGENTS.get("style_second_read"):
            raw_review = await second_read_style(
                title=inp.section.title,
                paragraphs=paragraphs,
                voice_profile_text=inp.voice_profile_text,
                suggestions=[f.model_dump(mode="json") for f in findings],
            )
            review = StyleSecondRead.model_validate(raw_review)
            for check in review.checks:
                i = check.number - 1
                if 0 <= i < len(findings) and check.verdict != "holds":
                    findings[i].blocked = True
                    findings[i].block_reason = f"{check.verdict}: {check.why}"
            dropped = sum(1 for f in findings if f.blocked)
            if dropped:
                notes.append(
                    f"Gegenlesen hat {dropped} von {len(findings)} Vorschlägen zurückgehalten."
                )

        shown, blocked = split_blocked(findings)
        return EditingResult(
            work=inp.work,
            section_uuid=inp.section.uuid,
            section_title=inp.section.title,
            level="style",
            findings=shown,
            blocked=blocked,
            notes=notes,
        )
