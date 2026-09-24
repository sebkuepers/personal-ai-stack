"""Condensing the ledger — deterministic, no model, no I/O.

Everything here is arithmetic over entries that already have a category. The
numbers in the workbook, in the library summary and in the chat all come from
this one place, so the three can never disagree.

**Transfers never count.** A credit-card collective debit on the current account
and the individual items on the card statement are the same money seen twice;
counting both doubles roughly a fifth of the spending. The same for moving money
between his own accounts. They are kept in the ledger — they happened — and
excluded from every total.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from workflows.finance import config as c
from workflows.finance.models import LedgerEntry, PlanningContext

# Categories that are money moving, not money spent.
NEUTRAL = {"transfer"}


@dataclass
class CategoryTotal:
    category: str
    spent_cents: int = 0
    count: int = 0
    plan_cents: int = 0  # per month, from Project 55

    @property
    def label(self) -> str:
        return c.label(self.category)


@dataclass
class MerchantTotal:
    merchant: str
    spent_cents: int = 0
    count: int = 0
    months: set[tuple[int, int]] = field(default_factory=set)

    @property
    def recurring(self) -> bool:
        """Charged in three separate months — arithmetic, not an opinion."""
        return len(self.months) >= 3


@dataclass
class Report:
    start: date | None
    end: date | None
    months: float
    income_cents: int = 0
    spent_cents: int = 0
    categories: list[CategoryTotal] = field(default_factory=list)
    merchants: list[MerchantTotal] = field(default_factory=list)
    uncategorised: int = 0

    @property
    def balance_cents(self) -> int:
        return self.income_cents + self.spent_cents

    @property
    def monthly_balance_cents(self) -> int:
        return int(self.balance_cents / self.months) if self.months else 0

    def per_month(self, cents: int) -> int:
        return int(cents / self.months) if self.months else 0


def _plan_by_category(context: PlanningContext | None) -> dict[str, int]:
    """His monthly plan, mapped onto the category keys.

    The mapping is the ``rows`` list in ``shared/finance.json`` — the same list
    that documents where each category came from. So the plan comparison uses
    exactly the derivation that is already written down, and a category whose
    rows nobody maintained simply has no plan rather than a wrong one.
    """
    if context is None:
        return {}
    amounts = {
        item.label.lower(): item.monthly_cents
        for section in context.sections
        for item in section.items
        if not item.rollup
    }
    out: dict[str, int] = {}
    for key, entry in c.CATEGORIES.items():
        total = sum(amounts.get(row.lower(), 0) for row in entry.get("rows", []))
        if total:
            out[key] = total
    return out


def build(entries: list[LedgerEntry], context: PlanningContext | None = None) -> Report:
    """The whole picture from the ledger."""
    dated = [e for e in entries if e.booked_on]
    if not dated:
        return Report(start=None, end=None, months=0)
    start, end = min(e.booked_on for e in dated), max(e.booked_on for e in dated)
    months = max((end - start).days / 30.44, 1 / 30.44)

    plan = _plan_by_category(context)
    report = Report(start=start, end=end, months=months)
    by_category: dict[str, CategoryTotal] = {}
    by_merchant: dict[str, MerchantTotal] = {}

    for entry in entries:
        if not entry.category:
            report.uncategorised += 1
            continue
        if entry.category in NEUTRAL:
            continue
        if entry.amount_cents > 0:
            report.income_cents += entry.amount_cents
            continue

        report.spent_cents += entry.amount_cents
        total = by_category.setdefault(
            entry.category,
            CategoryTotal(entry.category, plan_cents=plan.get(entry.category, 0)),
        )
        total.spent_cents += entry.amount_cents
        total.count += 1

        name = entry.merchant or entry.text[:28]
        merchant = by_merchant.setdefault(name, MerchantTotal(name))
        merchant.spent_cents += entry.amount_cents
        merchant.count += 1
        merchant.months.add((entry.booked_on.year, entry.booked_on.month))

    report.categories = sorted(by_category.values(), key=lambda t: t.spent_cents)
    report.merchants = sorted(by_merchant.values(), key=lambda m: m.spent_cents)
    return report


def month_slice(entries: list[LedgerEntry], year: int, month: int) -> list[LedgerEntry]:
    return [e for e in entries if e.booked_on.year == year and e.booked_on.month == month]


def months_in(entries: list[LedgerEntry]) -> list[tuple[int, int]]:
    """Every month the ledger covers, oldest first."""
    return sorted({(e.booked_on.year, e.booked_on.month) for e in entries})


def subscriptions(report: Report, minimum: int = 3) -> list[MerchantTotal]:
    """Merchants charged in ``minimum`` separate months.

    Deliberately not the agent's ``recurring`` flag: that is one model's opinion
    about one booking, while this is a fact about the ledger. The two are
    compared in the report — where they disagree is where to look.
    """
    return [m for m in report.merchants if len(m.months) >= minimum]


def flagged_by_model(entries: list[LedgerEntry]) -> Counter[str]:
    """What the agent itself called recurring, per merchant."""
    return Counter(e.merchant for e in entries if e.recurring and e.merchant)
