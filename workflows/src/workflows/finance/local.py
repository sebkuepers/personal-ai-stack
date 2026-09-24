"""Reading local files from inside a workflow — allowed here, and only here.

The CRM and inbox domains run in the Cloudflare container and may not touch the
file system at all. This domain's worker runs on the author's MacBook, so the
same exception applies that ``docs/BOOK.md`` argues for ``book/local.py``: an
activity may **read**. Nothing here writes — the ledger, the workbook and every
move on disk stay in ``financecli``.

An activity reads exactly once, and the result is in the event history
afterwards. That is what makes a run reproducible in Studio rather than
dependent on what the disk happened to hold at replay time.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import mistralai.workflows as workflows

DATA = Path(__file__).resolve().parents[3] / "data" / "finance"


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def read_ledger() -> list[dict]:
    """The whole ledger as plain dicts.

    Dicts rather than models: the result crosses the sandbox boundary, and a
    Pydantic model imported on both sides of it is two classes (gotcha 20).
    """
    from workflows.finance import ledger

    return [entry.model_dump(mode="json") for entry in ledger.read_all(DATA)]


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def read_planning() -> dict | None:
    """His planning workbook, or ``None`` when it cannot be read.

    Returning ``None`` rather than raising: the conversation is still worth
    having without the plan comparison, and a missing workbook must not take
    the session down.
    """
    from workflows.finance import config as c
    from workflows.finance import project55

    try:
        return project55.read(c.planning_workbook()).model_dump(mode="json")
    except Exception:  # noqa: BLE001 — the caller shows the figures without a plan
        return None


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def read_positions() -> list[dict]:
    """The newest depot export, or an empty list when there is none."""
    from datetime import date

    from workflows.finance import config as c
    from workflows.finance.statements import parse_positions

    path = c.latest_depot()
    if not path:
        return []
    positions = parse_positions(
        path.read_text(encoding="utf-8-sig"),
        as_of=date.today(),  # noqa: DTZ011 — local worker, local clock
        source=path.name,
    )
    return [p.model_dump(mode="json") for p in positions]
