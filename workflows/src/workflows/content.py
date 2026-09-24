"""Level 3 of the edit — a whole chapter against the author's rubric.

The other two levels work on the sentence. This one works on the arc: does the
chapter carry what it is supposed to carry? Does it hold the two touchstones? Is
there something in it that, according to the plan, does not belong?

**It changes nothing.** No ``search``, no ``replace``, nowhere in the schema.
The answer to a substantive problem is writing, not replacing — and the writing
is the author's. This level shows him where the chapter fails its own rubric,
and asks at most five questions.

Three yardsticks, in descending authority:

1. **The chapter rubric** from ``shared/book/<slug>.json`` — ``proves``,
   ``must_carry``, ``need_not_carry``, register, season, history budget.
2. **The work's touchstones** — the two questions that have already, in
   practice, sunk a whole chapter and a location and thrown them out of the
   book. That makes them the sharpest yardstick this repo knows.
3. **The exposé** from ``kontext/expose.md`` — what the book is meant to become.
   It comes last and is explicitly marked as intent: it describes the book as it
   is offered to publishers, not as the manuscript is. Confuse the two and every
   deviation looks like an error.

Trigger with:
  make book-content work=immer-wieder-ruegen chapter="Voll zur Oma"
"""

from __future__ import annotations

from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows import workflow
from pydantic import BaseModel, Field

with workflow.unsafe.imports_passed_through():
    from workflows.book.models import ContentReview
    from workflows.book.agents import review_content
    from workflows.book.local import load_context, read_chapter


class ContentInput(BaseModel):
    """Input of ``book-content`` — one chapter of a work."""

    work: str = "immer-wieder-ruegen"
    chapter: str
    with_synopsis: bool = Field(
        default=True, description="Pass the exposé in as a third yardstick"
    )


class ContentResult(BaseModel):
    """Output of ``book-content``."""

    work: str
    chapter: str
    words: int
    sections: int
    review: ContentReview
    notes: list[str] = Field(default_factory=list)


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def read_rubric(work: str, chapter: str) -> tuple[dict, dict]:
    """The chapter's rubric and the work's touchstones from ``shared/book/<slug>.json``."""
    import workflows.book.config as config

    w = config.load_work(work)
    rubric = config.chapter_by_title(work, chapter) or {}
    return rubric, w.get("touchstones") or {}


@workflows.workflow.define(
    name="book-content",
    workflow_display_name="Book · Content (level 3)",
    workflow_description=(
        "Prüft ein ganzes Kapitel gegen die Rubrik des Autors: Prüfsteine, was es tragen muss, "
        "was nicht hineingehört. Ändert nichts — stellt Fragen und benennt, was fehlt."
    ),
    execution_timeout=timedelta(minutes=30),
    # Identifiers only, no text — search_keys are stored unencrypted.
    search_keys=["work", "chapter"],
)
class BookContentWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: ContentInput) -> ContentResult:
        chapter = await read_chapter(inp.work, inp.chapter)
        notes: list[str] = []

        synopsis = await load_context(inp.work, "expose") if inp.with_synopsis else ""
        if inp.with_synopsis and not synopsis:
            notes.append(
                "Kein Exposé in kontext/expose.md — geprüft wird nur gegen Rubrik und Prüfsteine."
            )

        # Rubric and touchstones come through an activity, because they are read
        # from `shared/` — that is I/O and does not belong in the workflow body,
        # which is replayed on a retry.
        rubric, touchstones = await read_rubric(inp.work, inp.chapter)
        if not rubric:
            notes.append(
                f"Für {inp.chapter!r} steht keine Rubrik in shared/book/{inp.work}.json — "
                "geprüft wird nur gegen die Prüfsteine des Werks."
            )

        raw = await review_content(
            chapter=chapter, rubric=rubric, touchstones=touchstones, synopsis=synopsis
        )
        return ContentResult(
            work=inp.work,
            chapter=inp.chapter,
            words=chapter["words"],
            sections=len(chapter["sections"]),
            review=ContentReview.model_validate(raw),
            notes=notes,
        )
