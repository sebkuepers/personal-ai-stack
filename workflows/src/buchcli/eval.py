"""Testfälle für die Buch-Agents erzeugen.

    python -m buchcli.eval --erzeuge            # Fälle aus dem Manuskript bauen
    make buch-eval                              # messen (nutzt evalkit)

Gemessen wird mit dem domänenunabhängigen ``evalkit``; hier steht nur, was am
Buch besonders ist: welche Abschnitte sich als Testfälle eignen und welche
Fallen für dieses Werk gelten.

Die Fälle liegen in ``shared/buch/eval-<slug>.json`` und sind gitignored — sie
enthalten Manuskripttext.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflows.buch import config as c
from workflows.buch.scrivener import lies_binder

REPO = Path(__file__).resolve().parents[3]


def faelle_pfad(slug: str) -> Path:
    return REPO / "shared" / "buch" / f"eval-{slug}.json"


def erzeuge(slug: str, anzahl: int = 6, max_zeichen: int = 1800) -> list[dict]:
    """Baut Testfälle aus echten Abschnitten und setzt die bekannten Fallen.

    **Fallen werden automatisch gesetzt, Erwartungen nicht.** Die Fallen stammen
    aus beobachtetem Fehlverhalten und aus der Liste geschützter Umgangssprache
    in ``shared/buch.json`` — beides ist belastbar. Welche Stelle dagegen ein
    echter Fehler ist, kann nur der Autor entscheiden; geratene Erwartungen wären
    schlimmer als keine, weil sie eine Messung vortäuschen.

    Bevorzugt werden Abschnitte mit Umgangssprache und direkter Rede: Dort
    entscheidet sich, ob ein Agent die Stimme respektiert oder glattbügelt.
    """
    werk = c.lade_werk(slug)
    struktur = werk.get("struktur") or {}
    m = lies_binder(
        c.scrivener_pfad(slug),
        slug,
        wurzel=struktur.get("wurzel"),
        kapitel_ebene=struktur.get("kapitel_ebene", 0),
    )
    mit_text = [a for a in m.abschnitte if a.hat_text]

    def punkte(a) -> int:  # noqa: ANN001
        t = a.text.lower()
        return sum(1 for w in c.GEWOLLTE_UMGANGSSPRACHE if f" {w} " in t) + t.count("„")

    faelle = []
    for a in sorted(mit_text, key=punkte, reverse=True)[:anzahl]:
        # Fälle bewusst kurz halten: Ein Eval, das Minuten braucht, wird nicht
        # benutzt. Absätze aufnehmen, bis das Budget erreicht ist — die mit
        # Fallen zuerst, damit sie garantiert drin sind.
        mit_falle = [
            p for p in a.absaetze
            if any(f" {w} " in p.lower() for w in c.GEWOLLTE_UMGANGSSPRACHE) or "„" in p
        ]
        gewaehlt, laenge = [], 0
        for p in (mit_falle + [x for x in a.absaetze if x not in mit_falle]):
            if laenge + len(p) > max_zeichen and gewaehlt:
                break
            gewaehlt.append(p)
            laenge += len(p)
        gewaehlt = [p for p in a.absaetze if p in gewaehlt]  # Originalreihenfolge
        absatzblock = "\n\n".join(f"[{i}] {p}" for i, p in enumerate(gewaehlt))

        verboten = [
            {
                "pfad": "korrekturen[].search",
                "operator": "paar",
                "paar_pfad": "korrekturen[].replace",
                "wert": [wort, ersatz],
                "hinweis": "gewollte Umgangssprache (shared/buch.json)",
            }
            for wort, ersatz in c.GEWOLLTE_UMGANGSSPRACHE.items()
            if f" {wort} " in absatzblock.lower()
        ]

        faelle.append(
            {
                "id": a.titel[:30],
                "quelle": "manuskript",
                "_uuid": a.uuid,
                "eingabe": f"ABSCHNITT: {a.titel}\n\n--- ABSÄTZE ---\n{absatzblock}",
                "erwartet": [],
                "verboten": verboten,
                "notiz": (
                    "erwartet[] von Hand füllen — echte Fehler, die gefunden werden MÜSSEN. "
                    'Format: {"pfad": "korrekturen[].search", "wert": "der fehlerhafte Text"}'
                ),
            }
        )
    return faelle


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Testfälle für die Buch-Agents erzeugen.")
    p.add_argument("--werk", default="immer-wieder-ruegen")
    p.add_argument("--anzahl", type=int, default=6)
    p.add_argument("--max-zeichen", type=int, default=1800,
                   help="Obergrenze je Fall — kurze Fälle halten das Eval benutzbar")
    p.add_argument("--erzeuge", action="store_true", help="Fälle neu bauen (überschreibt)")
    args = p.parse_args(argv)

    pfad = faelle_pfad(args.werk)
    if not args.erzeuge:
        if pfad.is_file():
            faelle = json.loads(pfad.read_text(encoding="utf-8"))
            erw = sum(len(f.get("erwartet", [])) for f in faelle)
            verb = sum(len(f.get("verboten", [])) for f in faelle)
            print(f"{len(faelle)} Fälle · {erw} Erwartungen · {verb} Fallen  →  {pfad.name}")
            print(f"\nMessen:  python -m evalkit --agent buch-korrektorat --faelle {pfad.relative_to(REPO)}")
        else:
            print(f"Keine Fälle vorhanden. Erzeugen mit: {p.prog} --erzeuge")
        return 0

    faelle = erzeuge(args.werk, args.anzahl, args.max_zeichen)
    pfad.write_text(json.dumps(faelle, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verb = sum(len(f["verboten"]) for f in faelle)
    print(f"{len(faelle)} Fälle → {pfad.relative_to(REPO)}")
    print(f"  {verb} Fallen automatisch gesetzt, 0 Erwartungen.")
    print("  → erwartet[] von Hand füllen; das Urteil, was ein Fehler ist, gehört dir.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
