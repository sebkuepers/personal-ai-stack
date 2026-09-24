"""End-to-end eval of the inbox cascade — not of the individual agents.

Measuring the stages separately (``make inbox-eval``) says what small and
medium could do. But the cascade is a system of its own with its own failure
profile:

- Small is right and escalates anyway → medium can make correct things worse
  (medium itself only hits ~91 %).
- Small is wrong WITHOUT the escalation rule firing → the error stands.
- The escalation rule itself is untested in the assembly.

This eval runs the REAL flow per case — first stage (small, exactly as
configured in ``agents/inbox-review.json``), the escalation decision from
``escalation.needs_second_review``, second stage (medium,
``agents/inbox-second-review.json``), second stage wins — and checks the final
result against the same case catalogue. For comparison, first-stage-alone and
second-stage-alone run too, because the actual question is: what does the
cascade buy over "medium on everything", and what does it cost in quality?

    uv run python -m workflows.inbox.cascade_eval --runs 2
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from evalkit.models import Case, evaluate, tally
from evalkit.runner import agent_definition
from workflows.inbox.escalation import needs_second_review
from workflows.inbox.models import InboxReview

REPO = Path(__file__).resolve().parents[4]
API = "https://api.mistral.ai/v1/chat/completions"


def _agent_setup(name: str) -> tuple[str, str, dict]:
    """(model, instructions, response_schema) of an agent from agents/<name>.json."""
    instructions, schema = agent_definition(REPO, name)
    d = json.loads((REPO / "agents" / f"{name}.json").read_text(encoding="utf-8"))
    return d["model"], instructions, schema


@dataclass
class Stage:
    """One call of a cascade stage with its real configuration."""

    name: str
    model: str
    instructions: str
    schema: dict


def _call(stage: Stage, text: str) -> tuple[dict, int, float]:
    """One chat-completions call of a stage → (answer dict, tokens, seconds)."""
    body = {
        "model": stage.model,
        "messages": [
            {"role": "system", "content": stage.instructions},
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
        "max_tokens": 4000,
        "response_format": stage.schema,
    }
    req = urllib.request.Request(
        API,
        method="POST",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    t0 = time.time()
    with urllib.request.urlopen(req) as resp:
        d = json.loads(resp.read())
    text = d["choices"][0]["message"]["content"]
    if isinstance(text, list):  # thinking chunks before the text
        text = "".join(
            t.get("text", "")
            for t in text
            if isinstance(t, dict) and t.get("type") == "text"
        )
    return (
        json.loads(text),
        d.get("usage", {}).get("completion_tokens", 0),
        time.time() - t0,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Measure the inbox cascade end to end.")
    p.add_argument("--cases", default="shared/inbox/eval-review.json")
    p.add_argument("--runs", type=int, default=1)
    args = p.parse_args(argv)

    load_dotenv(REPO / "workflows" / ".env")

    first = Stage("inbox-review", *_agent_setup("inbox-review"))
    second = Stage("inbox-second-review", *_agent_setup("inbox-second-review"))
    print(f"Cascade: first stage={first.model}, second stage={second.model}")

    cases = [
        Case.from_dict(c)
        for c in json.loads((REPO / args.cases).read_text(encoding="utf-8"))
    ]

    cascade_results = []  # final results of the cascade
    first_results = []  # first stage alone (what did the second stage fix or ruin?)
    cascade_tokens = 0
    escalations = 0

    for _ in range(args.runs):
        for case in cases:
            # Stage 1 — the first stage sees every envelope.
            answer, tokens, seconds = _call(first, case.input)
            review = InboxReview.model_validate(answer)
            r1 = evaluate(case, answer)
            r1.tokens, r1.seconds = tokens, seconds
            first_results.append(r1)
            cascade_tokens += tokens

            # Stage 2 — the second stage only where the escalation rule fires; it wins.
            if needs_second_review(review):
                escalations += 1
                answer2, tokens2, seconds2 = _call(second, case.input)
                cascade_tokens += tokens2
                r2 = evaluate(case, answer2)
                r2.seconds = seconds + seconds2
                cascade_results.append(r2)
            else:
                r = evaluate(case, answer)
                r.tokens, r.seconds = tokens, seconds
                cascade_results.append(r)

    # Second stage alone on ALL cases — the strategy the cascade has to beat
    # (medium on everything: more expensive, but without small's mistakes).
    second_alone = []
    for _ in range(args.runs):
        for case in cases:
            answer, tokens, seconds = _call(second, case.input)
            r = evaluate(case, answer)
            r.tokens, r.seconds = tokens, seconds
            second_alone.append(r)

    total = len(cases) * args.runs
    print(f"\n{total} cases · escalations: {escalations} ({escalations / total:.0%})\n")
    for name, results, tokens in (
        ("first review alone (small)", first_results, sum(r.tokens for r in first_results)),
        ("second review alone (medium)", second_alone, sum(r.tokens for r in second_alone)),
        ("CASCADE (final)", cascade_results, cascade_tokens),
    ):
        summary = tally(name, cases * args.runs, results)
        summary.tokens = tokens
        print("  " + summary.as_line())

    print("\nMissed / trapped by the cascade:")
    for r in cascade_results:
        for m in r.missed:
            print(f"  ○ {r.case_id}: missed {m}")
        for t in r.trapped:
            print(f"  ✗ {r.case_id}: trap {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
