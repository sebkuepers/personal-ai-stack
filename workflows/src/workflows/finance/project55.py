"""Reading the author's planning workbook — **read only, always**.

The planning workbook is his top-level document and the one artefact in this
domain that is genuinely maintained by hand. Nothing here
writes to it; a test holds that.

What it supplies, and what this module therefore does not have to invent:
the category structure, the subscriptions one by one, what he plans to spend per month,
his savings rate, his emergency-fund target and where he sees room to cut.

**Not** the target portfolio. Sheet ``Tabelle2`` carries an old one, and he said
plainly that it is outdated — the live depot export is what represents where the
journey is going. So the portfolio comes from ``Depot/``, and this module ignores
that sheet rather than quietly serving stale strategy.

**The layout**, measured on 2026-09-24: sheet ``Ausgaben`` holds three blocks
side by side. A label in column A has its monthly amount in B, a label in G has
it in H, a label in M has it in N. A label with **no** amount next to it is a
section heading (``Haus``, ``Autos``, ``Kredite`` …), not an item.

If that layout changes, this module raises by name. Guessing a column would
produce a plan that is quietly wrong, and a plan that is quietly wrong is worse
than no plan.

**What this module deliberately does not do: infer more hierarchy than the
header rule gives.** In his sheet one line sits two blank rows below the
block above it and is in fact a roll-up of the whole middle column, while another
sits two blank rows below its siblings and does belong to its section. The two are indistinguishable from the file, so no gap heuristic
can separate them. Every figure that matters is therefore taken from HIS total
cells, never summed up by me — a computed section total is shown as computed and
nowhere used as a claim about his plan.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from workflows.finance.models import PlanItem, PlanningContext, PlanSection

SHEET = "Ausgaben"
# label column → the column holding its monthly amount
BLOCKS = (("A", "B"), ("G", "H"), ("M", "N"))
# Rows that are arithmetic on the sheet, not line items of his plan.
TOTALS = {"summe", "sparrate:", "sparrate", "kürzen", "notgroschen"}


class PlanningError(ValueError):
    """The workbook does not look the way it did — with what was expected."""


def _cents(value: Any) -> int | None:
    """A cell as integer cents. ``None`` when the cell is empty."""
    if value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (ArithmeticError, ValueError):
        return None


def read(path: Path) -> PlanningContext:
    """Read the planning workbook. Opens it read-only and never writes."""
    import openpyxl  # local: keeps the import cost off every other domain

    if not path.is_file():
        raise PlanningError(f"Planungsmappe nicht gefunden: {path}")
    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    if SHEET not in workbook.sheetnames:
        raise PlanningError(
            f"Blatt {SHEET!r} fehlt in {path.name} — vorhanden: {workbook.sheetnames}"
        )
    sheet = workbook[SHEET]

    sections: list[PlanSection] = []
    block_of: dict[int, int] = {}  # id(section) → the column block it came from
    subscriptions: list[PlanItem] = []
    totals: dict[str, int] = {}

    for index, (label_col, amount_col) in enumerate(BLOCKS):
        current: PlanSection | None = None
        for row in range(1, (sheet.max_row or 0) + 1):
            label = sheet[f"{label_col}{row}"].value
            if not isinstance(label, str) or not label.strip():
                continue
            label = label.strip()
            amount = _cents(sheet[f"{amount_col}{row}"].value)

            if label.lower() in TOTALS:
                # Keyed by BLOCK and label: "Summe" appears once per column, and
                # keying by label alone let the last one win — the expense total
                # silently became the savings-potential total.
                totals[f"{index}:{label.lower().rstrip(':')}"] = amount or 0
                continue
            if amount is None:
                current = PlanSection(title=label, items=[])
                block_of[id(current)] = index
                sections.append(current)
                continue
            item = PlanItem(label=label, monthly_cents=amount)
            if current is not None:
                current.items.append(item)
            # The middle block IS his subscription list —             # Lotto, Mistral, Garmin … each with what it costs per month.
            if index == 1:
                subscriptions.append(item)

    if not sections:
        raise PlanningError(
            f"Keine Abschnitte in {SHEET!r} gefunden — die Spaltenaufteilung "
            f"{BLOCKS} passt nicht mehr."
        )

    # A heading with nothing under it is the sheet title, not a section.
    sections = [s for s in sections if s.items]

    # "Sonstige" in the left column carries exactly the total of the middle
    # column — it is a roll-up line, not an expense of its own. Placing it under
    # the section above (Sparen) both misfiles it and double-counts every
    # subscription. Detected by the one signal the sheet actually gives: its
    # amount IS another block's total.
    # It has to be the total of ANOTHER block. A section with a single item
    # trivially equals its own block's total, and the first version of this
    # rule duly flagged that item as a roll-up — caught by its own fixture.
    for section in sections:
        here = block_of.get(id(section))
        elsewhere = {
            v for k, v in totals.items()
            if k.endswith(":summe") and v and not k.startswith(f"{here}:")
        }
        for item in section.items:
            if item.monthly_cents in elsewhere:
                item.rollup = True

    return PlanningContext(
        sections=sections,
        subscriptions=subscriptions,
        monthly_total_cents=totals.get("0:summe", 0),
        subscriptions_total_cents=totals.get("1:summe", 0),
        savings_potential_cents=totals.get("2:summe", 0),
        savings_rate_cents=totals.get("0:sparrate", 0),
        emergency_fund_cents=totals.get("2:notgroschen", 0),
        cuttable_cents=totals.get("1:kürzen", 0),
        source=path.name,
        read_on=date.today(),  # noqa: DTZ011 — a local CLI reading a local file
    )
