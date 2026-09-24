"""Categorise the ledger with the Studio agent.

    python -m financecli.categorise            # preview: what would be asked
    python -m financecli.categorise --apply    # ask and write it back
    python -m financecli.categorise --apply --all   # also re-ask what is done

Only what has no category yet, unless ``--all``. Re-running is therefore cheap,
and interrupting it costs nothing but the bookings already paid for.

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
import random
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from workflows.finance import config as c
from workflows.finance import ledger
from workflows.finance.categorise import parse, prompt_for
from workflows.finance.models import LedgerEntry
from workflows.finance.render import euro

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
DATA = Path(__file__).resolve().parents[2] / "data" / "finance"


async def _ask(client, agent_id: str, entry: LedgerEntry, limit: asyncio.Semaphore):
    """One booking, with backoff.

    650 bookings in quick succession hit ``429 Token rate limit reached`` — at
    concurrency 10 the first real run died after 23. The limit is on tokens per
    minute, not on requests, so waiting is the only remedy; retrying immediately
    just burns the next window too.
    """
    from mistralai.client import models as m

    async with limit:
        for attempt in range(6):
            try:
                response = await client.beta.conversations.start_async(
                    agent_id=agent_id, inputs=prompt_for(entry), store=False
                )
                break
            except Exception as exc:  # noqa: BLE001 — retry on rate limit, raise the rest
                if "429" not in str(exc) or attempt == 5:
                    raise
                # 2, 4, 8, 16, 32 seconds plus jitter, so the retries of a whole
                # chunk do not line up and hit the same window together.
                await asyncio.sleep(2 ** (attempt + 1) + random.random() * 2)
        chunks = []
        for output in response.outputs:
            content = getattr(output, "content", None)
            if isinstance(content, str):
                chunks.append(content)
            elif isinstance(content, list):
                chunks.extend(x.text for x in content if isinstance(x, m.TextChunk))
        return entry, parse("\n".join(chunks))


async def run(entries: list[LedgerEntry], on_chunk) -> list[tuple[LedgerEntry, object]]:
    """Ask in chunks, handing each finished chunk to ``on_chunk`` immediately.

    Writing after every chunk rather than at the end: the first full run died
    on a rate limit after 23 of 649 and threw all 23 away. An interruption now
    costs at most one chunk, and the next run picks up where this one stopped
    because only uncategorised bookings are asked.
    """
    from mistralai.client import Mistral

    agent_id = c.AGENTS["finance_categorise_agent_id"]
    if not agent_id:
        raise RuntimeError(
            "shared/finance.json: agent.finance_categorise_agent_id fehlt — "
            "agents/build_finance_agents.py laufen lassen und make sync-agents."
        )
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    limit = asyncio.Semaphore(c.LIMITS["concurrency"])
    size = c.LIMITS["chunk"]
    done = 0
    results: list[tuple[LedgerEntry, object]] = []
    for start in range(0, len(entries), size):
        chunk = entries[start : start + size]
        got = await asyncio.gather(*(_ask(client, agent_id, e, limit) for e in chunk))
        results += got
        done += len(chunk)
        on_chunk(got)
        print(f"  … {done}/{len(entries)}", file=sys.stderr)
        if start + size < len(entries):
            await asyncio.sleep(c.LIMITS["pause_seconds"])
    return results


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
    by_id = {id(e): e for e in entries}
    today = date.today()  # noqa: DTZ011 — local CLI, local clock

    def persist(got) -> None:
        for entry, answer in got:
            target = by_id.get(id(entry)) or entry
            if target.confirmed and target.category != answer.category:
                continue  # his decision stands; the contradiction is in the report
            target.category = answer.category
            target.subcategory = answer.subcategory
            target.merchant = answer.merchant
            target.recurring = answer.recurring
            target.confidence = answer.confidence
            target.reasoning = answer.reasoning
            target.categorised_on = today
        ledger.write_all(DATA, entries)

    try:
        results = asyncio.run(run(todo, persist))
    except KeyboardInterrupt:
        print("\nAbgebrochen — das Bisherige steht im Ledger.", file=sys.stderr)
        return 1
    report(results, before)
    print(f"\nLedger aktualisiert: {len(results)} Buchungen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
