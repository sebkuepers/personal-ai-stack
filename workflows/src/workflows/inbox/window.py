"""The time window as CALENDAR DAYS — pure arithmetic, no clock, no I/O.

``newer_than:1d`` is relative to the moment of the call: a run at 09:00 covers
yesterday 09:00 to today 09:00. Two runs then overlap, a run that starts late
loses the beginning of its day, and no two runs ever cover the same ground —
which makes a daily job impossible to reason about.

Gmail can do better. ``after:`` is inclusive, ``before:`` is exclusive, both
take a date in ``YYYY/MM/DD``. So a day is a half-open interval and consecutive
days tile the calendar without gap or overlap.

The window is built from a date handed in, never from a clock — the workflow
body must stay deterministic (``get_today()`` is an activity).
"""

from __future__ import annotations

from datetime import date, timedelta


def calendar_window(today: date, days: int, include_today: bool) -> tuple[date, date]:
    """The half-open window ``[start, end)`` of ``days`` calendar days.

    ``include_today=True`` ends the window after today — what someone asks for
    in the conversation ("what has come in since yesterday", and today counts).
    ``include_today=False`` ends it at midnight before today — what the daily
    job wants: the previous day, complete and never touched again.
    """
    if days < 1:
        raise ValueError(f"A window needs at least one day, got {days}")
    end = today + timedelta(days=1) if include_today else today
    return end - timedelta(days=days), end


def gmail_query(scope: str, window: tuple[date, date]) -> str:
    """A Gmail search for ``scope`` ("in:inbox", "in:sent") over the window."""
    start, end = window
    return f"{scope} after:{start:%Y/%m/%d} before:{end:%Y/%m/%d}"
