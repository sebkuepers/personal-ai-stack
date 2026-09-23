"""Einen Abschnitt lektorieren lassen.

    python -m buchcli.lektorat --werk immer-wieder-ruegen --abschnitt "Einführung Strand"
    python -m buchcli.lektorat --uuid 4BEE4E45-… --ebene stil

Liest den Abschnitt aus Scrivener, rendert das Stimmprofil und löst den
passenden Workflow aus. Schreibt nichts — das Anwenden ist ein eigener,
abgesicherter Schritt (``buchcli.anwenden``, noch nicht gebaut).

Voraussetzung: ein laufender Worker (``make start-worker``).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from workflows.buch import config as c
from workflows.buch.models import LektoratErgebnis, Stimmprofil
from workflows.buch.scrivener import Abschnitt, lies_binder
from workflows.buch.stimme import render_fuer_agent

REPO = Path(__file__).resolve().parents[3]


def finde_abschnitt(slug: str, *, uuid: str | None, titel: str | None) -> Abschnitt:
    """Sucht einen Abschnitt über UUID oder (Teil-)Titel."""
    werk = c.lade_werk(slug)
    struktur = werk.get("struktur") or {}
    m = lies_binder(
        c.scrivener_pfad(slug),
        slug,
        wurzel=struktur.get("wurzel"),
        kapitel_ebene=struktur.get("kapitel_ebene", 0),
    )
    mit_text = [a for a in m.abschnitte if a.hat_text]

    if uuid:
        treffer = [a for a in mit_text if a.uuid.lower().startswith(uuid.lower())]
    elif titel:
        treffer = [a for a in mit_text if titel.lower() in a.titel.lower()]
    else:
        raise SystemExit("--uuid oder --abschnitt angeben.")

    if not treffer:
        verfuegbar = ", ".join(a.titel for a in mit_text[:8])
        raise SystemExit(f"Kein Abschnitt gefunden. Zum Beispiel: {verfuegbar} …")
    if len(treffer) > 1:
        raise SystemExit(
            "Mehrdeutig: " + ", ".join(f"{a.titel} ({a.uuid[:8]})" for a in treffer[:6])
        )
    return treffer[0]


def stimmprofil_text(slug: str) -> str:
    """Das Stimmprofil in der Form, die der Stil-Agent bekommt."""
    pfad = REPO / "shared" / "buch" / f"{slug}-stimme.json"
    if not pfad.is_file():
        return ""
    return render_fuer_agent(Stimmprofil.model_validate_json(pfad.read_text(encoding="utf-8")))


async def ausfuehren(workflow: str, eingabe: dict) -> dict:
    load_dotenv(REPO / "workflows" / ".env", override=True)
    from mistralai.extra.workflows import WorkflowEncodingConfig, configure_workflow_encoding
    from mistralai.workflows.client import get_mistral_client

    client = get_mistral_client(
        api_key=os.environ["MISTRAL_API_KEY"],
        server_url=os.environ.get("SERVER_URL", "https://api.mistral.ai"),
    )
    await configure_workflow_encoding(WorkflowEncodingConfig(), client=client)
    return await client.workflows.execute_workflow_and_wait_async(
        workflow_identifier=workflow,
        input=eingabe,
        deployment_name=os.environ.get("DEPLOYMENT_NAME", "default"),
    )


def zeige(e: LektoratErgebnis, absaetze: list[str]) -> None:
    print(f"\n{'=' * 74}")
    print(f"{e.ebene.upper()} — {e.abschnitt_titel}")
    print(f"{'=' * 74}")

    if e.nach_art:
        print("  " + " · ".join(f"{n}× {art}" for art, n in sorted(e.nach_art.items())))
    print()

    for i, b in enumerate(e.befunde, start=1):
        kopf = f"{i:2}. [{b.art}]"
        if b.schwere:
            kopf += f" {b.schwere}"
        if b.regel_id:
            kopf += f"  ⟶ {b.regel_id}"
        if b.judge:
            kopf += "  " + " ".join(f"{k}:{v}/5" for k, v in b.judge.items())
        print(kopf)
        print(f"    Absatz {b.absatz_index}")
        print(f"    − {b.search}")
        print(f"    + {b.replace}")
        print(f"    {b.warum}")
        print()

    if e.gesperrt:
        print(f"ZURÜCKGEHALTEN ({len(e.gesperrt)}) — vom Judge gesperrt, bevor sie dich erreichten:")
        for b in e.gesperrt:
            print(f"  · [{b.art}] {b.search[:60]!r} — {b.sperrgrund}")
        print()
    if e.hinweise:
        print("HINWEISE:")
        for h in e.hinweise:
            print(f"  · {h}")
        print()
    if not e.befunde and not e.gesperrt:
        print("  Keine Befunde. Der Abschnitt trägt.\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Einen Abschnitt lektorieren lassen.")
    p.add_argument("--werk", default="immer-wieder-ruegen")
    p.add_argument("--abschnitt", help="Titel oder Titelteil")
    p.add_argument("--uuid", help="UUID oder ihr Anfang")
    p.add_argument("--ebene", choices=["korrektorat", "stil"], default="korrektorat")
    p.add_argument("--max", type=int, default=12)
    p.add_argument("--ohne-judge", action="store_true", help="Bewertung überspringen")
    p.add_argument("--runden", type=int, default=1,
                   help="Judge-Runden: 1 = nur sperren (gemessener Standard), 2+ = Rückkopplung")
    args = p.parse_args(argv)

    a = finde_abschnitt(args.werk, uuid=args.uuid, titel=args.abschnitt)
    profil = stimmprofil_text(args.werk) if args.ebene == "stil" else ""

    if args.ebene == "stil" and not profil:
        print("Kein Stimmprofil vorhanden — erst `make buch-stimmprofil`.", file=sys.stderr)
        return 1

    eingabe = {
        "werk": args.werk,
        "abschnitt": {"uuid": a.uuid, "titel": a.titel, "text": a.text, "pfad": a.pfad},
        "absaetze": a.absaetze,
        "stimmprofil_text": profil,
        "max_befunde": args.max,
        "mit_judge": not args.ohne_judge,
        "max_runden": args.runden,
    }

    print(
        f"{a.titel}  ({a.uuid[:8]}, {len(a.absaetze)} Absätze, {a.woerter} Wörter) "
        f"→ Ebene {args.ebene}"
    )
    roh = asyncio.run(ausfuehren(f"buch-{args.ebene}", eingabe))
    ergebnis = LektoratErgebnis.model_validate(
        roh if isinstance(roh, dict) else roh.model_dump()
    )
    zeige(ergebnis, a.absaetze)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
