"""Typeset the manuscript — Typst, calibrated against the reference PDF.

    python -m bookcli.pdf --work immer-wieder-ruegen
    python -m bookcli.pdf --chapters 1-3            # chapters 1 to 3 only
    python -m bookcli.pdf --chapters 1-3 --compare  # page count against the reference

Purely local and deterministic: reads Scrivener, writes a Typst input, calls
``typst compile``. No agent, no workflow — there is nothing to decide here, only
to set.

The measurements live in ``shared/book.json`` under ``typeset.format`` and are
**measured** from the reference PDF, not estimated. ``--compare`` holds the
result against it: the same page count for the same chapter range means the text
block is right.

Output stays German: the author reads it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from workflows.book import config as c
from workflows.book.scrivener import read_binder

TEMPLATE = Path(__file__).parent.parent / "workflows" / "book" / "typeset" / "manuscript.typ"

MONTHS = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def german_date(d: date) -> str:
    return f"{d.day}. {MONTHS[d.month - 1]} {d.year}"


def chapter_range(argument: str | None, everything: list[str]) -> list[str]:
    """Map ``1-3`` or ``4`` or nothing (= all) onto chapter names."""
    if not argument:
        return everything
    if "-" in argument:
        first, last = (int(x) for x in argument.split("-", 1))
    else:
        first = last = int(argument)
    return everything[first - 1 : last]


def build_data(slug: str, chapter_names: list[str], *, break_rule: str) -> dict:
    """The input for the Typst template — everything needed, nothing beyond."""
    work = c.load_work(slug)
    structure = work.get("structure") or {}
    m = read_binder(
        c.scrivener_path(slug),
        slug,
        root=structure.get("root"),
        chapter_level=structure.get("chapter_level", 0),
    )

    chapters = []
    for number, name in enumerate(chapter_names, start=1):
        inside = [s for s in m.sections if s.has_text and s.chapter == name]
        conf = c.chapter_by_title(slug, name) or {}
        sections = []
        previous_group: tuple[str, ...] | None = None
        for i, s in enumerate(inside):
            group = tuple(s.path[1:2])
            # Where a separator goes is a typographic decision of the author's
            # and cannot be derived from the reference (15 separators across 37
            # transitions, with no discernible rule). Hence a setting rather
            # than a guess.
            has_break = {
                "all": i > 0,
                "groups": i > 0 and group != previous_group,
                "none": False,
            }[break_rule]
            previous_group = group
            sections.append(
                {"title": s.title, "paragraphs": s.paragraphs, "break_before": has_break}
            )
        chapters.append(
            {
                "number": number,
                "title": name,
                "subtitle": conf.get("subtitle", ""),
                "sections": sections,
            }
        )

    words = sum(
        len(p.split()) for c_ in chapters for s in c_["sections"] for p in s["paragraphs"]
    )
    scope = (
        f"Kapitel {chapters[0]['number']} bis {chapters[-1]['number']}"
        if len(chapters) > 1
        else f"Kapitel {chapters[0]['number']}"
    )
    return {
        "work": {
            "title": work["title"],
            "subtitle": work.get("subtitle", ""),
            "author": work.get("author", ""),
        },
        "typeset": c.TYPESET["format"],
        "chapters": chapters,
        "as_of": german_date(date.today()),
        "scope_text": scope,
        "words": words,
    }


def pages(pdf: Path) -> int | None:
    """A PDF's page count via ``pdfinfo`` — None when that is not installed."""
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return None
    for line in out.splitlines():
        if line.startswith("Pages:"):
            return int(line.split()[-1])
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Manuskript als PDF setzen.")
    p.add_argument("--work", default="immer-wieder-ruegen")
    p.add_argument("--chapters", help="z. B. 1-3 oder 4; ohne Angabe alle")
    p.add_argument("--breaks", choices=["all", "groups", "none"],
                   help="überschreibt typeset.format.break_between")
    p.add_argument("--compare", action="store_true",
                   help="Seitenzahl gegen das Referenz-PDF halten")
    args = p.parse_args(argv)

    if not TEMPLATE.is_file():
        print(f"Template fehlt: {TEMPLATE}", file=sys.stderr)
        return 1

    work = c.load_work(args.work)
    structure = work.get("structure") or {}
    m = read_binder(
        c.scrivener_path(args.work),
        args.work,
        root=structure.get("root"),
        chapter_level=structure.get("chapter_level", 0),
    )
    names = chapter_range(args.chapters, m.chapters)
    if not names:
        print(f"Kein Kapitel für {args.chapters!r} — vorhanden: {', '.join(m.chapters)}",
              file=sys.stderr)
        return 1

    rule = args.breaks or c.TYPESET["format"].get("break_between", "groups")
    data = build_data(args.work, names, break_rule=rule)

    target_dir = c.work_path(args.work, "pdf")
    target_dir.mkdir(parents=True, exist_ok=True)
    tag = args.chapters.replace("-", "bis") if args.chapters else "alle"

    # Typst resolves paths RELATIVE TO THE TEMPLATE and refuses anything outside
    # its root. Instead of wrestling the file system with --root, we work in a
    # dedicated build folder: template and data sit next to each other there,
    # and the root is exactly that folder. Side effect: after a failure one can
    # look inside and repeat `typst compile` by hand.
    build = target_dir / ".build"
    build.mkdir(exist_ok=True)
    (build / "manuscript.typ").write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    json_path = build / "data.json"
    json_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    pdf_path = target_dir / f"{args.work}-{tag}-{date.today().isoformat()}.pdf"

    print(f"{work['title']} · {len(names)} Kapitel · {data['words']:,} Wörter"
          .replace(",", "."))
    print(f"  Trenner zwischen: {rule}")

    run = subprocess.run(
        ["typst", "compile", "--root", str(build), "--input", "data=data.json",
         str(build / "manuscript.typ"), str(pdf_path)],
        capture_output=True, text=True,
    )
    if run.returncode != 0:
        print(run.stderr.strip()[:3000], file=sys.stderr)
        return 1

    n = pages(pdf_path)
    print(f"  → {pdf_path}  ({n} Seiten)" if n else f"  → {pdf_path}")

    if args.compare:
        reference = c.work_path(args.work, "work") / c.TYPESET["reference_pdf"]
        r = pages(reference)
        if r is None:
            print(f"  Referenz nicht lesbar: {reference}")
        elif n is None:
            print("  pdfinfo fehlt — kein Vergleich möglich")
        else:
            d = n - r
            verdict = "gleich" if d == 0 else f"{d:+d} Seiten"
            print(f"  Referenz: {r} Seiten · unser Satz: {n} · {verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
