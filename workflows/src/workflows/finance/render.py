"""Rendering finance context as Markdown — pure, no I/O.

The overview is the document that makes Vibe useful *before* a single booking
has been read: what he plans to spend, what he subscribes to, what he wants to
save, and what he actually holds. It carries **no transaction, no account
number, no balance** — which is why it is also the one document here that is
harmless to put in a library.

German, because he reads it, and because Vibe answers him in German.
"""

from __future__ import annotations

from datetime import date

from workflows.finance.models import PlanningContext, Position


def euro(cents: int) -> str:
    """1234567 → '12.345,67 €' — German notation, the way he reads numbers."""
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    return f"{sign}{whole:,}".replace(",", ".") + f",{rest:02d} €"


def _plan(ctx: PlanningContext) -> list[str]:
    lines = ["## Was ich plane", ""]
    lines.append(f"**{euro(ctx.monthly_total_cents)} im Monat** — seine eigene Summe aus der Mappe.")
    lines.append("")
    for section in ctx.sections:
        if section.title.lower() == "kleinstausgaben":
            continue  # listed in full under the subscriptions below
        real = [i for i in section.items if not i.rollup]
        rolled = [i for i in section.items if i.rollup]
        if real:
            items = " · ".join(f"{i.label} {euro(i.monthly_cents)}" for i in real)
            lines.append(f"- **{section.title}** — {items}")
        for item in rolled:
            lines.append(
                f"- **{item.label}** — {euro(item.monthly_cents)} "
                "_(Summe eines anderen Blocks, keine eigene Ausgabe)_"
            )
    return lines


def _subscriptions(ctx: PlanningContext) -> list[str]:
    lines = ["", "## Abos", ""]
    if not ctx.subscriptions:
        lines.append("_(keine in der Mappe)_")
        return lines
    lines.append(
        f"{len(ctx.subscriptions)} Stück, zusammen **{euro(ctx.subscriptions_total_cents)} im Monat**."
    )
    lines.append("")
    for item in sorted(ctx.subscriptions, key=lambda i: -i.monthly_cents):
        lines.append(f"- {item.label} — {euro(item.monthly_cents)} ({euro(item.yearly_cents)}/Jahr)")
    if ctx.cuttable_cents:
        lines += ["", f"Als kürzbar markiert: **{euro(ctx.cuttable_cents)} im Monat**."]
    return lines


def _goals(ctx: PlanningContext) -> list[str]:
    lines = ["", "## Ziele", ""]
    lines.append(f"- Notgroschen: **{euro(ctx.emergency_fund_cents)}**")
    lines.append(f"- Sparrate laut Mappe: **{euro(ctx.savings_rate_cents)} im Monat**")
    if ctx.savings_rate_cents == 0:
        # Stated, not glossed over: it is the most consequential number in the
        # workbook and it is zero.
        lines.append(
            "  — steht auf null. Das ist keine fehlende Angabe, sondern der Stand."
        )
    if ctx.savings_potential_cents:
        lines.append(
            f"- Sparpotential, das er selbst sieht: **{euro(ctx.savings_potential_cents)} im Monat**"
        )
    return lines


def _depot(positions: list[Position]) -> list[str]:
    lines = ["", "## Depot", ""]
    if not positions:
        lines.append("_(kein Auszug vorhanden)_")
        return lines
    # A position with no units and no value is not a holding — it is something
    # he watches. The broker exports it all the same, and dropping it would
    # throw away a statement of intent; listing it as "0,00 €" would be noise.
    watched = [p for p in positions if p.units == 0 and p.value_cents == 0]
    positions = [p for p in positions if p not in watched]
    total = sum(p.value_cents for p in positions)
    cost = sum(round(p.units * p.buy_price_cents) for p in positions)
    as_of = next((p.as_of for p in positions if p.as_of), None)
    lines.append(
        f"**{euro(total)}** in {len(positions)} Positionen"
        + (f", Stand {as_of:%d.%m.%Y}" if as_of else "")
        + f". Einstand {euro(cost)}, also {euro(total - cost)}."
    )
    lines.append("")
    lines.append(
        "Das ist der **Bestand**, nicht die Absicht. Die Absicht steht in "
        "`anlagestrategie.md` in derselben Library — Zielzahl, Portfoliostruktur, "
        "Crash- und Regimewechsel-Regeln. Das alte Zielportfolio-Blatt in der "
        "Planungsmappe ist überholt und wird hier nicht gelesen."
    )
    lines.append("")
    for kind in sorted({p.kind for p in positions}):
        subset = [p for p in positions if p.kind == kind]
        share = sum(p.value_cents for p in subset) * 100 // max(total, 1)
        lines.append(f"### {kind} — {euro(sum(p.value_cents for p in subset))} ({share} %)")
        for position in sorted(subset, key=lambda p: -p.value_cents):
            region = f" · {position.region}" if position.region else ""
            lines.append(f"- {position.name} — {euro(position.value_cents)}{region}")
        lines.append("")
    if watched:
        lines.append("### Beobachtet (nicht im Bestand)")
        for position in watched:
            lines.append(f"- {position.name}" + (f" · {position.sector}" if position.sector else ""))
        lines.append("")
    return lines


def overview(ctx: PlanningContext, positions: list[Position], as_of: date) -> str:
    """The standing picture: plan, subscriptions, goals, portfolio. No bookings."""
    lines = [
        f"# Finanzen · Rahmen — Stand {as_of:%d.%m.%Y}",
        "",
        "Was ich mir vorgenommen habe und was ich halte. **Keine einzelnen Buchungen** — "
        "die bleiben auf dem Rechner.",
        "",
        f"Quelle: `{ctx.source}`" + (f", gelesen am {ctx.read_on:%d.%m.%Y}" if ctx.read_on else ""),
        "",
    ]
    lines += _plan(ctx)
    lines += _subscriptions(ctx)
    lines += _goals(ctx)
    lines += _depot(positions)
    return "\n".join(lines).rstrip() + "\n"
