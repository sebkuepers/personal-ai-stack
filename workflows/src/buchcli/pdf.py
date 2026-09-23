"""Manuskript setzen — Typst, gegen das Referenz-PDF kalibriert.

    python -m buchcli.pdf --werk immer-wieder-ruegen
    python -m buchcli.pdf --kapitel 1-3            # nur Kapitel 1 bis 3
    python -m buchcli.pdf --kapitel 1-3 --vergleich  # Seitenzahl gegen die Referenz

Rein lokal und deterministisch: liest Scrivener, schreibt eine Typst-Eingabe,
ruft ``typst compile``. Kein Agent, kein Workflow — hier gibt es nichts zu
entscheiden, nur zu setzen.

Die Maße stehen in ``shared/buch.json`` unter ``satz.format`` und sind aus dem
Referenz-PDF **ausgemessen**, nicht geschätzt. ``--vergleich`` hält das Ergebnis
dagegen: Gleiche Seitenzahl bei gleichem Kapitelbereich heißt, der Satzspiegel
stimmt.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from workflows.buch import config as c
from workflows.buch.scrivener import lies_binder

TEMPLATE = Path(__file__).parent.parent / "workflows" / "buch" / "satz" / "manuskript.typ"

MONATE = [
    "Januar", "Februar", "März", "April", "Mai", "Juni",
    "Juli", "August", "September", "Oktober", "November", "Dezember",
]


def deutsches_datum(d: date) -> str:
    return f"{d.day}. {MONATE[d.month - 1]} {d.year}"


def kapitelbereich(argument: str | None, alle: list[str]) -> list[str]:
    """``1-3`` oder ``4`` oder nichts (= alle) auf Kapitelnamen abbilden."""
    if not argument:
        return alle
    if "-" in argument:
        von, bis = (int(x) for x in argument.split("-", 1))
    else:
        von = bis = int(argument)
    return alle[von - 1 : bis]


def baue_daten(slug: str, kapitel_namen: list[str], *, trenner_regel: str) -> dict:
    """Die Eingabe für das Typst-Template — alles Nötige, nichts darüber hinaus."""
    werk = c.lade_werk(slug)
    struktur = werk.get("struktur") or {}
    m = lies_binder(
        c.scrivener_pfad(slug),
        slug,
        wurzel=struktur.get("wurzel"),
        kapitel_ebene=struktur.get("kapitel_ebene", 0),
    )

    kapitel = []
    for nummer, name in enumerate(kapitel_namen, start=1):
        drin = [a for a in m.abschnitte if a.hat_text and a.kapitel == name]
        konf = c.kapitel_nach_titel(slug, name) or {}
        abschnitte = []
        vorige_gruppe: tuple[str, ...] | None = None
        for i, a in enumerate(drin):
            gruppe = tuple(a.pfad[1:2])
            # Wann ein Trenner steht, ist eine typografische Entscheidung des
            # Autors und aus der Referenz nicht ableitbar (15 Trenner bei 37
            # Übergängen, ohne erkennbare Regel). Deshalb Einstellung statt
            # Vermutung.
            trenner = {
                "alle": i > 0,
                "gruppen": i > 0 and gruppe != vorige_gruppe,
                "keine": False,
            }[trenner_regel]
            vorige_gruppe = gruppe
            abschnitte.append(
                {"titel": a.titel, "absaetze": a.absaetze, "trenner_davor": trenner}
            )
        kapitel.append(
            {
                "nummer": nummer,
                "titel": name,
                "untertitel": konf.get("untertitel", ""),
                "abschnitte": abschnitte,
            }
        )

    woerter = sum(
        len(p.split()) for k in kapitel for a in k["abschnitte"] for p in a["absaetze"]
    )
    umfang = (
        f"Kapitel {kapitel[0]['nummer']} bis {kapitel[-1]['nummer']}"
        if len(kapitel) > 1
        else f"Kapitel {kapitel[0]['nummer']}"
    )
    return {
        "werk": {
            "titel": werk["titel"],
            "untertitel": werk.get("untertitel", ""),
            "autor": werk.get("autor", ""),
        },
        "satz": c.SATZ["format"],
        "kapitel": kapitel,
        "stand": deutsches_datum(date.today()),
        "umfang_text": umfang,
        "woerter": woerter,
    }


def seiten(pdf: Path) -> int | None:
    """Seitenzahl eines PDFs über ``pdfinfo`` — None, wenn es das nicht gibt."""
    try:
        out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return None
    for zeile in out.splitlines():
        if zeile.startswith("Pages:"):
            return int(zeile.split()[-1])
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Manuskript als PDF setzen.")
    p.add_argument("--werk", default="immer-wieder-ruegen")
    p.add_argument("--kapitel", help="z. B. 1-3 oder 4; ohne Angabe alle")
    p.add_argument("--trenner", choices=["alle", "gruppen", "keine"],
                   help="überschreibt satz.format.trenner_zwischen")
    p.add_argument("--vergleich", action="store_true",
                   help="Seitenzahl gegen das Referenz-PDF halten")
    args = p.parse_args(argv)

    if not TEMPLATE.is_file():
        print(f"Template fehlt: {TEMPLATE}", file=sys.stderr)
        return 1

    werk = c.lade_werk(args.werk)
    struktur = werk.get("struktur") or {}
    m = lies_binder(
        c.scrivener_pfad(args.werk),
        args.werk,
        wurzel=struktur.get("wurzel"),
        kapitel_ebene=struktur.get("kapitel_ebene", 0),
    )
    namen = kapitelbereich(args.kapitel, m.kapitel)
    if not namen:
        print(f"Kein Kapitel für {args.kapitel!r} — vorhanden: {', '.join(m.kapitel)}",
              file=sys.stderr)
        return 1

    regel = args.trenner or c.SATZ["format"].get("trenner_zwischen", "gruppen")
    daten = baue_daten(args.werk, namen, trenner_regel=regel)

    ziel_ordner = c.werk_pfad(args.werk, "pdf")
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    kennung = args.kapitel.replace("-", "bis") if args.kapitel else "alle"

    # Typst löst Pfade RELATIV ZUM TEMPLATE auf und verweigert alles außerhalb
    # seiner Wurzel. Statt mit --root am Dateisystem zu rütteln, wird in einem
    # eigenen Bauordner gearbeitet: Template und Daten liegen dort nebeneinander,
    # und die Wurzel ist genau dieser Ordner. Nebeneffekt: Man kann nach einem
    # Fehlschlag hineinschauen und `typst compile` von Hand wiederholen.
    bau = ziel_ordner / ".bau"
    bau.mkdir(exist_ok=True)
    (bau / "manuskript.typ").write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    json_pfad = bau / "daten.json"
    json_pfad.write_text(json.dumps(daten, ensure_ascii=False), encoding="utf-8")
    pdf_pfad = ziel_ordner / f"{args.werk}-{kennung}-{date.today().isoformat()}.pdf"

    print(f"{werk['titel']} · {len(namen)} Kapitel · {daten['woerter']:,} Wörter"
          .replace(",", "."))
    print(f"  Trenner zwischen: {regel}")

    lauf = subprocess.run(
        ["typst", "compile", "--root", str(bau), "--input", "daten=daten.json",
         str(bau / "manuskript.typ"), str(pdf_pfad)],
        capture_output=True, text=True,
    )
    if lauf.returncode != 0:
        print(lauf.stderr.strip()[:3000], file=sys.stderr)
        return 1

    n = seiten(pdf_pfad)
    print(f"  → {pdf_pfad}  ({n} Seiten)" if n else f"  → {pdf_pfad}")

    if args.vergleich:
        referenz = c.werk_pfad(args.werk, "werk") / c.SATZ["referenz_pdf"]
        r = seiten(referenz)
        if r is None:
            print(f"  Referenz nicht lesbar: {referenz}")
        elif n is None:
            print("  pdfinfo fehlt — kein Vergleich möglich")
        else:
            d = n - r
            urteil = "gleich" if d == 0 else f"{d:+d} Seiten"
            print(f"  Referenz: {r} Seiten · unser Satz: {n} · {urteil}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
