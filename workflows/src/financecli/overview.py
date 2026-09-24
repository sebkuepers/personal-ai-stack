"""Render the standing finance picture and put it in the library.

    python -m financecli.overview            # show it (default)
    python -m financecli.overview --upload   # and put it in the library

The document is his plan plus his depot: what he intends to spend, what he
subscribes to, what he wants to save, what he holds. **No booking, no account
number, no balance** — which is why it is the one part of this domain that is
harmless in a library, and why it can exist before a single statement has been
read.

Both sources are opened read-only. The planning workbook is his and stays his.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from workflows.finance import config as c
from workflows.finance import library, project55, render
from workflows.finance.models import Position
from workflows.finance.statements import parse_positions

load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def build(as_of: date) -> tuple[str, int]:
    """The overview text and how many depot positions went into it."""
    context = project55.read(c.planning_workbook())
    positions: list[Position] = []
    depot = c.latest_depot()
    if depot:
        positions = parse_positions(
            depot.read_text(encoding="utf-8-sig"), as_of=as_of, source=depot.name
        )
    return render.overview(context, positions, as_of=as_of), len(positions)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finanz-Rahmen rendern.")
    parser.add_argument("--upload", action="store_true", help="in die Library legen")
    args = parser.parse_args(argv)

    try:
        text, positions = build(date.today())  # noqa: DTZ011 — local CLI, local clock
    except (FileNotFoundError, project55.PlanningError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(text)
    if not args.upload:
        print(f"--- {positions} Depot-Positionen. Mit --upload in die Library.", file=sys.stderr)
        return 0

    name = c.LIBRARY_DOCUMENTS["overview"]
    try:
        result = library.store(name, text)
    except library.LeakError as exc:
        print(f"NICHT hochgeladen: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if result.get("skipped"):
        print(f"Übersprungen: {result['skipped']}", file=sys.stderr)
    elif result.get("kept"):
        print(f"{name} NICHT ersetzt — das vorhandene ist ausführlicher.", file=sys.stderr)
    else:
        print(f"{name} in der Library abgelegt.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
