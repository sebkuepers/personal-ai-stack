"""Rendering the report is pure Markdown — the same instance goes to canvas,
chat and library. A rendering mistake here distorts all three.

The boring case is included: an empty report must not produce empty Markdown
sections with broken tables — "_(nichts)_" is the honest form.
"""

from __future__ import annotations

from datetime import date

from workflows.inbox.render import dossier, headline, report_as_markdown
from workflows.inbox.models import (
    ReplyItem,
    FinanceItem,
    InboxScanReport,
    SentEnvelope,
    UnsubCandidate,
)


def _report() -> InboxScanReport:
    return InboxScanReport(
        window_days=1,
        inbox_found=2,
        skipped_no_messages=4,
        own_replies=1,
        pages=1,
        second_review_count=1,
        second_review_changed=1,
        type_counts={"newsletter": 1, "invoice_payment": 1},
        subscription_groups={"GitHub": 1},
        needs_reply=[
            ReplyItem(
                sender="a@example.com", subject="Zahlung fehlgeschlagen",
                urgency="today", reasoning="", answered=False,
            )
        ],
        finance=[
            FinanceItem(
                sender="a@example.com", subject="Zahlung fehlgeschlagen",
                kind="reminder", amount="89,00 EUR", due_date="2026-09-26",
            )
        ],
        context=["Zusage für Freitag, 10 Uhr."],
        unsub_links=[
            UnsubCandidate(
                sender="news@example.com", subject="Rundbrief",
                thread_id="t1", url="https://news.example.com/out",
            )
        ],
        sent=[SentEnvelope(sender="seb@example.com", to=["x@example.com"], subject="Re: Termin")],
    )


def _leerer_report() -> InboxScanReport:
    return InboxScanReport(
        window_days=1, inbox_found=0, pages=0,
        skipped_no_messages=0, own_replies=0,
    )


# ---------------------------------------------------------------------------
# Kopfzahlen für den Chat
# ---------------------------------------------------------------------------


def test_headline_names_the_essentials() -> None:
    text = headline(_report())
    assert "2 Mails" in text
    assert "1× Zweitblick (1 geändert)" in text
    assert "1 Antwort(en) erwartet" in text


def test_headline_of_an_empty_run() -> None:
    text = headline(_leerer_report())
    assert "0 Mails" in text
    assert "Antwort" not in text


# ---------------------------------------------------------------------------
# Der volle Report als Markdown (Canvas)
# ---------------------------------------------------------------------------


def test_report_markdown_carries_every_section() -> None:
    md = report_as_markdown(_report())
    assert "## Dringend — Antwort erwartet" in md
    assert "## Finanzen" in md
    assert "## Lärm nach Absender-Gruppe" in md
    assert "## Abbestell-Kandidaten" in md
    assert "## Kontext für Vibe" in md
    assert "## Gesendet im Fenster" in md
    assert "[Abmelden](https://news.example.com/out)" in md
    assert "89,00 EUR" in md
    assert "2026-09-26" in md


def test_report_markdown_of_an_empty_run_has_no_broken_tables() -> None:
    md = report_as_markdown(_leerer_report())
    assert "_(nichts)_" in md
    assert "GitHub" not in md


# ---------------------------------------------------------------------------
# The dossier for the library
# ---------------------------------------------------------------------------


def test_dossier_is_cut_for_vibe() -> None:
    d = dossier(_report(), "2026-09-24")
    assert "# Inbox · Kontext — Stand 2026-09-24" in d
    assert "Antworten, die du schuldest" in d
    assert "a@example.com" in d
    assert "Fristen und Finanzen" in d
    assert "Zusage für Freitag, 10 Uhr." in d
    assert "Was du geschrieben hast" in d
    assert "x@example.com" in d
    # The noise statistic belongs in the canvas, not in the dossier.
    assert "Lärm" not in d


def test_dossier_of_an_empty_run() -> None:
    d = dossier(_leerer_report(), "2026-09-24")
    assert "_(keine offenen Antworten)_" in d
    assert "_(nichts gesendet)_" in d


def test_dossier_does_not_list_answered_ones_as_open() -> None:
    r = _report()
    r.needs_reply[0].answered = True
    d = dossier(r, "2026-09-24")
    assert "_(keine offenen Antworten)_" in d


# ---------------------------------------------------------------------------
# Absolute dates — the dossier is read again weeks later
# ---------------------------------------------------------------------------


def _dated_report() -> InboxScanReport:
    """A report with a real window and a dated reply."""
    return InboxScanReport(
        window_days=1,
        window_start=date(2026, 9, 22),
        window_end=date(2026, 9, 23),
        inbox_found=1,
        skipped_no_messages=0,
        own_replies=0,
        pages=1,
        needs_reply=[
            ReplyItem(
                sender="a@example.com",
                subject="Rechnung offen",
                received_on=date(2026, 9, 22),
                urgency="today",
                reasoning="",
                answered=False,
            )
        ],
    )


class TestAbsoluteDates:
    """"heute" is a lie the moment the document is a day old.

    The first real run stored a dossier in which every owed reply said
    "**today**". Read three weeks later through retrieval it claims a deadline
    that passed — and nothing in the text says otherwise.
    """

    def test_an_urgency_is_rendered_with_the_date_it_referred_to(self) -> None:
        text = dossier(_dated_report(), "2026-09-23")
        assert "eingegangen 22.09.2026" in text
        assert "**today**" not in text

    def test_the_window_appears_as_calendar_dates(self) -> None:
        # window_end is exclusive, so a one-day window names ONE day.
        assert "22.09.2026" in report_as_markdown(_dated_report())
        assert "bis" not in report_as_markdown(_dated_report()).splitlines()[0]

    def test_a_multi_day_window_names_both_ends(self) -> None:
        r = _dated_report()
        r.window_days = 3
        r.window_start = date(2026, 9, 20)
        assert "20.09.2026 bis 22.09.2026" in report_as_markdown(r)

    def test_a_report_without_a_window_still_renders(self) -> None:
        # Older stored reports have no window — they must not crash the render.
        assert "1 Tag(e)" in report_as_markdown(_report())


class TestTruncation:
    """A cap that cannot say it bit is a lie — see gmail.gmail_search_threads."""

    def test_a_truncated_run_says_so_in_the_headline(self) -> None:
        r = _dated_report()
        r.truncated = True
        assert "abgeschnitten" in headline(r)

    def test_an_untruncated_run_stays_quiet(self) -> None:
        assert "abgeschnitten" not in headline(_dated_report())
