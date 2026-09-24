"""Das Rendern des Reports ist reines Markdown — dieselbe Instanz geht an
canvas, chat and library. A rendering mistake here distorts all three.

Der Langweilfall ist dabei: Ein leerer Report darf keine leeren
Markdown sections with broken tables — "_(nichts)_" is the
ehrliche Form.
"""

from __future__ import annotations

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
