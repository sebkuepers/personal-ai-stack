"""Die Anweisungen für das Vibe-Projekt eines Werks — erzeugt, nicht gepflegt.

    python -m buchcli.anweisungen --werk immer-wieder-ruegen          # zeigt sie
    python -m buchcli.anweisungen --werk immer-wieder-ruegen --kopieren  # in die Zwischenablage

Ein Vibe-Projekt kennt genau zwei Dinge, die jeden Chat darin prägen: hochgeladene
Dateien und **Anweisungen**. Bibliotheken lassen sich dort nicht anhängen; das
geht nur je Chat über ``+``. Also gehört in die Anweisungen, was in jedem
Gespräch über das Buch gelten soll — und das steht bereits in
``shared/buch/<slug>.json`` und im Stimmprofil. Hier wird es nur zusammengesetzt.

Gepflegt wird es nicht: Ändert sich die Konfiguration oder das Profil, erzeugt
man den Text neu und fügt ihn ein. Eine von Hand gepflegte Kopie wäre in einer
Woche veraltet und würde dann in jedem Chat das Falsche behaupten.

Der Text enthält Werkinhalt (Prüfsteine, Stimme). Er ist für das Vibe-Projekt
bestimmt, nicht für das Repo.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from workflows.buch import config as c
from workflows.buch.models import Stimmprofil

REPO = Path(__file__).resolve().parents[3]


def anweisungen(slug: str) -> str:
    werk = c.lade_werk(slug)
    profil_pfad = REPO / "shared" / "buch" / f"{slug}-stimme.json"
    profil = (
        Stimmprofil.model_validate_json(profil_pfad.read_text(encoding="utf-8"))
        if profil_pfad.is_file()
        else None
    )
    ps = werk.get("pruefsteine") or {}
    er = werk.get("erzaehlregeln") or {}
    formen = ", ".join(sorted(c.GEWOLLTE_UMGANGSSPRACHE))

    teile = [
        f"Dieses Projekt gehört zu meinem Buch „{werk['titel']}“"
        + (f" — {werk['untertitel']}" if werk.get("untertitel") else "")
        + f". Ich bin der Autor. Das Manuskript entsteht in Scrivener; der aktuelle Stand liegt "
        f"als manuskript.md in diesem Projekt oder in der Bibliothek {werk['mistral']['library_name']}.",
        "",
        "## Woran du dich hältst",
        "",
        "- **kennzahlen.md** hat alle Zahlen: Umfang, Kapitel, Status, Etiketten, wo es dünn ist. "
        "Nimm sie von dort und zähle keine Überschriften in manuskript.md — Kapitel, Untergruppen "
        "und Abschnitte sind drei Ebenen und stehen dort alle als Überschrift.",
        "- **rubrik.md** ist mein Maßstab: die zwei Fragen an jedes Kapitel, die Erzählregeln, und "
        "je Kapitel, was es beweisen und tragen muss. Daran wird gemessen, nicht an allgemeiner "
        "Schreiblehre.",
        "- Das Exposé (expose.md) beschreibt, was das Buch werden SOLL. Das Manuskript ist, was es IST. "
        "Verwechsle die beiden nicht: Eine Abweichung vom Exposé ist ein Befund, kein Fehler.",
        "- Der Kapitelplan (kapitelplan.md) ist ein älterer Stand mit Arbeitstiteln. Maßgeblich ist, "
        "was ich dir hier sage, nicht, was dort steht.",
        "",
        "## Wie ich schreibe",
        "",
        f"- Umgangssprache ist gewollt, auch im Erzähltext: {formen}. Das wird nicht korrigiert.",
        "- Figuren sprechen, wie sie sprechen. Direkte Rede wird nicht geglättet.",
        "- Kurze und unvollständige Sätze sind Stilmittel, keine Fehler.",
    ]
    if er.get("perspektive"):
        teile.append(f"- Perspektive: {er['perspektive']}")
    if er.get("prinzip"):
        teile.append(f"- Prinzip des Buchs: {er['prinzip']}")

    if profil and profil.aktive_regeln:
        teile += ["", "## Mein Stimmprofil — beschreibend, keine Vorschriften", ""]
        teile.append(
            "Diese Regeln beschreiben, wie ich schreibe. Sie sind kein Auftrag, meinen Text "
            "„noch mehr so“ zu machen. Ein Text, der ihnen folgt, ist fertig."
        )
        teile.append("")
        for r in profil.aktive_regeln:
            teile.append(f"- **{r.titel}** — {r.regel}")

    if ps.get("erste_frage") or ps.get("zweite_frage"):
        teile += ["", "## Die zwei Fragen an jedes Kapitel", ""]
        for k in ("erste_frage", "zweite_frage"):
            f = ps.get(k) or {}
            if f.get("regel"):
                teile.append(f"- **{f['regel']}**" + (f" {f['erlaeuterung']}" if f.get("erlaeuterung") else ""))

    teile += [
        "",
        "## Was du nicht tust",
        "",
        "- Du schreibst nichts ins Manuskript. Änderungen laufen über die Workflows „Buch · Lektorat“ "
        "und werden von mir freigegeben.",
        "- Du erfindest keine Zitate aus dem Buch. Wenn du eine Stelle meinst, zitiere sie wörtlich "
        "aus manuskript.md oder sag, dass du sie nicht findest.",
        "- Wenn ich frage, wie weit das Buch ist, verweise auf den Workflow „Buch · Übersicht“ — der "
        "liest den aktuellen Stand, die Dateien hier sind so alt wie ihr letzter Upload.",
    ]
    return "\n".join(teile)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vibe-Projekt-Anweisungen erzeugen.")
    p.add_argument("--werk", default="immer-wieder-ruegen")
    p.add_argument("--kopieren", action="store_true", help="in die Zwischenablage (macOS)")
    args = p.parse_args(argv)

    text = anweisungen(args.werk)
    if args.kopieren and sys.platform == "darwin":
        subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)
        print(f"{len(text)} Zeichen in der Zwischenablage — in Vibe: Projekt → Anweisungen → Anpassen.")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
