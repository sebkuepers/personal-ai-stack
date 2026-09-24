"""The ledger's one job: every booking exactly once, across overlapping exports.

Bank exports overlap — an April download repeats March. Re-importing must add
nothing. But two genuinely identical bookings on one day are real money and must
survive, and those two requirements pull in opposite directions. That tension is
what this file pins.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from workflows.finance import ledger
from workflows.finance.models import Transaction


def booking(day: int, cents: int, text: str = "Beispielhändler", account: str = "giro") -> Transaction:
    return Transaction(
        account=account,
        booked_on=date(2026, 3, day),
        text=text,
        amount_cents=cents,
    )


class TestDeduplication:
    def test_importing_the_same_export_twice_adds_nothing(self, tmp_path: Path) -> None:
        rows = [booking(1, -1000), booking(2, -2000)]
        assert ledger.add(tmp_path, rows) == (2, 0)
        assert ledger.add(tmp_path, rows) == (0, 2)
        assert len(ledger.read_all(tmp_path)) == 2

    def test_an_overlapping_export_only_adds_the_new_part(self, tmp_path: Path) -> None:
        # The real case: March downloaded in March, then again in April
        # together with April.
        march = [booking(1, -1000), booking(2, -2000)]
        march_and_april = [*march, booking(30, -3000)]
        ledger.add(tmp_path, march)
        added, known = ledger.add(tmp_path, march_and_april)
        assert (added, known) == (1, 2)
        assert len(ledger.read_all(tmp_path)) == 3

    def test_the_same_file_from_two_sources_is_one_booking(self, tmp_path: Path) -> None:
        # Identity is the booking, not the file it arrived in.
        one = booking(1, -1000)
        one.source_file = "export-a.csv"
        two = booking(1, -1000)
        two.source_file = "export-b.csv"
        two.source_line = 99
        ledger.add(tmp_path, [one])
        assert ledger.add(tmp_path, [two]) == (0, 1)

    def test_two_identical_bookings_on_one_day_both_survive(self, tmp_path: Path) -> None:
        # Two coffees at the same price on the same day is real money. Throwing
        # the second away to make deduplication simple would lose it.
        twice = [booking(1, -350), booking(1, -350)]
        assert ledger.add(tmp_path, twice) == (2, 0)
        entries = ledger.read_all(tmp_path)
        assert [e.occurrence for e in entries] == [1, 2]

    def test_and_re_importing_them_still_adds_nothing(self, tmp_path: Path) -> None:
        twice = [booking(1, -350), booking(1, -350)]
        ledger.add(tmp_path, twice)
        assert ledger.add(tmp_path, twice) == (0, 2)
        assert len(ledger.read_all(tmp_path)) == 2

    def test_a_third_identical_booking_is_new(self, tmp_path: Path) -> None:
        ledger.add(tmp_path, [booking(1, -350), booking(1, -350)])
        assert ledger.add(tmp_path, [booking(1, -350)] * 3) == (1, 2)

    def test_the_same_amount_on_another_account_is_another_booking(self, tmp_path: Path) -> None:
        ledger.add(tmp_path, [booking(1, -1000, account="giro")])
        assert ledger.add(tmp_path, [booking(1, -1000, account="karte")]) == (1, 0)


class TestFiles:
    def test_bookings_are_split_by_month(self, tmp_path: Path) -> None:
        rows = [booking(1, -1000), Transaction(
            account="giro", booked_on=date(2026, 4, 2), text="April", amount_cents=-500
        )]
        ledger.add(tmp_path, rows)
        assert ledger.month_file(tmp_path, 2026, 3).is_file()
        assert ledger.month_file(tmp_path, 2026, 4).is_file()

    def test_one_unreadable_line_does_not_cost_the_month(self, tmp_path: Path) -> None:
        ledger.add(tmp_path, [booking(1, -1000), booking(2, -2000)])
        path = ledger.month_file(tmp_path, 2026, 3)
        path.write_text(path.read_text(encoding="utf-8") + "{kaputt\n", encoding="utf-8")
        assert len(ledger.read_all(tmp_path)) == 2

    def test_an_empty_ledger_reads_as_empty_not_as_an_error(self, tmp_path: Path) -> None:
        assert ledger.read_all(tmp_path) == []
