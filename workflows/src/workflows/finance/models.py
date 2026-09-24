"""Pydantic models for the finance domain.

**Money is integer cents, never a float.** ``0.1 + 0.2`` is not ``0.3``, and a
budget that is off by a cent per booking is off by two euros a month and
unexplainable. Parsing turns "-1.234,56" into ``-123456`` once, at the edge, and
everything downstream counts integers.

Dates are ``date`` objects, never strings. The first measurement run sorted
German dates as text and reported the window "01.04. → 31.03." — sorting
``"31.03.2026"`` before ``"01.04.2026"`` is exactly what string comparison does.
"""

from __future__ import annotations

import hashlib
from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class Transaction(BaseModel):
    """One booking, as it came out of a statement — not yet categorised.

    ``text`` is what the bank wrote, unabridged: the categorising model reads
    it, and shortening it here would silently cost accuracy later.
    """

    account: str  # the account id from paths.json, e.g. "girokonto"
    booked_on: date
    value_on: date | None = None
    text: str
    counterparty: str = ""  # bunq names it separately; the others only have text
    amount_cents: int  # negative = money left
    currency: str = "EUR"
    bank_category: str = ""  # what the bank itself guessed — kept, never trusted
    source_file: str = ""
    source_line: int = 0

    @property
    def amount(self) -> float:
        """Only for display. Never compute with this."""
        return self.amount_cents / 100

    def fingerprint(self) -> str:
        """Stable identity of a booking, for deduplication.

        Deliberately NOT including the source file or line: the same booking
        appears again when a later export overlaps the previous one, and that
        is the whole case deduplication exists for. Two genuinely identical
        bookings on one day (twice the same coffee) collide — the ledger
        therefore counts occurrences instead of discarding blindly.
        """
        raw = f"{self.account}|{self.booked_on.isoformat()}|{self.amount_cents}|{self.text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class LedgerEntry(Transaction):
    """A booking in the ledger — with its identity and, later, its category."""

    fp: str
    occurrence: int = 1  # 2 = the second identical booking on the same day
    category: str = ""
    subcategory: str = ""
    merchant: str = ""
    recurring: bool = False
    confidence: float = 0.0
    reasoning: str = ""
    categorised_on: date | None = None
    confirmed: bool = False  # he said yes — a later run may not overrule it


class FinanceCategory(BaseModel):
    """Mirrors the answer schema of the Studio agent ``Finance · Categorise``."""

    model_config = ConfigDict(extra="forbid")

    category: str
    subcategory: str = ""  # optional on purpose: often there is nothing finer to say
    merchant: str = Field(description="The counterparty in plain words, e.g. 'Lotto24'")
    recurring: bool
    confidence: float
    # No default. A field with one drops out of the schema's "required" list and
    # the model then simply omits it — repo rule 6, paid for in the book domain.
    # The reasoning is the audit trail; without it a wrong category cannot be
    # argued with.
    reasoning: str = Field(description="One sentence naming the part of the text it was read from")


class Position(BaseModel):
    """One holding from a depot export — a SNAPSHOT, not a booking.

    A statement says what happened; a depot export says what is. Mixing the two
    into one ledger would make every total wrong, so positions live in their own
    file and never touch the transaction ledger.

    Value is integer cents like everything monetary here. ``units`` is not money
    and stays a float — 1,128 shares of something is a quantity, not an amount.
    """

    name: str
    isin: str = ""
    wkn: str = ""
    kind: str = ""  # Aktien | ETF | …, as the broker writes it
    units: float = 0.0
    buy_price_cents: int = 0
    price_cents: int = 0
    value_cents: int = 0
    currency: str = "EUR"
    region: str = ""
    sector: str = ""
    as_of: date | None = None

    @property
    def gain_cents(self) -> int:
        """Unrealised gain — what the position is worth minus what it cost."""
        return self.value_cents - round(self.units * self.buy_price_cents)


class PlanItem(BaseModel):
    """One line of his plan: what he intends to spend on this, per month."""

    label: str
    monthly_cents: int
    rollup: bool = False  # not an expense — the total of another block

    @property
    def yearly_cents(self) -> int:
        return self.monthly_cents * 12


class PlanSection(BaseModel):
    """A heading in his workbook and the items under it — Haus, Autos, Kredite …"""

    title: str
    items: list[PlanItem] = Field(default_factory=list)

    @property
    def monthly_cents(self) -> int:
        return sum(i.monthly_cents for i in self.items)


class PlanningContext(BaseModel):
    """What his planning workbook says. Read only, always.

    This is the context that makes Vibe useful before a single booking has been
    read: what he plans to spend, what he subscribes to, what he wants to save —
    and not one transaction. It is therefore also the harmless half of the
    library, the part that carries no bank data at all.
    """

    sections: list[PlanSection] = Field(default_factory=list)
    subscriptions: list[PlanItem] = Field(default_factory=list)
    monthly_total_cents: int = 0  # HIS "Summe", not my sum
    subscriptions_total_cents: int = 0
    savings_potential_cents: int = 0
    savings_rate_cents: int = 0
    emergency_fund_cents: int = 0
    cuttable_cents: int = 0  # what he himself marked as "Kürzen"
    source: str = ""
    read_on: date | None = None

    @property
    def subscriptions_monthly_cents(self) -> int:
        """Summed from the items — compare against his own total, never replace it."""
        return sum(s.monthly_cents for s in self.subscriptions)
