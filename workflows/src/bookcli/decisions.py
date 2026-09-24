"""Read and count the decision log.

    python -m bookcli.decisions --work immer-wieder-ruegen           # tally per rule
    python -m bookcli.decisions --work immer-wieder-ruegen --last 20
    python -m bookcli.decisions --work immer-wieder-ruegen --eval shared/book/eval-from-log.json

``--eval`` turns the author's decisions into test cases for ``evalkit``: every
rejected style suggestion becomes a trap, every accepted one an expectation.
That is the point where the evals stop being my constructions and start carrying
his judgement.

The file does NOT land in the repo — it contains manuscript text.
``shared/book/*.json`` is gitignored anyway; only the explicitly released eval
files are excluded from that, and this one is not among them.

"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflows.book import decisions as log

DATA = Path(__file__).resolve().parents[2] / "data"


def as_eval_cases(lines: list[dict], *, level: str, work: str) -> list[dict]:
    """Test cases from decisions — grouped per section and session.

    One case per (session, section). The **input** is reconstructed exactly as
    the agent received it: section text from Scrivener (as of now — the text may
    have changed since the session, in which case the anchors no longer hold and
    the case is skipped), plus the current voice profile for the style level.

    Traps are the rejected suggestions (search text → replacement), expectations
    the accepted ones. With that the evals carry HIS judgement for the first
    time, not mine.
    """
    from workflows.book import config as c
    from workflows.book.scrivener import read_binder

    from .editing import voice_profile_text

    w = c.load_work(work)
    structure = w.get("structure") or {}
    m = read_binder(
        c.scrivener_path(work), work,
        root=structure.get("root"), chapter_level=structure.get("chapter_level", 0),
    )
    by_uuid = {s.uuid: s for s in m.sections if s.has_text}
    profile = voice_profile_text(work) if level == "style" else ""

    def input_for(s) -> str:  # noqa: ANN001
        block = "\n\n".join(f"[{i}] {t}" for i, t in enumerate(s.paragraphs))
        if level == "style":
            return (
                f"HÖCHSTENS 12 VORSCHLÄGE.\n\n=== STIMMPROFIL DES AUTORS ===\n{profile}\n\n"
                f"=== ABSCHNITT: {s.title} ===\n{block}"
            )
        return f"ABSCHNITT: {s.title}\n\n--- ABSÄTZE ---\n{block}"

    groups: dict[tuple[str, str], list[dict]] = {}
    for entry in lines:
        if entry.get("level") != level:
            continue
        groups.setdefault((entry["session"], entry["section_uuid"]), []).append(entry)

    cases = []
    for (session, uuid), entries in groups.items():
        s = by_uuid.get(uuid)
        if s is None:
            continue
        # Only decisions whose anchor still sits in today's text. What the
        # author rewrote since the session is no longer a test case.
        entries = [e for e in entries if any(e["search"] in p for p in s.paragraphs)]
        forbidden = [
            {
                "path": "suggestions[].search",
                "operator": "pair",
                "pair_path": "suggestions[].replace",
                "value": [e["search"], e["replace"]],
                "note": e.get("reason") or "abgelehnt",
            }
            for e in entries
            if e["decision"] == "abgelehnt"
        ]
        expected = [
            {"path": "suggestions[].search", "value": e["search"]}
            for e in entries
            if e["decision"] == "angenommen"
        ]
        if not forbidden and not expected:
            continue
        cases.append(
            {
                "id": f"{entries[0]['section']}-{session[:8]}",
                "source": "entscheidungslog",
                "note": (
                    f"{len(expected)} angenommen, {len(forbidden)} abgelehnt — "
                    f"Sitzung {session[:8]}, {entries[0]['ts'][:10]}"
                ),
                "section_uuid": uuid,
                "input": input_for(s),
                "expected": expected,
                "forbidden": forbidden,
            }
        )
    return cases


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Entscheidungslog lesen und auszählen.")
    p.add_argument("--work", default="immer-wieder-ruegen")
    p.add_argument("--level", default="style", choices=["copyedit", "style"])
    p.add_argument("--last", type=int, help="die letzten N Zeilen zeigen")
    p.add_argument("--eval", help="Testfälle aus den Entscheidungen in diese Datei schreiben")
    args = p.parse_args(argv)

    lines = log.read_all(DATA, args.work)
    if not lines:
        print(f"Noch keine Entscheidungen für {args.work!r} unter {log.log_dir(DATA, args.work)}")
        return 0

    print(f"{len(lines)} Entscheidungen · {len({entry['session'] for entry in lines})} Sitzungen · "
          f"{len({entry['section_uuid'] for entry in lines})} Abschnitte\n")

    if args.last:
        for entry in lines[-args.last :]:
            mark = {"angenommen": "✓", "abgelehnt": "✗", "zurueckgestellt": "·"}[entry["decision"]]
            reason = f"  — {entry['reason']}" if entry.get("reason") else ""
            print(f"  {mark} [{entry['level']}] {entry['section']}: {entry['search'][:50]!r}{reason}")
        print()

    print(log.as_text(log.tally_per_rule(lines, level=args.level)))

    if args.eval:
        cases = as_eval_cases(lines, level=args.level, work=args.work)
        Path(args.eval).write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n")
        print(f"\n→ {len(cases)} Fälle nach {args.eval} (nicht fürs Repo — enthält Werktext)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
