"""Reading the planning workbook, and the one door out of this machine.

The workbook fixture is **constructed** — his layout, invented numbers. The
layout itself (three label/amount column pairs, a heading being a label without
an amount) was measured against the real file on 2026-09-24.

The leak guard is the more important half of this file. The library is the only
place in this domain where anything leaves the machine, so the check sits at
that door rather than in the habits of whoever writes the next renderer.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from workflows.finance import library, project55, render
from workflows.finance.models import PlanItem, PlanningContext, PlanSection, Position


def _workbook(tmp_path: Path, *, sheet: str = "Ausgaben") -> Path:
    """His layout: labels in A/G/M, monthly amounts in B/H/N."""
    import openpyxl

    book = openpyxl.Workbook()
    page = book.active
    page.title = sheet
    rows = {
        "A1": "Ausgaben Tracking",
        "A3": "Haus",
        "A4": "Miete", "B4": 1000,
        "A5": "Strom", "B5": 100,
        "A8": "Sonstige", "B8": 50,  # equals the middle block's total → a roll-up
        "A10": "Summe", "B10": 1150,
        "A12": "Sparrate:", "B12": 0,
        "G3": "Kleinstausgaben",
        "G4": "Lotto", "H4": 10,
        "G5": "Mistral", "H5": 40,
        "G7": "Summe", "H7": 50,
        "G9": "Kürzen", "H9": 10,
        "M3": "Sparpotential",
        "M4": "Aktuell", "N4": 200,
        "M6": "Summe", "N6": 200,
        "M8": "Notgroschen", "N8": 5000,
    }
    for ref, value in rows.items():
        page[ref] = value
    path = tmp_path / "plan.xlsx"
    book.save(path)
    return path


class TestPlanningWorkbook:
    def test_a_label_without_an_amount_is_a_heading(self, tmp_path: Path) -> None:
        ctx = project55.read(_workbook(tmp_path))
        assert [s.title for s in ctx.sections] == ["Haus", "Kleinstausgaben", "Sparpotential"]

    def test_the_sheet_title_is_not_a_section(self, tmp_path: Path) -> None:
        # "Ausgaben Tracking" in A1 has no items under it.
        ctx = project55.read(_workbook(tmp_path))
        assert all(s.title != "Ausgaben Tracking" for s in ctx.sections)

    def test_each_block_keeps_its_own_total(self, tmp_path: Path) -> None:
        # "Summe" appears once per column. Keyed by label alone the last one
        # won, and the expense total silently became the savings potential.
        ctx = project55.read(_workbook(tmp_path))
        assert ctx.monthly_total_cents == 115000
        assert ctx.subscriptions_total_cents == 5000
        assert ctx.savings_potential_cents == 20000

    def test_the_goals_are_read(self, tmp_path: Path) -> None:
        ctx = project55.read(_workbook(tmp_path))
        assert ctx.savings_rate_cents == 0
        assert ctx.emergency_fund_cents == 500000
        assert ctx.cuttable_cents == 1000

    def test_the_middle_block_is_the_subscription_list(self, tmp_path: Path) -> None:
        ctx = project55.read(_workbook(tmp_path))
        assert [s.label for s in ctx.subscriptions] == ["Lotto", "Mistral"]

    def test_a_line_that_equals_another_blocks_total_is_a_roll_up(self, tmp_path: Path) -> None:
        # "Sonstige" carries the total of the middle column. Treated as an
        # expense it both lands under the wrong heading and double-counts every
        # subscription.
        ctx = project55.read(_workbook(tmp_path))
        rolled = [i for s in ctx.sections for i in s.items if i.rollup]
        assert [i.label for i in rolled] == ["Sonstige"]

    def test_a_missing_sheet_is_named(self, tmp_path: Path) -> None:
        path = _workbook(tmp_path, sheet="Etwas anderes")
        with pytest.raises(project55.PlanningError, match="Ausgaben"):
            project55.read(path)

    def test_a_missing_file_is_named(self, tmp_path: Path) -> None:
        with pytest.raises(project55.PlanningError, match="nicht gefunden"):
            project55.read(tmp_path / "gibtesnicht.xlsx")


class TestLeakGuard:
    """Nothing that identifies an account may reach the library."""

    # Every identifier below is INVENTED. The first version of this file used
    # the real ones out of the statements — in a test whose whole point is that
    # such things must not end up anywhere public.
    @pytest.mark.parametrize(
        "text",
        [
            "Überweisung an DE00000000000000000000 vom 10.04.",
            "Karte 0000 0000 0000 0000",
            "Belastete Kreditkarte 0000 00XX XXXX 0000",
            "Konto NL00000000000000000000",
        ],
    )
    def test_an_account_identifier_is_refused(self, text: str) -> None:
        with pytest.raises(library.LeakError):
            library.check(text)

    def test_amounts_and_merchants_are_fine(self) -> None:
        # Without merchant names the whole point is gone: a question about one
        # kind of spending needs the merchants it consists of.
        library.check("Beispielladen 10,00 € · Beispieldienst 14,99 € · Summe 498,58 €")

    def test_the_real_overview_passes_the_door(self) -> None:
        ctx = PlanningContext(
            sections=[PlanSection(title="Haus", items=[PlanItem(label="Miete", monthly_cents=1000)])],
            subscriptions=[PlanItem(label="Lotto", monthly_cents=1000)],
            monthly_total_cents=1000,
            source="plan.xlsx",
        )
        position = Position(name="MSCI World", isin="IE00B4L5Y983", value_cents=54220, kind="ETF")
        library.check(render.overview(ctx, [position], as_of=date(2026, 9, 24)))

    def test_an_isin_is_not_mistaken_for_an_iban(self) -> None:
        # Both start with two letters and two digits. An ISIN is twelve
        # characters and belongs in the depot listing; refusing it would make
        # the portfolio section impossible.
        library.check("MSCI World (IE00B4L5Y983) — 542,20 €")
