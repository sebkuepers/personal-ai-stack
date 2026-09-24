"""Der Report als Markdown — für Canvas, Chat und das Library-Dossier.

Reines Rendern, kein I/O: Dieselbe Report-Instanz wird im Gespräch als Canvas
gezeigt, im Chat zusammengefasst und als Dossier in die Library gelegt — ein
Zuschnitt, drei Empfänger, keine Drift.
"""

from __future__ import annotations

from workflows.inbox.models import InboxScanReport


def _tabelle(zeilen: list[list[str]]) -> str:
    """Eine Markdown-Tabelle mit Kopfzeile."""
    if not zeilen:
        return "_(nichts)_"
    kopf, rest = zeilen[0], zeilen[1:]
    out = ["| " + " | ".join(kopf) + " |", "|" + "|".join(["---"] * len(kopf)) + "|"]
    out += ["| " + " | ".join(z) + " |" for z in rest]
    return "\n".join(out)


def headline(r: InboxScanReport) -> str:
    """Die Zusammenfassung für den Chat — kurz, das Detail steht im Canvas."""
    teile = [f"**{r.inbox_found} Mails** in {r.window_days} Tag(en) gesichtet"]
    if r.skipped_no_messages:
        teile.append(f"{r.skipped_no_messages} ohne Umschlag übersprungen")
    if r.own_replies:
        teile.append(f"{r.own_replies} eigene Antworten")
    if r.second_review_count:
        teile.append(f"{r.second_review_count}× Zweitblick ({r.second_review_changed} geändert)")
    offen = [a for a in r.needs_reply if not a.beantwortet]
    if offen:
        teile.append(f"**{len(offen)} Antwort(en) erwartet**")
    return " · ".join(teile)


def report_as_markdown(r: InboxScanReport) -> str:
    """Der volle Report als Markdown-Dokument — Canvas und Dossier."""
    z: list[str] = [f"# Inbox · Sichtung ({r.window_days} Tage)"]
    z += ["", headline(r), ""]

    z += ["## Dringend — Antwort erwartet", ""]
    if r.needs_reply:
        for a in r.needs_reply:
            haken = " ✓ beantwortet" if a.beantwortet else ""
            z.append(f"- **{a.urgency}** · {a.sender} — *{a.subject}*{haken}")
    else:
        z.append("_(keine)_")
    z.append("")

    z += ["## Finanzen", ""]
    if r.finanzen:
        z += [
            "",
            _tabelle(
                [["Absender", "Art", "Betrag", "Fälligkeit", "Betreff"]]
                + [
                    [f.sender, f.art, f.betrag or "—", f.due_date or "—", f.subject]
                    for f in r.finanzen
                ]
            ),
        ]
    else:
        z.append("_(keine)_")
    z.append("")

    z += ["## Lärm nach Absender-Gruppe", ""]
    z += [
        _tabelle([["Gruppe", "Mails"]] + [[g, str(n)] for g, n in r.subscription_groups.items()])
        or "_(keine)_"
    ]
    z.append("")

    z += ["## Typen", ""]
    z += [_tabelle([["Typ", "Mails"]] + [[t, str(n)] for t, n in r.type_counts.items()])]
    z.append("")

    z += ["## Abbestell-Kandidaten", ""]
    if r.unsub_links:
        z += [
            _tabelle(
                [["Absender", "Abmeldelink"]]
                + [[u.sender, f"[Abmelden]({u.url})"] for u in r.unsub_links]
            )
        ]
    else:
        z.append("_(keine Links gefunden)_")
    z.append("")

    z += ["## Kontext für Vibe", ""]
    if r.kontext:
        z += [f"- {k}" for k in r.kontext]
    else:
        z.append("_(nichts)_")
    z.append("")

    z += ["## Gesendet im Fenster", ""]
    if r.sent:
        z += [
            _tabelle(
                [["An", "Betreff", "Datum"]]
                + [[", ".join(s.to), s.subject, str(s.received_on or "")] for s in r.sent]
            )
        ]
    else:
        z.append("_(nichts gesendet)_")
    return "\n".join(z)


def dossier(r: InboxScanReport, stand: str) -> str:
    """Das Kontext-Dossier für die Library — auf Vibe zugeschnitten.

    Keine Kopie des Reports: Vibe braucht das, was eine Arbeitssitzung
    beeinflusst — Antworten, Fristen, Kontext, zugesagte Dinge. Die
    Lärm-Statistik steht im Canvas, nicht im Dossier.
    """
    z: list[str] = [f"# Inbox · Kontext — Stand {stand}", ""]
    z += [headline(r), ""]

    z += ["## Antworten, die du schuldest", ""]
    offen = [a for a in r.needs_reply if not a.beantwortet]
    for a in offen:
        z.append(f"- **{a.urgency}** · {a.sender} — *{a.subject}*")
    if not offen:
        z.append("_(keine offenen Antworten)_")
    z.append("")

    z += ["## Fristen und Finanzen", ""]
    for f in r.finanzen:
        frist = f" bis **{f.due_date}**" if f.due_date else ""
        z.append(f"- {f.art.capitalize()}{frist} · {f.sender} — *{f.subject}*")
    if not r.finanzen:
        z.append("_(keine)_")
    z.append("")

    z += ["## Was du zugesagt oder erfahren hast", ""]
    for k in r.kontext:
        z.append(f"- {k}")
    if not r.kontext:
        z.append("_(nichts)_")
    z.append("")

    z += ["## Was du geschrieben hast", ""]
    for s in r.sent:
        z.append(f"- An {', '.join(s.to)}: *{s.subject}* ({s.received_on})")
    if not r.sent:
        z.append("_(nichts gesendet)_")
    return "\n".join(z)
