"""The report as Markdown — for the canvas, the chat and the library dossier.

Pure rendering, no I/O: the same report instance is shown as a canvas in the
conversation, summarised in the chat and stored as a dossier in the library —
one cut, three recipients, no drift.

The rendered text is German: the author reads it, and so does Vibe when it
works with him.
"""

from __future__ import annotations

from workflows.inbox.models import InboxScanReport


def _table(rows: list[list[str]]) -> str:
    """A Markdown table with a header row."""
    if not rows:
        return "_(nichts)_"
    head, rest = rows[0], rows[1:]
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    out += ["| " + " | ".join(r) + " |" for r in rest]
    return "\n".join(out)


def headline(r: InboxScanReport) -> str:
    """The summary for the chat — short; the detail is in the canvas."""
    parts = [f"**{r.inbox_found} Mails** in {r.window_days} Tag(en) gesichtet"]
    if r.skipped_no_messages:
        parts.append(f"{r.skipped_no_messages} ohne Umschlag übersprungen")
    if r.own_replies:
        parts.append(f"{r.own_replies} eigene Antworten")
    if r.second_review_count:
        parts.append(f"{r.second_review_count}× Zweitblick ({r.second_review_changed} geändert)")
    open_replies = [a for a in r.needs_reply if not a.answered]
    if open_replies:
        parts.append(f"**{len(open_replies)} Antwort(en) erwartet**")
    return " · ".join(parts)


def report_as_markdown(r: InboxScanReport) -> str:
    """The full report as a Markdown document — canvas and dossier."""
    lines: list[str] = [f"# Inbox · Sichtung ({r.window_days} Tage)"]
    lines += ["", headline(r), ""]

    lines += ["## Dringend — Antwort erwartet", ""]
    if r.needs_reply:
        for a in r.needs_reply:
            check = " ✓ beantwortet" if a.answered else ""
            lines.append(f"- **{a.urgency}** · {a.sender} — *{a.subject}*{check}")
    else:
        lines.append("_(keine)_")
    lines.append("")

    lines += ["## Finanzen", ""]
    if r.finance:
        lines += [
            "",
            _table(
                [["Absender", "Art", "Betrag", "Fälligkeit", "Betreff"]]
                + [
                    [f.sender, f.kind, f.amount or "—", f.due_date or "—", f.subject]
                    for f in r.finance
                ]
            ),
        ]
    else:
        lines.append("_(keine)_")
    lines.append("")

    lines += ["## Lärm nach Absender-Gruppe", ""]
    lines += [
        _table([["Gruppe", "Mails"]] + [[g, str(n)] for g, n in r.subscription_groups.items()])
    ]
    lines.append("")

    lines += ["## Typen", ""]
    lines += [_table([["Typ", "Mails"]] + [[t, str(n)] for t, n in r.type_counts.items()])]
    lines.append("")

    lines += ["## Abbestell-Kandidaten", ""]
    if r.unsub_links:
        lines += [
            _table(
                [["Absender", "Abmeldelink"]]
                + [[u.sender, f"[Abmelden]({u.url})"] for u in r.unsub_links]
            )
        ]
    else:
        lines.append("_(keine Links gefunden)_")
    lines.append("")

    lines += ["## Kontext für Vibe", ""]
    if r.context:
        lines += [f"- {c}" for c in r.context]
    else:
        lines.append("_(nichts)_")
    lines.append("")

    lines += ["## Gesendet im Fenster", ""]
    if r.sent:
        lines += [
            _table(
                [["An", "Betreff", "Datum"]]
                + [[", ".join(s.to), s.subject, str(s.received_on or "")] for s in r.sent]
            )
        ]
    else:
        lines.append("_(nichts gesendet)_")
    return "\n".join(lines)


def dossier(r: InboxScanReport, as_of: str) -> str:
    """The context dossier for the library — cut for Vibe.

    Not a copy of the report: Vibe needs what influences a working session —
    replies owed, deadlines, context, things promised. The noise statistic is
    in the canvas, not in the dossier.
    """
    lines: list[str] = [f"# Inbox · Kontext — Stand {as_of}", ""]
    lines += [headline(r), ""]

    lines += ["## Antworten, die du schuldest", ""]
    open_replies = [a for a in r.needs_reply if not a.answered]
    for a in open_replies:
        lines.append(f"- **{a.urgency}** · {a.sender} — *{a.subject}*")
    if not open_replies:
        lines.append("_(keine offenen Antworten)_")
    lines.append("")

    lines += ["## Fristen und Finanzen", ""]
    for f in r.finance:
        due = f" bis **{f.due_date}**" if f.due_date else ""
        lines.append(f"- {f.kind.capitalize()}{due} · {f.sender} — *{f.subject}*")
    if not r.finance:
        lines.append("_(keine)_")
    lines.append("")

    lines += ["## Was du zugesagt oder erfahren hast", ""]
    for c in r.context:
        lines.append(f"- {c}")
    if not r.context:
        lines.append("_(nichts)_")
    lines.append("")

    lines += ["## Was du geschrieben hast", ""]
    for s in r.sent:
        lines.append(f"- An {', '.join(s.to)}: *{s.subject}* ({s.received_on})")
    if not r.sent:
        lines.append("_(nichts gesendet)_")
    return "\n".join(lines)
