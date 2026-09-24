"""Generate test cases for the book agents.

    python -m bookcli.eval --generate           # build cases from the manuscript
    make book-eval                              # measure (uses evalkit)

Measuring is done with the domain-independent ``evalkit``; only what is specific
to the book lives here: which sections make good test cases and which traps
apply to this work.

The cases live in ``shared/book/eval-<slug>.json`` and are gitignored — they
contain manuscript text.

"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflows.book import config as c
from workflows.book.scrivener import read_binder

REPO = Path(__file__).resolve().parents[3]


def cases_path(slug: str) -> Path:
    return REPO / "shared" / "book" / f"eval-{slug}.json"


def generate(slug: str, count: int = 6, max_chars: int = 1800) -> list[dict]:
    """Build test cases from real sections and set the known traps.

    **Traps are set automatically, expectations are not.** The traps come from
    observed misbehaviour and from the list of protected colloquialisms in
    ``shared/book.json`` — both are solid. Which passage is a real error, on the
    other hand, only the author can decide; guessed expectations would be worse
    than none, because they fake a measurement.

    Sections with colloquialisms and direct speech are preferred: that is where
    it is decided whether an agent respects the voice or irons it flat.
    """
    work = c.load_work(slug)
    structure = work.get("structure") or {}
    m = read_binder(
        c.scrivener_path(slug),
        slug,
        root=structure.get("root"),
        chapter_level=structure.get("chapter_level", 0),
    )
    with_text = [s for s in m.sections if s.has_text]

    def score(s) -> int:  # noqa: ANN001
        t = s.text.lower()
        return sum(1 for w in c.INTENTIONAL_COLLOQUIALISMS if f" {w} " in t) + t.count("„")

    cases = []
    for s in sorted(with_text, key=score, reverse=True)[:count]:
        # Keep cases deliberately short: an eval that takes minutes does not get
        # used. Add paragraphs until the budget is reached — the ones with traps
        # first, so they are guaranteed to be in.
        with_trap = [
            p for p in s.paragraphs
            if any(f" {w} " in p.lower() for w in c.INTENTIONAL_COLLOQUIALISMS) or "„" in p
        ]
        chosen, length = [], 0
        for p in (with_trap + [x for x in s.paragraphs if x not in with_trap]):
            if length + len(p) > max_chars and chosen:
                break
            chosen.append(p)
            length += len(p)
        chosen = [p for p in s.paragraphs if p in chosen]  # original order
        paragraph_block = "\n\n".join(f"[{i}] {p}" for i, p in enumerate(chosen))

        forbidden = [
            # Always applies and needs no annotation: a "finding" that changes
            # nothing is not one. Exactly this class of error triggered an
            # earlier instruction change without the measurement showing it.
            {
                "path": "corrections[].search",
                "operator": "unchanged",
                "pair_path": "corrections[].replace",
                "note": "Befund ohne Änderung",
            },
        ] + [
            {
                "path": "corrections[].search",
                "operator": "pair",
                "pair_path": "corrections[].replace",
                "value": [word, replacement],
                "note": "gewollte Umgangssprache (shared/book.json)",
            }
            for word, replacement in c.INTENTIONAL_COLLOQUIALISMS.items()
            if f" {word} " in paragraph_block.lower()
        ]

        cases.append(
            {
                "id": s.title[:30],
                "source": "manuskript",
                "_uuid": s.uuid,
                "input": f"ABSCHNITT: {s.title}\n\n--- ABSÄTZE ---\n{paragraph_block}",
                "expected": [],
                "forbidden": forbidden,
                "note": (
                    "expected[] von Hand füllen — echte Fehler, die gefunden werden MÜSSEN. "
                    'Format: {"path": "corrections[].search", "value": "der fehlerhafte Text"}'
                ),
            }
        )
    return cases


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Testfälle für die Buch-Agents erzeugen.")
    p.add_argument("--work", default="immer-wieder-ruegen")
    p.add_argument("--count", type=int, default=6)
    p.add_argument("--max-chars", type=int, default=1800,
                   help="Obergrenze je Fall — kurze Fälle halten das Eval benutzbar")
    p.add_argument("--generate", action="store_true", help="Fälle neu bauen (überschreibt)")
    args = p.parse_args(argv)

    path = cases_path(args.work)
    if not args.generate:
        if path.is_file():
            cases = json.loads(path.read_text(encoding="utf-8"))
            expectations = sum(len(f.get("expected", [])) for f in cases)
            traps = sum(len(f.get("forbidden", [])) for f in cases)
            print(f"{len(cases)} Fälle · {expectations} Erwartungen · {traps} Fallen  →  {path.name}")
            print(
                "\nMessen:  python -m evalkit --agent book-copyedit "
                f"--cases {path.relative_to(REPO)}"
            )
        else:
            print(f"Keine Fälle vorhanden. Erzeugen mit: {p.prog} --generate")
        return 0

    cases = generate(args.work, args.count, args.max_chars)
    path.write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    traps = sum(len(f["forbidden"]) for f in cases)
    print(f"{len(cases)} Fälle → {path.relative_to(REPO)}")
    print(f"  {traps} Fallen automatisch gesetzt, 0 Erwartungen.")
    print("  → expected[] von Hand füllen; das Urteil, was ein Fehler ist, gehört dir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
