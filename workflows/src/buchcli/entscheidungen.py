"""Das Entscheidungslog lesen und auszählen.

    python -m buchcli.entscheidungen --werk immer-wieder-ruegen           # Bilanz je Regel
    python -m buchcli.entscheidungen --werk immer-wieder-ruegen --letzte 20
    python -m buchcli.entscheidungen --werk immer-wieder-ruegen --eval shared/buch/eval-aus-log.json

``--eval`` macht aus den Entscheidungen des Autors Testfälle für ``evalkit``:
Jeder abgelehnte Stilvorschlag wird eine Falle, jeder angenommene eine Erwartung.
Das ist der Punkt, an dem die Evals aufhören, meine Konstruktionen zu sein, und
anfangen, sein Urteil zu tragen.

Die Datei landet NICHT im Repo — sie enthält Manuskripttext. ``shared/buch/*.json``
ist ohnehin gitignored; nur die ausdrücklich freigegebenen Eval-Dateien sind
ausgenommen, und diese gehört nicht dazu.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from workflows.buch import entscheidungen as log

DATEN = Path(__file__).resolve().parents[2] / "data"


def als_eval(zeilen: list[dict], *, ebene: str, werk: str) -> list[dict]:
    """Testfälle aus Entscheidungen — gruppiert je Abschnitt und Sitzung.

    Ein Fall je (Sitzung, Abschnitt). Die **Eingabe** wird so nachgebaut, wie sie
    der Agent bekam: Abschnittstext aus Scrivener (Stand jetzt — der Text kann
    sich seit der Sitzung geändert haben, dann greifen die Anker nicht mehr, und
    der Fall wird ausgelassen), beim Stil dazu das aktuelle Stimmprofil.

    Fallen sind die abgelehnten Vorschläge (Suchtext → Ersatz), Erwartungen die
    angenommenen. Damit tragen die Evals zum ersten Mal SEIN Urteil, nicht meins.
    """
    from workflows.buch import config as c
    from workflows.buch.scrivener import lies_binder

    from .lektorat import stimmprofil_text

    w = c.lade_werk(werk)
    struktur = w.get("struktur") or {}
    m = lies_binder(
        c.scrivener_pfad(werk), werk,
        wurzel=struktur.get("wurzel"), kapitel_ebene=struktur.get("kapitel_ebene", 0),
    )
    nach_uuid = {a.uuid: a for a in m.abschnitte if a.hat_text}
    profil = stimmprofil_text(werk) if ebene == "stil" else ""

    def eingabe_fuer(a) -> str:  # noqa: ANN001
        block = "\n\n".join(f"[{i}] {t}" for i, t in enumerate(a.absaetze))
        if ebene == "stil":
            return (
                f"HÖCHSTENS 12 VORSCHLÄGE.\n\n=== STIMMPROFIL DES AUTORS ===\n{profil}\n\n"
                f"=== ABSCHNITT: {a.titel} ===\n{block}"
            )
        return f"ABSCHNITT: {a.titel}\n\n--- ABSÄTZE ---\n{block}"
    gruppen: dict[tuple[str, str], list[dict]] = {}
    for z in zeilen:
        if z.get("ebene") != ebene:
            continue
        gruppen.setdefault((z["sitzung"], z["abschnitt_uuid"]), []).append(z)

    faelle = []
    for (sitzung, uuid), eintraege in gruppen.items():
        a = nach_uuid.get(uuid)
        if a is None:
            continue
        # Nur Entscheidungen, deren Anker noch im heutigen Text sitzt. Was der
        # Autor seit der Sitzung umgeschrieben hat, ist kein Testfall mehr.
        eintraege = [z for z in eintraege if any(z["search"] in p for p in a.absaetze)]
        verboten = [
            {
                "pfad": "vorschlaege[].search",
                "operator": "paar",
                "paar_pfad": "vorschlaege[].replace",
                "wert": [z["search"], z["replace"]],
                "hinweis": z.get("grund") or "abgelehnt",
            }
            for z in eintraege
            if z["entscheidung"] == "abgelehnt"
        ]
        erwartet = [
            {"pfad": "vorschlaege[].search", "wert": z["search"]}
            for z in eintraege
            if z["entscheidung"] == "angenommen"
        ]
        if not verboten and not erwartet:
            continue
        faelle.append(
            {
                "id": f"{eintraege[0]['abschnitt']}-{sitzung[:8]}",
                "quelle": "entscheidungslog",
                "notiz": (
                    f"{len(erwartet)} angenommen, {len(verboten)} abgelehnt — "
                    f"Sitzung {sitzung[:8]}, {eintraege[0]['ts'][:10]}"
                ),
                "abschnitt_uuid": uuid,
                "eingabe": eingabe_fuer(a),
                "erwartet": erwartet,
                "verboten": verboten,
            }
        )
    return faelle


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Entscheidungslog lesen und auszählen.")
    p.add_argument("--werk", default="immer-wieder-ruegen")
    p.add_argument("--ebene", default="stil", choices=["korrektorat", "stil"])
    p.add_argument("--letzte", type=int, help="die letzten N Zeilen zeigen")
    p.add_argument("--eval", help="Testfälle aus den Entscheidungen in diese Datei schreiben")
    args = p.parse_args(argv)

    zeilen = log.lies_alle(DATEN, args.werk)
    if not zeilen:
        print(f"Noch keine Entscheidungen für {args.werk!r} unter {log.log_ordner(DATEN, args.werk)}")
        return 0

    print(f"{len(zeilen)} Entscheidungen · {len({z['sitzung'] for z in zeilen})} Sitzungen · "
          f"{len({z['abschnitt_uuid'] for z in zeilen})} Abschnitte\n")

    if args.letzte:
        for z in zeilen[-args.letzte :]:
            zeichen = {"angenommen": "✓", "abgelehnt": "✗", "zurueckgestellt": "·"}[z["entscheidung"]]
            grund = f"  — {z['grund']}" if z.get("grund") else ""
            print(f"  {zeichen} [{z['ebene']}] {z['abschnitt']}: {z['search'][:50]!r}{grund}")
        print()

    print(log.als_text(log.bilanz_je_regel(zeilen, ebene=args.ebene)))

    if args.eval:
        faelle = als_eval(zeilen, ebene=args.ebene, werk=args.werk)
        Path(args.eval).write_text(json.dumps(faelle, ensure_ascii=False, indent=2) + "\n")
        print(f"\n→ {len(faelle)} Fälle nach {args.eval} (nicht fürs Repo — enthält Werktext)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
