"""Das Stimmprofil eines Werks destillieren.

    python -m buchcli.stimmprofil --werk immer-wieder-ruegen              # Lauf → Kandidat
    python -m buchcli.stimmprofil --werk immer-wieder-ruegen --uebernehmen # Kandidat → Profil

Die Arbeitsteilung folgt der Architekturregel der Domäne: **lokal lesen und
rechnen, in der Cloud orchestrieren.** Hier passiert alles, was Dateisystem oder
Determinismus braucht — Scrivener lesen, Kennzahlen messen, die Lektoratsnotizen
auswerten. Der Workflow ``buch-stimmprofil`` bekommt das fertig aufbereitet und
kümmert sich um die Agent-Aufrufe, ihre Wiederholung und die Belegprüfung.

Jeder Lauf schreibt seinen Kandidaten nach ``shared/buch/<slug>-stimme.kandidat.json``
und zeigt ihn. ``--uebernehmen`` befördert **genau diesen Kandidaten** zum Profil —
ohne neuen Lauf. Vorher war ``--schreiben`` ein zweiter Lauf, und das
gespeicherte Profil war nie das, das man gerade gesehen hatte. Ein Lauf, ansehen,
den übernehmen.

Das Profil landet in ``shared/buch/<slug>-stimme.json``, im Skill
``skills/buch-stimme/`` und (mit ``--library``) in der Mistral Library.

Voraussetzung: ein laufender Worker (``make start-worker``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from workflows.buch import config as c
from workflows.buch.models import Stimmprofil
from workflows.buch.scrivener import lies_binder
from workflows.buch.stilmetrik import messe_manuskript
from workflows.buch.stimme import render_markdown

REPO = Path(__file__).resolve().parents[3]


def baue_eingabe(slug: str, *, limit: int | None = None, parallel: int = 6) -> dict:
    """Liest Scrivener und baut daraus die Workflow-Eingabe."""
    werk = c.lade_werk(slug)
    struktur = werk.get("struktur") or {}
    m = lies_binder(
        c.scrivener_pfad(slug),
        slug,
        wurzel=struktur.get("wurzel"),
        kapitel_ebene=struktur.get("kapitel_ebene", 0),
    )

    mit_text = [a for a in m.abschnitte if a.hat_text]
    if limit:
        mit_text = mit_text[:limit]

    metrik = messe_manuskript(m)

    return {
        "werk": slug,
        "abschnitte": [
            {
                "uuid": a.uuid,
                "titel": a.titel,
                "text": a.text,
                "pfad": a.pfad,
                "synopsis": a.synopsis,
            }
            for a in mit_text
        ],
        # Belegbasis = AUSSCHLIESSLICH Werktext, nie Kommentar über das Werk:
        # Ausschließlich das VOLLE Manuskript, auch bei --limit (sonst gelten
        # Fundstellen aus nicht analysierten Abschnitten fälschlich als erfunden).
        #
        # BEWUSST OHNE die Lektoratsnotizen. Sie standen hier einmal — ihre
        # VORHER/NACHHER-Paare gingen sogar mit VORRANG in den Reduce-Schritt, und
        # entsprechend kamen 9 von 10 Regeln aus ihnen statt aus dem Text. Das ist
        # nicht, was ein Stimmprofil sein soll: Die Notizen sagen, was der Autor an
        # einzelnen Stellen korrigiert hat, nicht, wie er schreibt. Das Profil wird
        # aus dem Manuskript abgeleitet, sonst aus nichts.
        "korpus_text": "\n\n".join(
            p for a in m.abschnitte if a.hat_text for p in a.absaetze
        ),
        "metrik_text": metrik.als_text(),
        "metrik": metrik.to_dict(),
        "woerter": sum(a.woerter for a in mit_text),
        "kapitel": m.kapitel,
        "parallel": parallel,
    }


async def ausfuehren(eingabe: dict) -> dict:
    """Löst den Workflow aus und wartet auf das Ergebnis."""
    load_dotenv(REPO / "workflows" / ".env", override=True)
    from mistralai.extra.workflows import WorkflowEncodingConfig, configure_workflow_encoding
    from mistralai.workflows.client import get_mistral_client

    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        raise SystemExit("MISTRAL_API_KEY fehlt — workflows/.env prüfen.")

    client = get_mistral_client(
        api_key=api_key, server_url=os.environ.get("SERVER_URL", "https://api.mistral.ai")
    )
    await configure_workflow_encoding(WorkflowEncodingConfig(), client=client)
    return await client.workflows.execute_workflow_and_wait_async(
        workflow_identifier="buch-stimmprofil",
        input=eingabe,
        deployment_name=os.environ.get("DEPLOYMENT_NAME", "default"),
    )


def zeige(profil: Stimmprofil) -> None:
    print(f"\n{'=' * 72}")
    print(f"STIMMPROFIL — {profil.werk}  (Version {profil.version})")
    print(f"{'=' * 72}")
    print(f"Erzählhaltung : {profil.erzaehlhaltung}")
    print(f"Tempus/Person : {profil.tempus} · {profil.person}")
    print(f"Korpus        : {profil.korpus.abschnitte} Abschnitte, {profil.korpus.woerter} Wörter")
    print(f"\nREGELN ({len(profil.aktive_regeln)} von {c.MAX_STIMMREGELN} möglichen):\n")
    for i, r in enumerate(profil.aktive_regeln, start=1):
        print(f"{i:2}. {r.titel}   [{r.id}]  Quelle: {r.quelle}")
        print(f"    {r.regel}")
        print(f"    erkennbar an: {r.pruefbar_als}")
        print(f"    Fundstelle: „{r.fundstellen[0][:100]}…“  ({len(r.fundstellen)} Fundstellen)")
        print()
    if profil.vermeidungen:
        print("TUT DER AUTOR NIE:")
        for v in profil.vermeidungen:
            print(f"  - {v}")
        print()
    if profil.offene_fragen:
        print("OFFENE FRAGEN:")
        for f in profil.offene_fragen:
            print(f"  - {f}")
        print()
    if profil.verworfene_regeln:
        print(f"VERWORFEN — Belegprüfung nicht bestanden ({len(profil.verworfene_regeln)}):")
        for v in profil.verworfene_regeln:
            print(f"  - {v['titel']}: {v['grund']}")
        print()


def schreibe(profil: Stimmprofil, slug: str) -> list[Path]:
    """Legt das Profil als Quelle der Wahrheit und als Skill ab."""
    geschrieben: list[Path] = []

    ziel = REPO / "shared" / "buch" / f"{slug}-stimme.json"
    ziel.write_text(
        profil.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
    )
    geschrieben.append(ziel)

    # Lesbare Fassung ins Werk-Verzeichnis — dorthin, wo die übrigen Werk-Daten
    # liegen. Bewusst kein Agent Skill: Der Stil-Agent bekommt das Profil zur
    # Laufzeit in den Prompt gerendert (render_fuer_agent), und für Vibe Work
    # müsste ein Skill ohnehin von Hand im UI angelegt werden.
    export = c.lade_werk(slug)["pfade"]["export"]
    export.mkdir(parents=True, exist_ok=True)
    (export / "stimmprofil.md").write_text(render_markdown(profil), encoding="utf-8")
    geschrieben.append(export / "stimmprofil.md")

    # Verweis in der Werk-Konfiguration aktualisieren.
    werkdatei = REPO / "shared" / "buch" / f"{slug}.json"
    werk = json.loads(werkdatei.read_text(encoding="utf-8"))
    werk["stimmprofil"] = f"shared/buch/{slug}-stimme.json"
    werkdatei.write_text(
        json.dumps(werk, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return geschrieben


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stimmprofil eines Werks destillieren.")
    p.add_argument("--werk", default="immer-wieder-ruegen")
    p.add_argument("--limit", type=int, help="nur die ersten N Abschnitte (Probelauf)")
    p.add_argument("--parallel", type=int, default=6)
    p.add_argument("--uebernehmen", action="store_true",
                   help="den zuletzt erzeugten Kandidaten zum Profil machen (kein neuer Lauf)")
    p.add_argument("--schreiben", action="store_true",
                   help="Lauf UND sofort übernehmen — nur, wenn man ohne Ansehen vertraut")
    p.add_argument("--library", action="store_true", help="zusätzlich in die Mistral Library")
    args = p.parse_args(argv)

    fehlend = [k for k in ("stimme_probe", "stimme_profil") if not c.AGENTS.get(k)]
    if fehlend:
        print(f"Agent-IDs fehlen in shared/buch.json: {fehlend}", file=sys.stderr)
        print("→ cd workflows && make sync-agents", file=sys.stderr)
        return 1

    eingabe = baue_eingabe(args.werk, limit=args.limit, parallel=args.parallel)
    print(
        f"{args.werk}: {len(eingabe['abschnitte'])} Abschnitte, {eingabe['woerter']} Wörter, "
        "nur Manuskripttext"
    )
    print(f"Analyse läuft ({args.parallel} parallel) — das dauert einige Minuten …\n")

    kandidat = REPO / "shared" / "buch" / f"{args.werk}-stimme.kandidat.json"

    if args.uebernehmen:
        if not kandidat.is_file():
            print(f"Kein Kandidat unter {kandidat.relative_to(REPO)} — erst einen Lauf machen.")
            return 1
        profil = Stimmprofil.model_validate_json(kandidat.read_text(encoding="utf-8"))
        zeige(profil)
        for pfad in schreibe(profil, args.werk):
            print(f"  → {pfad.relative_to(REPO)}")
        print("  (Kandidat übernommen — kein neuer Lauf)")
        return 0

    roh = asyncio.run(ausfuehren(eingabe))
    profil = Stimmprofil.model_validate(roh if isinstance(roh, dict) else roh.model_dump())
    zeige(profil)
    kandidat.write_text(profil.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8")
    print(f"  → Kandidat: {kandidat.relative_to(REPO)}")

    if args.schreiben:
        for pfad in schreibe(profil, args.werk):
            print(f"  → {pfad.relative_to(REPO)}")
        if args.library:
            from buchcli.sync import in_library

            werk = c.lade_werk(args.werk)
            md = werk["pfade"]["export"] / "stimmprofil.md"
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(render_markdown(profil), encoding="utf-8")
            print(f"  → Library: {in_library(md, werk)}")
    else:
        print("Nur Kandidat. Gefällt er: --uebernehmen. Gefällt er nicht: neuer Lauf.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
