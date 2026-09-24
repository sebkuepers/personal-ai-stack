"""The parser decides every number downstream — this is its contract.

All fixtures are **constructed**: invented merchants, invented amounts,
invented IBANs. The shapes are taken from the real exports (measured
2026-09-24), the content is not, because this repo is public.

Two properties matter more than the rest:

* **Money is integer cents.** German notation writes 1.234,56 where bunq writes
  1234.56 — read with the wrong switch, a four-figure amount becomes 1,23 € and
  nothing looks broken.
* **A dialect that does not fit throws.** Guessing a column produces a ledger
  that is quietly wrong, and that is worse than no ledger.
"""

from __future__ import annotations

from datetime import date

import pytest

from workflows.finance.statements import (
    StatementError,
    parse_amount,
    parse_date,
    parse_positions,
    parse_quantity,
    parse_text,
)

GIRO = (
    "Buchungstag;Wertstellung;Umsatzart;Buchungstext;Betrag;Währung;IBAN Kontoinhaber;Kategorie\n"
    "10.04.2026;10.04.2026;Lastschrift;Beispielwerke GmbH 04/2026 Rechnung;-1.234,56;EUR;DE00;Wohnen\n"
    "09.04.2026;09.04.2026;Gutschrift;Gehalt April;3.000,00;EUR;DE00;\n"
)
CARD = (
    "Buchungstag;Umsatz;Buchungstext;Betrag;Währung;Betrag Ursprung;"
    "Währung Ursprung;Belastete Kreditkarte;Kategorie\n"
    "11.04.2026;10.04.2026;BEISPIELCAFE 12, BERLIN, DEU;-14,58;EUR;-14,58;EUR;"
    "0000 00XX XXXX 0000;Restaurants & Bars\n"
)
BUNQ = (
    '"Date","Interest Date","Amount","Account","Counterparty","Name","Description"\n'
    '"2026-01-02","2026-02-01","-37.46","NL00000000000000000000","","Beispiel Apotheke",'
    '"Beispiel Apotheke Berlin, DE"\n'
)


class TestAmounts:
    @pytest.mark.parametrize(
        ("raw", "german", "cents"),
        [
            ("-1.234,56", True, -123456),
            ("3.000,00", True, 300000),
            ("-14,58", True, -1458),
            ("0,00", True, 0),
            ("-37.46", False, -3746),
            ("1234.5", False, 123450),
            ("1,200.00", False, 120000),  # bunq writes thousands with a comma
            ("-1,234.56", False, -123456),
            ("+12,00", True, 1200),
        ],
    )
    def test_the_notation_switch_decides_the_magnitude(self, raw, german, cents) -> None:
        assert parse_amount(raw, german=german) == cents

    def test_reading_german_notation_as_english_is_off_by_a_factor_of_a_thousand(self) -> None:
        # The failure this switch exists for: 1.234,56 € silently becomes 1,23 €.
        assert parse_amount("1.234,56", german=True) == 123456
        assert parse_amount("1.234", german=False) == 123

    def test_an_unreadable_amount_throws_instead_of_guessing_zero(self) -> None:
        with pytest.raises(StatementError, match="nicht lesbar|leer"):
            parse_amount("keine Ahnung", german=True)
        with pytest.raises(StatementError, match="leer"):
            parse_amount("   ", german=True)

    def test_three_decimals_are_rounded_not_cut(self) -> None:
        # The depot export states three. Truncating loses a cent per position
        # and the total then never quite matches the broker's.
        assert parse_amount("416,859", german=True) == 41686
        assert parse_amount("147,105", german=True) == 14711


class TestQuantities:
    def test_a_count_keeps_its_precision(self) -> None:
        # Through the money parser 1,128 became 1,12 — and the unrealised gain
        # was then four euros wrong on a position of a hundred and fifty.
        assert parse_quantity("1,128", german=True) == pytest.approx(1.128)
        assert parse_quantity("1.5", german=False) == pytest.approx(1.5)


class TestDates:
    def test_both_notations_are_read(self) -> None:
        assert parse_date("10.04.2026") == date(2026, 4, 10)
        assert parse_date("2026-01-02") == date(2026, 1, 2)

    def test_dates_are_objects_so_sorting_is_chronological(self) -> None:
        # Sorting German dates as TEXT put 31.03. before 01.04. — the first
        # measurement run reported the window as "01.04. → 31.03.".
        dates = sorted([parse_date("01.04.2026"), parse_date("31.03.2026")])
        assert dates[0] == date(2026, 3, 31)

    def test_a_value_date_may_be_the_thirtieth_of_february(self) -> None:
        # Not a defect: German banks book the value date on a 30/360 basis, and
        # the real Commerzbank export carries 30.02.2026. It means end of
        # February, so it is clamped to the last day the month has.
        assert parse_date("30.02.2026", clamp=True) == date(2026, 2, 28)
        assert parse_date("31.04.2026", clamp=True) == date(2026, 4, 30)

    def test_a_booking_date_is_never_clamped(self) -> None:
        # Clamping the BOOKING date would silently put a booking in the wrong
        # month; only the value date is allowed the 30/360 fiction.
        with pytest.raises(StatementError, match="Datum nicht lesbar"):
            parse_date("30.02.2026")

    def test_nonsense_throws(self) -> None:
        with pytest.raises(StatementError, match="Datum nicht lesbar"):
            parse_date("irgendwann")


class TestDialects:
    def test_giro(self) -> None:
        rows = parse_text(GIRO, dialect="commerzbank_giro", account="girokonto")
        assert [r.amount_cents for r in rows] == [-123456, 300000]
        assert rows[0].booked_on == date(2026, 4, 10)
        assert rows[0].bank_category == "Wohnen"  # kept, never trusted
        assert rows[0].source_line == 2

    def test_card_takes_the_merchant_out_of_the_text(self) -> None:
        rows = parse_text(CARD, dialect="commerzbank_card", account="mastercard-gold")
        assert rows[0].counterparty == "BEISPIELCAFE 12"
        assert rows[0].text == "BEISPIELCAFE 12, BERLIN, DEU"  # unabridged

    def test_bunq_has_its_own_counterparty_column(self) -> None:
        rows = parse_text(BUNQ, dialect="bunq", account="haushaltskasse")
        assert rows[0].counterparty == "Beispiel Apotheke"
        assert rows[0].amount_cents == -3746

    def test_a_byte_order_mark_does_not_break_the_dialect_check(self) -> None:
        # All three real exports start with one. Without utf-8-sig the first
        # column is called "﻿Buchungstag" and the check fails for a reason
        # nobody would guess from the message.
        rows = parse_text("﻿" + GIRO, dialect="commerzbank_giro", account="girokonto")
        assert len(rows) == 2

    def test_the_wrong_dialect_names_the_missing_columns(self) -> None:
        with pytest.raises(StatementError, match="Date"):
            parse_text(GIRO, dialect="bunq", account="girokonto")

    def test_an_unknown_dialect_lists_the_known_ones(self) -> None:
        with pytest.raises(StatementError, match="commerzbank_giro"):
            parse_text(GIRO, dialect="sparkasse", account="x")

    def test_empty_lines_are_skipped_not_counted(self) -> None:
        rows = parse_text(GIRO + ";;;;;;;\n", dialect="commerzbank_giro", account="girokonto")
        assert len(rows) == 2


class TestFingerprint:
    def test_the_same_booking_from_two_exports_has_one_identity(self) -> None:
        # The overlap case deduplication exists for: a later export repeats the
        # previous month. Same booking, different file and line.
        first = parse_text(GIRO, dialect="commerzbank_giro", account="girokonto", source="a.csv")
        again = parse_text(GIRO, dialect="commerzbank_giro", account="girokonto", source="b.csv")
        assert first[0].fingerprint() == again[0].fingerprint()

    def test_a_different_amount_is_a_different_booking(self) -> None:
        rows = parse_text(GIRO, dialect="commerzbank_giro", account="girokonto")
        assert rows[0].fingerprint() != rows[1].fingerprint()

    def test_the_same_text_on_another_account_is_not_the_same_booking(self) -> None:
        here = parse_text(GIRO, dialect="commerzbank_giro", account="girokonto")
        there = parse_text(GIRO, dialect="commerzbank_giro", account="zweitkonto")
        assert here[0].fingerprint() != there[0].fingerprint()


DEPOT = (
    "Name,ISIN,WKN,Typ,Anzahl,Kaufpreis,Aktueller Kurs,Aktueller Wert,"
    "Währung,Wechselkurs,Region,Sektor\n"
    'Beispiel AG,DE0000000000,A00000,Aktien,"1,128","109,88","130,36","147,105",'
    'EUR,1,Vereinigte Staaten (USA),Internet-Software\n'
    'Beispiel Gold ETF,JE0000000000,A00001,ETF,"1,121","370,145","371,8","416,859",'
    "EUR,1,Global,Edelmetalle\n"
)


class TestDepot:
    """A depot export is a SNAPSHOT, not a ledger.

    Its shape was measured on 2026-09-24 against the real export: quoted
    fields with a German decimal comma INSIDE the quotes, so the comma is both
    the field separator and the decimal mark and only the quoting keeps them
    apart.
    """

    def test_positions_are_read_with_the_german_decimal_comma(self) -> None:
        rows = parse_positions(DEPOT, as_of=date(2026, 9, 24))
        # Rounded, not truncated: 147,105 -> 14711 and 416,859 -> 41686.
        assert [r.value_cents for r in rows] == [14711, 41686]
        assert rows[0].units == pytest.approx(1.128)

    def test_the_kind_and_the_sector_survive(self) -> None:
        rows = parse_positions(DEPOT, as_of=date(2026, 9, 24))
        assert rows[0].kind == "Aktien"
        assert rows[1].sector == "Edelmetalle"

    def test_the_unrealised_gain_is_value_minus_cost(self) -> None:
        rows = parse_positions(DEPOT, as_of=date(2026, 9, 24))
        # 1.128 units bought at 109,88 = 123,94; now worth 147,105 → +23,16
        assert rows[0].gain_cents == pytest.approx(2318, abs=2)

    def test_a_depot_file_may_not_enter_the_transaction_ledger(self) -> None:
        # Mixing a snapshot into a ledger makes every total wrong, silently.
        with pytest.raises(StatementError, match="kein Buchungsformat"):
            parse_text(DEPOT, dialect="depot", account="depot")

    def test_a_booking_export_is_not_a_depot_export(self) -> None:
        with pytest.raises(StatementError, match="ISIN"):
            parse_positions(GIRO, as_of=date(2026, 9, 24))
