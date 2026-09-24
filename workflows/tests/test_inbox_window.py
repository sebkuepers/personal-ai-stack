"""The window is the whole reason a daily job can be reasoned about.

``newer_than:1d`` is relative to the moment of the call: two runs overlap, a
late run loses the start of its day, and no run ever covers exactly one day.
Calendar days tile — that property is what these tests pin.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from workflows.inbox.window import calendar_window, gmail_query

MONDAY = date(2026, 9, 21)
WEDNESDAY = date(2026, 9, 23)


class TestCalendarWindow:
    def test_the_daily_job_gets_yesterday_and_only_yesterday(self) -> None:
        start, end = calendar_window(WEDNESDAY, days=1, include_today=False)
        assert (start, end) == (date(2026, 9, 22), WEDNESDAY)

    def test_the_conversation_gets_today_too(self) -> None:
        start, end = calendar_window(WEDNESDAY, days=1, include_today=True)
        assert (start, end) == (WEDNESDAY, date(2026, 9, 24))

    def test_seven_days_including_today_ends_tomorrow(self) -> None:
        start, end = calendar_window(WEDNESDAY, days=7, include_today=True)
        assert (start, end) == (date(2026, 9, 17), date(2026, 9, 24))

    def test_consecutive_daily_windows_tile_without_gap_or_overlap(self) -> None:
        """The property the whole design rests on."""
        windows = [
            calendar_window(MONDAY + timedelta(days=n), days=1, include_today=False)
            for n in range(3)
        ]
        for earlier, later in zip(windows, windows[1:], strict=False):
            assert earlier[1] == later[0], f"{earlier} and {later} do not tile"

    def test_a_window_of_zero_days_is_refused(self) -> None:
        # Silently returning an empty window would report "nothing to do" —
        # the most expensive possible lie in a triage run.
        with pytest.raises(ValueError, match="at least one day"):
            calendar_window(WEDNESDAY, days=0, include_today=True)


class TestGmailQuery:
    def test_the_format_is_the_one_gmail_takes(self) -> None:
        window = calendar_window(WEDNESDAY, days=1, include_today=False)
        assert gmail_query("in:inbox", window) == (
            "in:inbox after:2026/09/22 before:2026/09/23"
        )

    def test_the_sent_pass_uses_the_same_window(self) -> None:
        window = calendar_window(WEDNESDAY, days=3, include_today=True)
        assert gmail_query("in:sent", window) == (
            "in:sent after:2026/09/21 before:2026/09/24"
        )
