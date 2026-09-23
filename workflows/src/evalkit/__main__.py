"""Generisches Eval-CLI für jeden Agent im Repo.

    python -m evalkit --agent buch-korrektorat --faelle shared/buch/eval-immer-wieder-ruegen.json
    python -m evalkit --agent crm-classification --faelle shared/crm/eval-faelle.json --zaehlpfad ""

Die Fall-Datei ist eine JSON-Liste:

    [{"id": "…",
      "eingabe": "der Text, der an den Agent geht",
      "erwartet": [{"pfad": "korrekturen[].search", "wert": "…"}],
      "verboten": [{"pfad": "korrekturen[].search", "operator": "paar",
                    "paar_pfad": "korrekturen[].replace", "wert": ["runter", "hinunter"]}]}]

Domänen bringen eigene Generatoren mit (z. B. ``buchcli.eval --erzeuge``); das
Messen selbst ist hier für alle gleich.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from .modelle import Fall
from .runner import STANDARD_KONFIGURATIONEN, agent_definition

REPO = Path(__file__).resolve().parents[3]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Agent-Konfigurationen messen.")
    p.add_argument("--agent", required=True, help="Name der Datei in agents/ ohne .json")
    p.add_argument("--faelle", required=True, help="Pfad zur Fall-Datei (relativ zum Repo)")
    p.add_argument("--laeufe", type=int, default=1)
    p.add_argument("--nur", help="nur diese Konfiguration, z. B. small/high")
    p.add_argument(
        "--zaehlpfad",
        default="korrekturen[]",
        help="was als ein Befund zählt (leer lassen für Klassifikations-Agents)",
    )
    p.add_argument("--still", action="store_true", help="keine Fortschrittsanzeige")
    args = p.parse_args(argv)

    pfad = REPO / args.faelle
    if not pfad.is_file():
        print(f"Fall-Datei nicht gefunden: {pfad}", file=sys.stderr)
        return 1

    load_dotenv(REPO / "workflows" / ".env", override=True)
    faelle = [Fall.from_dict(d) for d in json.loads(pfad.read_text(encoding="utf-8"))]
    instruktionen, schema = agent_definition(REPO, args.agent)

    konfigs = [k for k in STANDARD_KONFIGURATIONEN if not args.nur or k.name == args.nur]
    if not konfigs:
        verfuegbar = ", ".join(k.name for k in STANDARD_KONFIGURATIONEN)
        print(f"Unbekannt: {args.nur}. Verfügbar: {verfuegbar}", file=sys.stderr)
        return 1

    erwartet = sum(len(f.erwartet) for f in faelle)
    verboten = sum(len(f.verboten) for f in faelle)
    print(
        f"{args.agent} · {len(faelle)} Fälle · {erwartet} Erwartungen · "
        f"{verboten} Fallen · {args.laeufe} Lauf/Läufe\n"
    )
    if not erwartet:
        print("  Hinweis: keine Erwartungen annotiert — gemessen wird nur die Fallenquote.\n")

    def fortschritt(konf: str, fall: str) -> None:
        if not args.still:
            print(f"  … {konf}  {fall[:40]}", end="\r", file=sys.stderr)

    # Konfiguration für Konfiguration ausgeben, nicht erst am Ende: Ein Lauf mit
    # Reasoning kann Minuten dauern, und ein stummer Prozess sieht aus wie ein
    # hängender.
    from .modelle import bilanziere
    from .runner import einmal

    ergebnisse = []
    for konf in konfigs:
        alle = []
        for _ in range(args.laeufe):
            for f in faelle:
                fortschritt(konf.name, f.id)
                alle.append(einmal(f, konf, instruktionen, schema,
                                   zaehlpfad=args.zaehlpfad or None))
        bilanz = bilanziere(konf.name, faelle * args.laeufe, alle)
        ergebnisse.append((bilanz, alle))
        print(" " * 70, end="\r")
        print(bilanz.als_zeile(), flush=True)

    print()
    for _bilanz, einzeln in sorted(ergebnisse, key=lambda x: -x[0].punktzahl):
        for e in einzeln:
            for ft in e.fehltritte:
                print(f"      ✗ {e.fall_id[:30]}: {ft[:80]}")
            for v in e.verpasst:
                print(f"      ○ {e.fall_id[:30]}: verpasst {v[:70]}")
            if e.fehler:
                print(f"      ! {e.fall_id[:30]}: {e.fehler[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
