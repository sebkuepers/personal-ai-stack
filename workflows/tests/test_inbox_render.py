"""Das Rendern des Reports ist reines Markdown — dieselbe Instanz geht an
Canvas, Chat und Library. Ein Renderfehler hier verfälscht alle drei.

Der Langweilfall ist dabei: Ein leerer Report darf keine leeren
Markdown-Kapitel mit krachenden Tabellen erzeugen — „_(nichts)_" ist die
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
                urgency="today", reasoning="", beantwortet=False,
            )
        ],
        finanzen=[
            FinanceItem(
                sender="a@example.com", subject="Zahlung fehlgeschlagen",
                art="reminder", betrag="89,00 EUR", due_date="2026-09-26",
            )
        ],
        kontext=["Zusage für Freitag, 10 Uhr."],
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


def test_headline_nennen_die_essenzen() -> None:
    text = headline(_report())
    assert "2 Mails" in text
    assert "1× Zweitblick (1 geändert)" in text
    assert "1 Antwort(en) erwartet" in text


def test_headline_leerer_lauf() -> None:
    text = headline(_leerer_report())
    assert "0 Mails" in text
    assert "Antwort" not in text


# ---------------------------------------------------------------------------
# Der volle Report als Markdown (Canvas)
# ---------------------------------------------------------------------------


def test_report_markdown_traegt_alle_abschnitte() -> None:
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


def test_report_markdown_leerer_lauf_ohne_krachende_tabellen() -> None:
    md = report_as_markdown(_leerer_report())
    assert "_(nichts)_" in md
    assert "GitHub" not in md


# ---------------------------------------------------------------------------
# Das Dossier für die Library
# ---------------------------------------------------------------------------


def test_dossier_ist_auf_vibe_zugeschnitten() -> None:
    d = dossier(_report(), "2026-09-24")
    assert "# Inbox · Kontext — Stand 2026-09-24" in d
    assert "Antworten, die du schuldest" in d
    assert "a@example.com" in d
    assert "Fristen und Finanzen" in d
    assert "Zusage für Freitag, 10 Uhr." in d
    assert "Was du geschrieben hast" in d
    assert "x@example.com" in d
    # Die Lärm-Statistik gehört in den Canvas, nicht ins Dossier.
    assert "Lärm" not in d


def test_dossier_leerer_lauf() -> None:
    d = dossier(_leerer_report(), "2026-09-24")
    assert "_(keine offenen Antworten)_" in d
    assert "_(nichts gesendet)_" in d


def test_dossier_nennt_beantwortete_nicht_unter_offen() -> None:
    r = _report()
    r.needs_reply[0].beantwortet = True
    d = dossier(r, "2026-09-24")
    assert "_(keine offenen Antworten)_" in d
