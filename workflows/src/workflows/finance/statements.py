"""Parsing bank statements — pure, no I/O beyond reading the file handed in.

Four dialects, measured against the real exports on 2026-09-24. Three of them
carry bookings; ``depot`` carries holdings and is parsed by a separate function,
because a snapshot and a ledger must never end up in the same total.

``commerzbank_giro``
    ``Buchungstag;Wertstellung;Umsatzart;Buchungstext;Betrag;Währung;IBAN;Kategorie``
    Dates ``DD.MM.YYYY``, amounts German (``-1.234,56``). The Buchungstext is
    one long line that often repeats the amount and an end-to-end reference.

``commerzbank_card``
    ``Buchungstag;Umsatz;Buchungstext;Betrag;Währung;Betrag Ursprung;Währung
    Ursprung;Belastete Kreditkarte;Kategorie``
    Same date and amount format. The text is ``MERCHANT, CITY, COUNTRY`` — the
    commas are harmless because the delimiter is a semicolon.

``bunq``
    ``"Date","Interest Date","Amount","Account","Counterparty","Name","Description"``
    ISO dates, dot-decimal amounts, and the counterparty in its own column.

Two rules the parsers keep:

1. **A dialect that does not fit throws, naming what it expected.** Guessing a
   column produces a ledger that is quietly wrong, and a quietly wrong ledger
   is worse than none.
2. **Money becomes integer cents here and nowhere else.** See ``models``.
"""

from __future__ import annotations

import calendar
import csv
import io
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path

from workflows.finance.models import Position, Transaction


class StatementError(ValueError):
    """The file is not the dialect it was said to be — with what was missing."""


# --------------------------------------------------------------------------- #
# Scalars
# --------------------------------------------------------------------------- #


def _normalise(raw: str, *, german: bool) -> str:
    """The number with a dot as the decimal mark, nothing else changed."""
    text = raw.strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        raise StatementError("Zahl ist leer")
    if german:
        text = text.replace(".", "").replace(",", ".")
    else:
        # The bunq export writes thousands as "1,200.00" — the comma is a
        # separator there, not a decimal mark. Leaving it in made Decimal
        # refuse the value, and only on the four-figure bookings.
        text = text.replace(",", "")
    return text


def parse_amount(raw: str, *, german: bool) -> int:
    """A monetary amount as integer cents.

    German notation uses ``.`` for thousands and ``,`` for decimals, the bunq
    export the other way round. Getting this wrong turns 1.234,56 EUR into
    1,23 EUR without anything looking broken, which is why it is one function
    with one switch rather than a regex per dialect.

    ``Decimal`` rather than float, and ROUNDED rather than truncated: the depot
    export states three decimals (``416,859``), and cutting the third off loses
    a cent per position in a way that only ever shows up as a total that does
    not quite match the broker's.
    """
    text = _normalise(raw, german=german)
    try:
        return int((Decimal(text) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except InvalidOperation as exc:
        raise StatementError(f"Betrag nicht lesbar: {raw!r}") from exc


def parse_quantity(raw: str, *, german: bool) -> float:
    """A COUNT, not an amount — full precision, no cents.

    1,128 shares is a quantity. Read through the money parser it became 1,12,
    and the unrealised gain was then four euros wrong on a position of a
    hundred and fifty.
    """
    text = _normalise(raw, german=german)
    try:
        return float(Decimal(text))
    except InvalidOperation as exc:
        raise StatementError(f"Anzahl nicht lesbar: {raw!r}") from exc


def parse_date(raw: str, *, clamp: bool = False) -> date:
    """``DD.MM.YYYY`` or ``YYYY-MM-DD`` — both appear, both are unambiguous.

    ``clamp`` allows a day that the month does not have. That is not a defect
    in the export: German banks book the value date on a 30/360 basis, so the
    Commerzbank statement really does carry ``30.02.2026``. Clamping it to the
    last day of the month is what the bank means.

    It is allowed for the VALUE date only. A booking date that does not exist
    is a broken file, and swallowing it would put a booking in the wrong month.
    """
    text = raw.strip()
    for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d.%m.%y"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    if clamp:
        match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
        if match:
            day, month, year = (int(g) for g in match.groups())
            if 1 <= month <= 12 and 1 <= day <= 31:
                last = calendar.monthrange(year, month)[1]
                return date(year, month, min(day, last))
    raise StatementError(f"Datum nicht lesbar: {raw!r}")


# --------------------------------------------------------------------------- #
# Dialects
# --------------------------------------------------------------------------- #

REQUIRED: dict[str, tuple[str, ...]] = {
    "commerzbank_giro": ("Buchungstag", "Buchungstext", "Betrag"),
    "commerzbank_card": ("Buchungstag", "Buchungstext", "Betrag"),
    "bunq": ("Date", "Amount", "Description"),
    "depot": ("Name", "ISIN", "Anzahl", "Aktueller Wert"),
}
DELIMITER: dict[str, str] = {
    "commerzbank_giro": ";",
    "commerzbank_card": ";",
    "bunq": ",",
    "depot": ",",
}


def _rows(text: str, dialect: str) -> Iterator[dict[str, str]]:
    # Strip the byte-order mark here rather than only in parse_file: without it
    # the first column is called "\ufeffBuchungstag" and the dialect check
    # fails for a reason nobody would guess from the message. All four real
    # exports carry one.
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter=DELIMITER[dialect])
    fields = [f.strip() for f in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED[dialect] if c not in fields]
    if missing:
        raise StatementError(
            f"Dialekt {dialect!r} passt nicht — es fehlen die Spalten {missing}. "
            f"Gefunden: {fields}"
        )
    for row in reader:
        yield {(k or "").strip(): (v or "").strip() for k, v in row.items()}


def _commerzbank(row: dict[str, str], account: str, card: bool) -> Transaction:
    value_raw = row.get("Wertstellung") or row.get("Umsatz") or ""
    return Transaction(
        account=account,
        booked_on=parse_date(row["Buchungstag"]),
        value_on=parse_date(value_raw, clamp=True) if value_raw else None,
        text=row["Buchungstext"],
        amount_cents=parse_amount(row["Betrag"], german=True),
        currency=row.get("Währung") or "EUR",
        bank_category=row.get("Kategorie", ""),
        counterparty=row["Buchungstext"].split(",")[0].strip() if card else "",
    )


def _bunq(row: dict[str, str], account: str) -> Transaction:
    return Transaction(
        account=account,
        booked_on=parse_date(row["Date"]),
        value_on=parse_date(row["Interest Date"], clamp=True) if row.get("Interest Date") else None,
        text=row["Description"],
        counterparty=row.get("Name") or row.get("Counterparty") or "",
        amount_cents=parse_amount(row["Amount"], german=False),
        currency="EUR",
    )


def parse_positions(text: str, *, as_of: date, source: str = "") -> list[Position]:
    """Parse a depot export — holdings, not bookings.

    Measured against the real export on 2026-09-24:
    ``Name,ISIN,WKN,Typ,Anzahl,Kaufpreis,Aktueller Kurs,Aktueller Wert,Währung,
    Wechselkurs,Region,Sektor``, quoted fields, German decimal comma inside the
    quotes (``"1,128"``, ``"147,105"``) — so the comma is both the field
    separator and the decimal mark, and only the quoting keeps them apart.
    """
    out: list[Position] = []
    for row in _rows(text, "depot"):
        if not row.get("Name"):
            continue
        out.append(
            Position(
                name=row["Name"],
                isin=row.get("ISIN", ""),
                wkn=row.get("WKN", ""),
                kind=row.get("Typ", ""),
                units=parse_quantity(row["Anzahl"], german=True),
                buy_price_cents=parse_amount(row.get("Kaufpreis") or "0", german=True),
                price_cents=parse_amount(row.get("Aktueller Kurs") or "0", german=True),
                value_cents=parse_amount(row["Aktueller Wert"], german=True),
                currency=row.get("Währung") or "EUR",
                region=row.get("Region", ""),
                sector=row.get("Sektor", ""),
                as_of=as_of,
            )
        )
    return out


def parse_text(text: str, *, dialect: str, account: str, source: str = "") -> list[Transaction]:
    """Parse the content of one statement file."""
    if dialect == "depot":
        raise StatementError("Ein Depotauszug ist kein Buchungsformat — parse_positions() benutzen.")
    if dialect not in REQUIRED:
        raise StatementError(f"Unbekannter Dialekt {dialect!r} — bekannt: {sorted(REQUIRED)}")
    out: list[Transaction] = []
    for line_no, row in enumerate(_rows(text, dialect), start=2):  # 1 is the header
        if not any(row.values()):
            continue
        if dialect == "bunq":
            transaction = _bunq(row, account)
        else:
            transaction = _commerzbank(row, account, card=dialect == "commerzbank_card")
        transaction.source_file = source
        transaction.source_line = line_no
        out.append(transaction)
    return out


def parse_file(path: Path, *, dialect: str, account: str) -> list[Transaction]:
    """Parse a statement from disk.

    ``utf-8-sig`` on purpose: all three exports start with a byte-order mark,
    and without stripping it the first column is called ``\\ufeffBuchungstag``
    and the dialect check fails for a reason nobody would guess.
    """
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return parse_text(text, dialect=dialect, account=account, source=path.name)
