"""Ein Kapitel gegen seine Rubrik prüfen — Ebene 3.

    python -m buchcli.inhalt --werk immer-wieder-ruegen --kapitel "Voll zur Oma"
    python -m buchcli.inhalt --kapitel "Und jetzt?" --ohne-expose

Schreibt nichts. Das Ergebnis ist eine Liste von Befunden und höchstens fünf
Fragen — die Antwort darauf ist Schreiben, und das tut der Autor.

Voraussetzung: ein laufender Worker (``make start-worker``).
"""

from __future__ import annotations

import argparse

from workflows.buch.models import InhaltBefund

from .lektorat import ausfuehren

ZEICHEN = {"ja": "✓", "teilweise": "~", "nein": "✗", "haelt": "✓", "wackelt": "~", "faellt": "✗"}


def zeige(e: dict) -> None:
    b = InhaltBefund.model_validate(e["befund"])
    print(f"\n{'=' * 74}")
    print(f"INHALT — {e['kapitel']}  ({e['abschnitte']} Abschnitte, {e['woerter']} Wörter)")
    print(f"{'=' * 74}\n")

    print(f"These des Kapitels, aus dem Text gelesen:\n  {b.kapitel_these}\n")

    if b.pruefsteine:
        print("PRÜFSTEINE")
        for p in b.pruefsteine:
            print(f"  {ZEICHEN.get(p.urteil, '?')} {p.frage}")
            print(f"      {p.begruendung}")
            if p.stellen:
                print(f"      Stellen: {', '.join(p.stellen)}")
        print()

    if b.traegt:
        offen = [t for t in b.traegt if t.getragen != "ja"]
        print(f"MUSS TRAGEN — {len(b.traegt) - len(offen)} von {len(b.traegt)} eingelöst")
        for t in b.traegt:
            print(f"  {ZEICHEN.get(t.getragen, '?')} {t.punkt}")
            if t.getragen != "ja":
                print(f"      {t.warum}")
            elif t.abschnitte:
                print(f"      {', '.join(t.abschnitte)}")
        print()

    for titel, eintraege in (("STEHT DRIN, MUSS ABER NICHT", b.zu_viel),
                             ("STREICHKANDIDATEN", b.streichkandidaten)):
        if eintraege:
            print(titel)
            for s in eintraege:
                print(f"  · {s.abschnitt} ({s.umfang})")
                print(f"      {s.grund}")
            print()

    if b.fragen_an_den_autor:
        print("FRAGEN AN DICH")
        for f in b.fragen_an_den_autor:
            print(f"  ? {f}")
        print()

    if e.get("hinweise"):
        print("HINWEISE")
        for h in e["hinweise"]:
            print(f"  · {h}")
        print()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ein Kapitel gegen seine Rubrik prüfen.")
    p.add_argument("--werk", default="immer-wieder-ruegen")
    p.add_argument("--kapitel", required=True)
    p.add_argument("--ohne-expose", action="store_true", help="nur Rubrik und Prüfsteine")
    args = p.parse_args(argv)

    import asyncio

    roh = asyncio.run(
        ausfuehren(
            "buch-inhalt",
            {"werk": args.werk, "kapitel": args.kapitel, "mit_expose": not args.ohne_expose},
        )
    )
    zeige(roh if isinstance(roh, dict) else roh.model_dump())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
