"""Categorise the ledger with the Studio agent.

    python -m financecli.categorise            # preview: what would be asked
    python -m financecli.categorise --apply    # ask and write it back
    python -m financecli.categorise --apply --all   # also re-ask what is done

Only what has no category yet, unless ``--all``. Re-running is therefore cheap,
and interrupting it costs nothing but the bookings already paid for.

The model work runs **through the workflow** ``finance-categorise``, not past
it: Temporal does the retries, every chunk shows up in the Studio timeline, and
a crash resumes. This CLI only reads the ledger, hands over prompts and writes
the answers back.

**The contradiction report is the point of ``--all``.** He chose "always a
model" over "rules first", and the open question is not cost — 190 bookings a
month are cents — but consistency: does the same merchant land in the same
category twice? A second pass over already-categorised bookings answers that
with a number instead of an opinion. A booking he has **confirmed** is never
overruled; the contradiction is reported and his decision stands.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from workflows.finance import config as c
from workflows.finance import ledger
from workflows.finance.categorise import prompt_for
from workflows.finance.models import FinanceCategory, LedgerEntry
from workflows.finance.render import euro

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
DATA = Path(__file__).resolve().parents[2] / "data" / "finance"


async def run(prompts: list[str]) -> list[dict]:
    """Trigger the ``finance-categorise`` workflow and wait for it.

    Through Studio, not past it: Temporal does the retries, the run appears in
    the timeline, and a crash resumes instead of starting over. The first
    version of this CLI called the agent directly and was therefore invisible —
    which is the one thing this repo is built to avoid.
    """
    from mistralai.extra.workflows import WorkflowEncodingConfig, configure_workflow_encoding
    from mistralai.workflows.client import get_mistral_client

    client = get_mistral_client(
        api_key=os.environ["MISTRAL_API_KEY"],
        server_url=os.environ.get("SERVER_URL", "https://api.mistral.ai"),
    )
    await configure_workflow_encoding(WorkflowEncodingConfig(), client=client)
    result = await client.workflows.execute_workflow_and_wait_async(
        workflow_identifier="finance-categorise",
        input={"prompts": prompts},
        deployment_name=os.environ.get("DEPLOYMENT_NAME", "default"),
    )
    payload = result if isinstance(result, dict) else result.model_dump()
    return payload.get("answers", payload.get("result", {}).get("answers", []))


def report(results, before: dict[str, str]) -> None:
    """What came back — and where a second pass contradicted the first."""
    counts = Counter(cat.category for _, cat in results)
    total = sum(counts.values())
    print(f"\n{total} Buchungen kategorisiert\n")
    for category, count in counts.most_common():
        spent = sum(
            e.amount_cents for e, cat in results if cat.category == category and e.amount_cents < 0
        )
        print(f"  {c.label(category):16} {count:4}  {euro(spent):>14}")

    unsure = [(e, cat) for e, cat in results if cat.confidence < 0.6]
    print(f"\nUnter 60 % Konfidenz: {len(unsure)}")
    for entry, cat in sorted(unsure, key=lambda x: x[0].amount_cents)[:8]:
        print(f"  {euro(entry.amount_cents):>12} {cat.category:14} {entry.text[:52]}")

    changed = [
        (e, cat) for e, cat in results if before.get(e.fp) and before[e.fp] != cat.category
    ]
    if before:
        share = len(changed) * 100 // max(len(before), 1)
        print(f"\nWidersprüche zum vorigen Lauf: {len(changed)} von {len(before)} ({share} %)")
        for entry, cat in changed[:8]:
            print(f"  {before[entry.fp]:14} → {cat.category:14} {entry.text[:46]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ledger kategorisieren.")
    parser.add_argument("--apply", action="store_true", help="Ergebnis ins Ledger schreiben")
    parser.add_argument("--all", action="store_true", help="auch schon kategorisierte erneut fragen")
    parser.add_argument("--limit", type=int, default=0, help="nur die ersten N (zum Ausprobieren)")
    args = parser.parse_args(argv)

    entries = ledger.read_all(DATA)
    todo = entries if args.all else [e for e in entries if not e.category]
    if args.limit:
        todo = todo[: args.limit]
    if not todo:
        print("Nichts zu kategorisieren — alles hat schon eine Kategorie. Mit --all erneut fragen.")
        return 0

    print(f"{len(todo)} von {len(entries)} Buchungen ohne Kategorie"
          if not args.all else f"{len(todo)} Buchungen, alle erneut")
    if not args.apply:
        print("\nBeispiel-Eingabe an den Agenten:\n")
        print(prompt_for(todo[0]))
        print("\nVorschau — nichts gefragt, nichts geschrieben. Mit --apply.")
        return 0

    before = {e.fp: e.category for e in todo if e.category}
    today = date.today()  # noqa: DTZ011 — local CLI, local clock
    size = c.LIMITS["chunk"]
    results: list[tuple[LedgerEntry, FinanceCategory]] = []

    # One workflow execution per chunk rather than one for all 669: each shows
    # up separately in the Studio timeline, and an interruption costs a chunk
    # instead of the run. The ledger is written after every chunk for the same
    # reason — the first full run died on a rate limit and lost everything.
    for start in range(0, len(todo), size):
        chunk = todo[start : start + size]
        answers = asyncio.run(run([prompt_for(e) for e in chunk]))
        for entry, raw in zip(chunk, answers, strict=False):
            answer = FinanceCategory.model_validate(raw)
            results.append((entry, answer))
            if entry.confirmed and entry.category != answer.category:
                continue  # his decision stands; the contradiction is in the report
            entry.category = answer.category
            entry.subcategory = answer.subcategory
            entry.merchant = answer.merchant
            entry.recurring = answer.recurring
            entry.confidence = answer.confidence
            entry.reasoning = answer.reasoning
            entry.categorised_on = today
        ledger.write_all(DATA, entries)
        print(f"  … {min(start + size, len(todo))}/{len(todo)}", file=sys.stderr)

    report(results, before)
    print(f"\nLedger aktualisiert: {len(results)} Buchungen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
