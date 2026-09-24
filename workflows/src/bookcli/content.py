"""Check a chapter against its rubric — level 3.

    python -m bookcli.content --work immer-wieder-ruegen --chapter "Voll zur Oma"
    python -m bookcli.content --chapter "Und jetzt?" --without-synopsis

Writes nothing. The result is a list of findings and at most five questions —
the answer to those is writing, and that is the author's job.

Prerequisite: a running worker (``make start-worker``).
"""

from __future__ import annotations

import argparse

from workflows.book.models import ContentReview

from .editing import run

MARKS = {"yes": "✓", "partly": "~", "no": "✗", "holds": "✓", "wobbles": "~", "fails": "✗"}


def show(e: dict) -> None:
    review = ContentReview.model_validate(e["review"])
    print(f"\n{'=' * 74}")
    print(f"INHALT — {e['chapter']}  ({e['sections']} Abschnitte, {e['words']} Wörter)")
    print(f"{'=' * 74}\n")

    print(f"These des Kapitels, aus dem Text gelesen:\n  {review.chapter_thesis}\n")

    if review.touchstones:
        print("PRÜFSTEINE")
        for t in review.touchstones:
            print(f"  {MARKS.get(t.verdict, '?')} {t.question}")
            print(f"      {t.reason}")
            if t.places:
                print(f"      Stellen: {', '.join(t.places)}")
        print()

    if review.carries:
        open_ = [c for c in review.carries if c.carried != "yes"]
        print(f"MUSS TRAGEN — {len(review.carries) - len(open_)} von {len(review.carries)} eingelöst")
        for c in review.carries:
            print(f"  {MARKS.get(c.carried, '?')} {c.point}")
            if c.carried != "yes":
                print(f"      {c.why}")
            elif c.sections:
                print(f"      {', '.join(c.sections)}")
        print()

    for heading, entries in (("STEHT DRIN, MUSS ABER NICHT", review.surplus),
                             ("STREICHKANDIDATEN", review.cut_candidates)):
        if entries:
            print(heading)
            for c in entries:
                print(f"  · {c.section} ({c.extent})")
                print(f"      {c.reason}")
            print()

    if review.questions_for_the_author:
        print("FRAGEN AN DICH")
        for q in review.questions_for_the_author:
            print(f"  ? {q}")
        print()

    if e.get("notes"):
        print("HINWEISE")
        for n in e["notes"]:
            print(f"  · {n}")
        print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ein Kapitel gegen seine Rubrik prüfen.")
    p.add_argument("--work", default="immer-wieder-ruegen")
    p.add_argument("--chapter", required=True)
    p.add_argument(
        "--without-synopsis", action="store_true", help="nur Rubrik und Prüfsteine"
    )
    args = p.parse_args(argv)

    import asyncio

    raw = asyncio.run(
        run(
            "book-content",
            {
                "work": args.work,
                "chapter": args.chapter,
                "with_synopsis": not args.without_synopsis,
            },
        )
    )
    show(raw if isinstance(raw, dict) else raw.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
