"""The ledger — every booking, once, on this machine.

JSONL, one file per month under ``workflows/data/finance/ledger/``, one line per
booking. Flat on purpose, the same reasoning as ``book/decisions.py``: it stays
countable with any tool, and a corrupt line costs one booking rather than the
file.

**Deduplication is the point.** Statements overlap — a download in April repeats
March, and re-running an import must not double the month. Identity is
``Transaction.fingerprint()``: account, date, amount, text. Deliberately not the
file or line, because the same booking appearing in two exports is exactly the
case this exists for.

Two genuinely identical bookings on one day (the same coffee twice) share a
fingerprint. They are kept, counted by ``occurrence``: the third identical
booking is only new if fewer than three are already recorded. Discarding them
would lose real money; ignoring the problem would double it on every re-import.

This file is gitignored. The repo is public, the bookkeeping is not.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from pathlib import Path

from workflows.finance.models import LedgerEntry, Transaction


def month_file(root: Path, year: int, month: int) -> Path:
    return root / "ledger" / f"{year:04d}-{month:02d}.jsonl"


def read_all(root: Path) -> list[LedgerEntry]:
    """Every entry, oldest month first. A broken line is skipped, not fatal."""
    folder = root / "ledger"
    out: list[LedgerEntry] = []
    for path in sorted(folder.glob("*.jsonl")) if folder.is_dir() else []:
        out.extend(_read_file(path))
    return out


def _read_file(path: Path) -> Iterator[LedgerEntry]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            yield LedgerEntry.model_validate_json(line)
        except ValueError:
            continue  # one unreadable line must not cost the month


def _seen(entries: Iterable[LedgerEntry]) -> Counter[str]:
    """How many times each fingerprint is already recorded."""
    return Counter(e.fp for e in entries)


def add(root: Path, transactions: list[Transaction]) -> tuple[int, int]:
    """Append what is new. Returns (added, already known).

    Rewrites each touched month file as a whole rather than appending: the
    occurrence counter has to be consistent within the file, and an append-only
    writer cannot renumber.
    """
    existing = read_all(root)
    counts = _seen(existing)
    by_month: dict[tuple[int, int], list[LedgerEntry]] = {}
    for entry in existing:
        by_month.setdefault((entry.booked_on.year, entry.booked_on.month), []).append(entry)

    added = 0
    incoming = Counter()
    for transaction in transactions:
        fingerprint = transaction.fingerprint()
        incoming[fingerprint] += 1
        if incoming[fingerprint] <= counts[fingerprint]:
            continue  # this many are already recorded
        entry = LedgerEntry(
            **transaction.model_dump(),
            fp=fingerprint,
            occurrence=incoming[fingerprint],
        )
        by_month.setdefault((entry.booked_on.year, entry.booked_on.month), []).append(entry)
        added += 1

    for (year, month), entries in by_month.items():
        path = month_file(root, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        entries.sort(key=lambda e: (e.booked_on, e.account, e.fp, e.occurrence))
        path.write_text(
            "\n".join(e.model_dump_json() for e in entries) + "\n", encoding="utf-8"
        )
    return added, len(transactions) - added


def write_all(root: Path, entries: list[LedgerEntry]) -> None:
    """Replace the ledger with these entries — used after categorisation."""
    by_month: dict[tuple[int, int], list[LedgerEntry]] = {}
    for entry in entries:
        by_month.setdefault((entry.booked_on.year, entry.booked_on.month), []).append(entry)
    for (year, month), month_entries in by_month.items():
        path = month_file(root, year, month)
        path.parent.mkdir(parents=True, exist_ok=True)
        month_entries.sort(key=lambda e: (e.booked_on, e.account, e.fp, e.occurrence))
        path.write_text(
            "\n".join(e.model_dump_json() for e in month_entries) + "\n", encoding="utf-8"
        )
