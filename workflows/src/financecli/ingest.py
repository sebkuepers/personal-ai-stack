"""Read the statements in ``Konten/`` into the ledger.

    python -m financecli.ingest          # preview: what would be added
    python -m financecli.ingest --apply  # write it

No model, no network. Pure arithmetic over the files that are already on this
machine, and the numbers it prints are the ones every later step depends on —
so it prints them before anything is asked of an agent.

Re-running is safe: identity is the booking, not the file, so an export that
repeats last month adds nothing (see ``ledger``).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from workflows.finance import config as c
from workflows.finance import ledger
from workflows.finance.models import Transaction
from workflows.finance.render import euro
from workflows.finance.statements import StatementError, parse_file

DATA = Path(__file__).resolve().parents[2] / "data" / "finance"


def collect() -> tuple[list[Transaction], list[str]]:
    """Every booking in ``Konten/``, plus what could not be read."""
    out: list[Transaction] = []
    problems: list[str] = []
    for account in c.accounts():
        folder = c.folder_of("Konten") / account["id"]
        if not folder.is_dir():
            problems.append(f"{account['id']}: kein Ordner {folder}")
            continue
        files = sorted(folder.glob("*.csv"))
        if not files:
            problems.append(f"{account['id']}: keine Auszüge in {folder.name}/")
        for path in files:
            try:
                out.extend(parse_file(path, dialect=account["dialect"], account=account["id"]))
            except StatementError as exc:
                problems.append(f"{account['id']}/{path.name}: {exc}")
    return out, problems


def show(transactions: list[Transaction]) -> None:
    """What the files actually contain — before a model ever sees them."""
    if not transactions:
        print("Keine Buchungen gefunden.")
        return
    by_account = Counter(t.account for t in transactions)
    print(f"{len(transactions)} Buchungen aus {len(by_account)} Konten\n")
    for account, count in by_account.most_common():
        rows = [t for t in transactions if t.account == account]
        low, high = min(r.booked_on for r in rows), max(r.booked_on for r in rows)
        out = sum(r.amount_cents for r in rows if r.amount_cents < 0)
        income = sum(r.amount_cents for r in rows if r.amount_cents > 0)
        print(
            f"  {account:20} {count:4}  {low:%d.%m.%Y} – {high:%d.%m.%Y}"
            f"  aus {euro(out):>14}  ein {euro(income):>14}"
        )

    print("\nDie zehn größten Ausgaben:")
    for row in sorted(transactions, key=lambda t: t.amount_cents)[:10]:
        print(f"  {euro(row.amount_cents):>14}  {row.booked_on:%d.%m.}  {row.text[:62]}")

    # Same amount from the same counterparty in three or more months: the
    # deterministic half of the subscription question, before any model.
    seen: dict[tuple[str, int], set[tuple[int, int]]] = {}
    for row in transactions:
        key = (row.counterparty or row.text[:28], row.amount_cents)
        seen.setdefault(key, set()).add((row.booked_on.year, row.booked_on.month))
    recurring = {k: v for k, v in seen.items() if len(v) >= 3 and k[1] < 0}
    print(f"\nGleicher Betrag in ≥3 Monaten: {len(recurring)} Kandidaten")
    for (who, amount), months in sorted(recurring.items(), key=lambda kv: kv[0][1])[:10]:
        print(f"  {euro(amount):>12}  ×{len(months)}  {who[:56]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kontoauszüge ins Ledger einlesen.")
    parser.add_argument("--apply", action="store_true", help="wirklich schreiben")
    args = parser.parse_args(argv)

    try:
        transactions, problems = collect()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    for problem in problems:
        print(f"  ! {problem}", file=sys.stderr)
    show(transactions)

    if not args.apply:
        print("\nVorschau — nichts geschrieben. Mit --apply ins Ledger.")
        return 0
    added, known = ledger.add(DATA, transactions)
    print(f"\n{added} neu ins Ledger, {known} schon bekannt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
