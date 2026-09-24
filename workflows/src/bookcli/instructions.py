"""The instructions for a work's Vibe project — generated, not maintained.

    python -m bookcli.instructions --work immer-wieder-ruegen           # show them
    python -m bookcli.instructions --work immer-wieder-ruegen --copy    # to the clipboard

A Vibe project knows exactly two things that shape every chat inside it:
uploaded files and **instructions**. Libraries cannot be attached there; that
only works per chat via ``+``. So whatever should hold in every conversation
about the book belongs in the instructions — and that already stands in
``shared/book/<slug>.json`` and in the voice profile. Here it is only assembled.

It is not maintained: when the configuration or the profile changes, you
regenerate the text and paste it in. A hand-maintained copy would be stale in a
week and would then assert the wrong thing in every chat.

The text contains the work's content (touchstones, voice). It is meant for the
Vibe project, not for the repo — and it is German, because the project is.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from workflows.book import config as c
from workflows.book.models import VoiceProfile

REPO = Path(__file__).resolve().parents[3]


def instructions(slug: str) -> str:
    work = c.load_work(slug)
    profile_path = REPO / "shared" / "book" / f"{slug}-voice.json"
    profile = (
        VoiceProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))
        if profile_path.is_file()
        else None
    )
    touchstones = work.get("touchstones") or {}
    narrative = work.get("narrative_rules") or {}
    forms = ", ".join(sorted(c.INTENTIONAL_COLLOQUIALISMS))

    parts = [
        f"Dieses Projekt gehört zu meinem Buch „{work['title']}“"
        + (f" — {work['subtitle']}" if work.get("subtitle") else "")
        + f". Ich bin der Autor. Das Manuskript entsteht in Scrivener; der aktuelle Stand liegt "
        f"als manuskript.md in diesem Projekt oder in der Bibliothek "
        f"{work['mistral']['library_name']}.",
        "",
        "## Woran du dich hältst",
        "",
        "- **kennzahlen.md** hat alle Zahlen: Umfang, Kapitel, Status, Etiketten, wo es dünn ist. "
        "Nimm sie von dort und zähle keine Überschriften in manuskript.md — Kapitel, Untergruppen "
        "und Abschnitte sind drei Ebenen und stehen dort alle als Überschrift.",
        "- **rubrik.md** ist mein Maßstab: die zwei Fragen an jedes Kapitel, die Erzählregeln, und "
        "je Kapitel, was es beweisen und tragen muss. Daran wird gemessen, nicht an allgemeiner "
        "Schreiblehre.",
        "- Das Exposé (expose.md) beschreibt, was das Buch werden SOLL. Das Manuskript ist, was es "
        "IST. Verwechsle die beiden nicht: Eine Abweichung vom Exposé ist ein Befund, kein Fehler.",
        "- Der Kapitelplan (kapitelplan.md) ist ein älterer Stand mit Arbeitstiteln. Maßgeblich "
        "ist, was ich dir hier sage, nicht, was dort steht.",
        "",
        "## Wie ich schreibe",
        "",
        f"- Umgangssprache ist gewollt, auch im Erzähltext: {forms}. Das wird nicht korrigiert.",
        "- Figuren sprechen, wie sie sprechen. Direkte Rede wird nicht geglättet.",
        "- Kurze und unvollständige Sätze sind Stilmittel, keine Fehler.",
    ]
    if narrative.get("perspective"):
        parts.append(f"- Perspektive: {narrative['perspective']}")
    if narrative.get("principle"):
        parts.append(f"- Prinzip des Buchs: {narrative['principle']}")

    if profile and profile.active_rules:
        parts += ["", "## Mein Stimmprofil — beschreibend, keine Vorschriften", ""]
        parts.append(
            "Diese Regeln beschreiben, wie ich schreibe. Sie sind kein Auftrag, meinen Text "
            "„noch mehr so“ zu machen. Ein Text, der ihnen folgt, ist fertig."
        )
        parts.append("")
        for r in profile.active_rules:
            parts.append(f"- **{r.title}** — {r.rule}")

    if touchstones.get("first_question") or touchstones.get("second_question"):
        parts += ["", "## Die zwei Fragen an jedes Kapitel", ""]
        for key in ("first_question", "second_question"):
            q = touchstones.get(key) or {}
            if q.get("rule"):
                parts.append(
                    f"- **{q['rule']}**"
                    + (f" {q['explanation']}" if q.get("explanation") else "")
                )

    parts += [
        "",
        "## Was du nicht tust",
        "",
        "- Du schreibst nichts ins Manuskript. Änderungen laufen über die Workflows "
        "„Buch · Lektorat“ und werden von mir freigegeben.",
        "- Du erfindest keine Zitate aus dem Buch. Wenn du eine Stelle meinst, zitiere sie "
        "wörtlich aus manuskript.md oder sag, dass du sie nicht findest.",
        "- Wenn ich frage, wie weit das Buch ist, verweise auf den Workflow „Buch · Übersicht“ — "
        "der liest den aktuellen Stand, die Dateien hier sind so alt wie ihr letzter Upload.",
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vibe-Projekt-Anweisungen erzeugen.")
    p.add_argument("--work", default="immer-wieder-ruegen")
    p.add_argument("--copy", action="store_true", help="in die Zwischenablage (macOS)")
    args = p.parse_args(argv)

    text = instructions(args.work)
    if args.copy and sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
        print(
            f"{len(text)} Zeichen in der Zwischenablage — "
            "in Vibe: Projekt → Anweisungen → Anpassen."
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
