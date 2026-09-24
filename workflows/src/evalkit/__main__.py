"""Generic eval CLI for every agent in the repo.

    python -m evalkit --agent book-copyedit --cases shared/book/eval-immer-wieder-ruegen.json
    python -m evalkit --agent crm-classification --cases shared/crm/eval-cases.json --count-path ""

The case file is a JSON list:

    [{"id": "…",
      "input": "the text that goes to the agent",
      "expected": [{"path": "corrections[].search", "value": "…"}],
      "forbidden": [{"path": "corrections[].search", "operator": "pair",
                     "pair_path": "corrections[].replace", "value": ["runter", "hinunter"]}]}]

Domains bring their own generators (e.g. ``bookcli.eval --generate``); the
measuring itself is the same for all of them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from .models import Case, tally
from .runner import DEFAULT_CONFIGS, Config, agent_definition, run_once

REPO = Path(__file__).resolve().parents[3]


def _configs(models: str | None, only: str | None) -> list[Config]:
    """The configurations to compare — either explicit models or the defaults."""
    if not models:
        return [c for c in DEFAULT_CONFIGS if not only or c.name == only]
    out: list[Config] = []
    for raw in models.split(","):
        raw = raw.strip()
        if not raw:
            continue
        with_high = raw.endswith("+")
        raw = raw.rstrip("+")
        model, _, effort = raw.partition(":")
        short = model.replace("-latest", "").replace("mistral-", "")
        out.append(Config(f"{short}/{effort or 'none'}", model, effort or None))
        if with_high:
            out.append(Config(f"{short}/high", model, "high"))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Measure agent configurations.")
    p.add_argument("--agent", required=True, help="file name in agents/ without .json")
    p.add_argument("--cases", required=True, help="path to the case file (relative to the repo)")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--only", help="this configuration only, e.g. small/high")
    p.add_argument(
        "--models",
        help=(
            "Instead of the default configurations: model IDs, comma-separated. "
            "A '+' appends a reasoning run, e.g. 'mistral-large-latest+,zai-glm-5'. "
            "Meant for reviewer comparisons — a second pair of eyes from the same "
            "model family shares the first one's blind spots."
        ),
    )
    p.add_argument(
        "--count-path",
        default="corrections[]",
        help="what counts as one finding (leave empty for classification agents)",
    )
    p.add_argument("--quiet", action="store_true", help="no progress display")
    args = p.parse_args(argv)

    path = REPO / args.cases
    if not path.is_file():
        print(f"Case file not found: {path}", file=sys.stderr)
        return 1

    load_dotenv(REPO / "workflows" / ".env", override=True)
    cases = [Case.from_dict(d) for d in json.loads(path.read_text(encoding="utf-8"))]
    instructions, schema = agent_definition(REPO, args.agent)

    configs = _configs(args.models, args.only)
    if not configs:
        available = ", ".join(c.name for c in DEFAULT_CONFIGS)
        print(f"Unknown: {args.only}. Available: {available}", file=sys.stderr)
        return 1

    expected = sum(len(c.expected) for c in cases)
    forbidden = sum(len(c.forbidden) for c in cases)
    print(
        f"{args.agent} · {len(cases)} cases · {expected} expectations · "
        f"{forbidden} traps · {args.runs} run(s)\n"
    )
    if not expected:
        print("  Note: no expectations annotated — only the trap rate is measured.\n")

    def progress(config: str, case: str) -> None:
        if not args.quiet:
            print(f"  … {config}  {case[:40]}", end="\r", file=sys.stderr)

    # Print configuration by configuration, not only at the end: a run with
    # reasoning can take minutes, and a silent process looks like a hung one.
    results = []
    for config in configs:
        all_results = []
        for _ in range(args.runs):
            for case in cases:
                progress(config.name, case.id)
                all_results.append(
                    run_once(case, config, instructions, schema,
                             count_path=args.count_path or None)
                )
        summary = tally(config.name, cases * args.runs, all_results)
        results.append((summary, all_results))
        print(" " * 70, end="\r")
        print(summary.as_line(), flush=True)

    print()
    for _summary, single in sorted(results, key=lambda x: -x[0].score):
        for r in single:
            for t in r.trapped:
                print(f"      ✗ {r.case_id[:30]}: {t[:80]}")
            for m in r.missed:
                print(f"      ○ {r.case_id[:30]}: missed {m[:70]}")
            if r.error:
                print(f"      ! {r.case_id[:30]}: {r.error[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
