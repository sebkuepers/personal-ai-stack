"""Build the report: a workbook on disk and the summaries in the library.

    python -m financecli.report            # show the figures
    python -m financecli.report --write    # write Berichte/Finanzbericht.xlsx
    python -m financecli.report --upload   # and put the summaries in the library

**The workbook is generated, never edited.** His own two workbooks —
``finanzen_privat_project55.xlsx`` and ``Telsche_Ausgaben.xlsx`` — are read and
never written; this one is thrown away and rebuilt on every run, which is why it
cannot be damaged and why he should not maintain anything inside it.

Its shape follows his Telsche workbook, because that one works: an overview, the
running costs, the individual items, plan against actual, the subscriptions.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from workflows.finance import config as c
from workflows.finance import ledger, library, project55, render, report
from workflows.finance.models import LedgerEntry

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
DATA = Path(__file__).resolve().parents[2] / "data" / "finance"

EURO = '#,##0.00\\ "€"'


def _sheet_overview(book, rep: report.Report) -> None:
    sheet = book.active
    sheet.title = "Übersicht"
    sheet["A1"] = "Finanzbericht"
    sheet["A2"] = f"{rep.start:%d.%m.%Y} – {rep.end:%d.%m.%Y} ({rep.months:.1f} Monate)"
    sheet["A3"] = "Erzeugt — nicht von Hand bearbeiten. Wird bei jedem Lauf neu gebaut."
    rows = [
        ("Einnahmen", rep.income_cents),
        ("Ausgaben", rep.spent_cents),
        ("Saldo", rep.balance_cents),
        ("Saldo pro Monat", rep.monthly_balance_cents),
    ]
    for index, (label, cents) in enumerate(rows, start=5):
        sheet[f"A{index}"] = label
        sheet[f"B{index}"] = cents / 100
        sheet[f"B{index}"].number_format = EURO
    sheet.column_dimensions["A"].width = 26
    sheet.column_dimensions["B"].width = 16


def _sheet_plan(book, rep: report.Report) -> None:
    sheet = book.create_sheet("Plan und Ist")
    sheet.append(["Kategorie", "Ausgaben", "pro Monat", "Plan pro Monat", "Abweichung", "Buchungen"])
    for total in rep.categories:
        actual = rep.per_month(total.spent_cents)
        sheet.append([
            total.label,
            total.spent_cents / 100,
            actual / 100,
            total.plan_cents / 100 if total.plan_cents else None,
            (abs(actual) - total.plan_cents) / 100 if total.plan_cents else None,
            total.count,
        ])
    for column in "BCDE":
        for cell in sheet[column][1:]:
            cell.number_format = EURO
    sheet.column_dimensions["A"].width = 22
    for column in "BCDE":
        sheet.column_dimensions[column].width = 16


def _sheet_subscriptions(book, rep: report.Report) -> None:
    sheet = book.create_sheet("Abos")
    sheet.append(["Empfänger", "pro Monat", "gesamt", "Buchungen", "Monate"])
    for merchant in report.subscriptions(rep):
        sheet.append([
            merchant.merchant,
            merchant.spent_cents / max(len(merchant.months), 1) / 100,
            merchant.spent_cents / 100,
            merchant.count,
            len(merchant.months),
        ])
    for column in "BC":
        for cell in sheet[column][1:]:
            cell.number_format = EURO
    sheet.column_dimensions["A"].width = 34
    for column in "BC":
        sheet.column_dimensions[column].width = 16


def _sheet_entries(book, entries: list[LedgerEntry]) -> None:
    sheet = book.create_sheet("Positionen")
    sheet.append(["Datum", "Konto", "Kategorie", "Unterkategorie", "Empfänger",
                  "Betrag", "Wiederkehrend", "Begründung", "Text der Bank"])
    for entry in sorted(entries, key=lambda e: (e.booked_on, e.account)):
        sheet.append([
            entry.booked_on, entry.account, c.label(entry.category) if entry.category else "",
            entry.subcategory, entry.merchant, entry.amount_cents / 100,
            "ja" if entry.recurring else "", entry.reasoning, entry.text,
        ])
    for cell in sheet["A"][1:]:
        cell.number_format = "DD.MM.YYYY"
    for cell in sheet["F"][1:]:
        cell.number_format = EURO
    widths = {"A": 12, "B": 20, "C": 16, "D": 18, "E": 28, "F": 14, "G": 14, "H": 46, "I": 60}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width


def write_workbook(entries: list[LedgerEntry], rep: report.Report, target: Path) -> Path:
    """A fresh workbook. Refuses while it is open in Excel."""
    import openpyxl

    from financecli.tidy import is_open

    if target.exists() and is_open(target):
        raise RuntimeError(
            f"{target.name} ist in einer Anwendung geöffnet — Excel schließen und "
            "erneut laufen lassen."
        )  # author-facing: stays German
    book = openpyxl.Workbook()
    _sheet_overview(book, rep)
    _sheet_plan(book, rep)
    _sheet_subscriptions(book, rep)
    _sheet_entries(book, entries)
    target.parent.mkdir(parents=True, exist_ok=True)
    book.save(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finanzbericht bauen.")
    parser.add_argument("--write", action="store_true", help="Arbeitsmappe schreiben")
    parser.add_argument("--upload", action="store_true", help="Zusammenfassungen in die Library")
    args = parser.parse_args(argv)

    entries = ledger.read_all(DATA)
    if not entries:
        print("Ledger ist leer — erst make finance-ingest apply=1.", file=sys.stderr)
        return 1
    try:
        context = project55.read(c.planning_workbook())
    except (FileNotFoundError, project55.PlanningError) as exc:
        print(f"Planung nicht lesbar ({exc}) — Bericht ohne Plan-Vergleich.", file=sys.stderr)
        context = None

    rep = report.build(entries, context)
    print(render.month_summary(rep, "Gesamt"))

    if args.write:
        target = write_workbook(entries, rep, c.folder_of("Berichte") / "Finanzbericht.xlsx")
        print(f"\nArbeitsmappe: {target}", file=sys.stderr)

    if args.upload:
        today = date.today()  # noqa: DTZ011 — local CLI, local clock
        documents = [
            (c.LIBRARY_DOCUMENTS["month"].format(month=f"{today:%Y-%m}"),
             render.month_summary(rep, f"Stand {today:%d.%m.%Y}")),
            (c.LIBRARY_DOCUMENTS["subscriptions"],
             render.subscription_summary(rep, context)),
        ]
        for name, text in documents:
            try:
                result = library.store(name, text)
            except library.LeakError as exc:
                print(f"{name} NICHT hochgeladen: {exc}", file=sys.stderr)
                return 1
            state = "behalten (vorhandenes ist länger)" if result.get("kept") else "abgelegt"
            print(f"{name}: {result.get('skipped') or state}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
