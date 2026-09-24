"""Distil a work's voice profile.

    python -m bookcli.voiceprofile --work immer-wieder-ruegen           # run → candidate
    python -m bookcli.voiceprofile --work immer-wieder-ruegen --promote # candidate → profile

The division of labour follows the domain's architecture rule: **read and
compute locally, orchestrate in the cloud.** Everything that needs a file system
or determinism happens here — reading Scrivener, measuring the metrics, parsing
the editing notes. The workflow ``book-voiceprofile`` receives that ready-made
and takes care of the agent calls, their retries and the evidence check.

Every run writes its candidate to ``shared/book/<slug>-voice.candidate.json`` and
shows it. ``--promote`` promotes **exactly that candidate** to the profile —
without a new run. Before, ``--write`` was a second run, and the stored profile
was never the one just seen. One run, look at it, promote that one.

The profile lands in ``shared/book/<slug>-voice.json``, in the work's export
folder and (with ``--library``) in the Mistral Library.

Output stays German: the author reads it.

Prerequisite: a running worker (``make start-worker``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from workflows.book import config as c
from workflows.book.models import VoiceProfile
from workflows.book.scrivener import read_binder
from workflows.book.stylemetrics import measure_manuscript
from workflows.book.voice import render_markdown

REPO = Path(__file__).resolve().parents[3]


def build_input(slug: str, *, limit: int | None = None, parallel: int = 6) -> dict:
    """Read Scrivener and build the workflow input from it."""
    work = c.load_work(slug)
    structure = work.get("structure") or {}
    m = read_binder(
        c.scrivener_path(slug),
        slug,
        root=structure.get("root"),
        chapter_level=structure.get("chapter_level", 0),
    )

    with_text = [s for s in m.sections if s.has_text]
    if limit:
        with_text = with_text[:limit]

    metrics = measure_manuscript(m)

    return {
        "work": slug,
        "sections": [
            {
                "uuid": s.uuid,
                "title": s.title,
                "text": s.text,
                "path": s.path,
                "synopsis": s.synopsis,
            }
            for s in with_text
        ],
        # Evidence base = EXCLUSIVELY the work's text, never commentary about
        # the work: always the FULL manuscript, even with --limit (otherwise
        # evidence from unanalysed sections would wrongly count as invented).
        #
        # DELIBERATELY WITHOUT the editing notes. They stood here once — their
        # VORHER/NACHHER pairs even went into the reduce step with PRIORITY,
        # and accordingly 9 of 10 rules came from them instead of from the text.
        # That is not what a voice profile is meant to be: the notes say what
        # the author corrected in individual places, not how he writes. The
        # profile is derived from the manuscript and from nothing else.
        "corpus_text": "\n\n".join(
            p for s in m.sections if s.has_text for p in s.paragraphs
        ),
        "metrics_text": metrics.as_text(),
        "metrics": metrics.to_dict(),
        "words": sum(s.words for s in with_text),
        "chapters": m.chapters,
        "parallel": parallel,
    }


async def run(payload: dict) -> dict:
    """Trigger the workflow and wait for the result."""
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
        workflow_identifier="book-voiceprofile",
        input=payload,
        deployment_name=os.environ.get("DEPLOYMENT_NAME", "default"),
    )


def show(profile: VoiceProfile) -> None:
    print(f"\n{'=' * 72}")
    print(f"STIMMPROFIL — {profile.work}  (Version {profile.version})")
    print(f"{'=' * 72}")
    print(f"Erzählhaltung : {profile.narrative_stance}")
    print(f"Tempus/Person : {profile.tense} · {profile.person}")
    print(f"Korpus        : {profile.corpus.sections} Abschnitte, {profile.corpus.words} Wörter")
    print(f"\nREGELN ({len(profile.active_rules)} von {c.MAX_VOICE_RULES} möglichen):\n")
    for i, r in enumerate(profile.active_rules, start=1):
        print(f"{i:2}. {r.title}   [{r.id}]  Quelle: {r.source}")
        print(f"    {r.rule}")
        print(f"    erkennbar an: {r.testable_as}")
        print(f"    Fundstelle: „{r.evidence[0][:100]}…“  ({len(r.evidence)} Fundstellen)")
        print()
    if profile.avoidances:
        print("TUT DER AUTOR NIE:")
        for a in profile.avoidances:
            print(f"  - {a}")
        print()
    if profile.open_questions:
        print("OFFENE FRAGEN:")
        for q in profile.open_questions:
            print(f"  - {q}")
        print()
    if profile.discarded_rules:
        print(f"VERWORFEN — Belegprüfung nicht bestanden ({len(profile.discarded_rules)}):")
        for d in profile.discarded_rules:
            print(f"  - {d['title']}: {d['reason']}")
        print()


def store(profile: VoiceProfile, slug: str) -> list[Path]:
    """Store the profile as the source of truth and as a readable export."""
    written: list[Path] = []

    target = REPO / "shared" / "book" / f"{slug}-voice.json"
    target.write_text(
        profile.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
    )
    written.append(target)

    # Readable version into the work directory — where the rest of the work's
    # data lives. Deliberately not an agent skill: the style agent gets the
    # profile rendered into its prompt at runtime (render_for_agent), and for
    # Vibe Work a skill would have to be created by hand in the UI anyway.
    export = c.load_work(slug)["paths"]["export"]
    export.mkdir(parents=True, exist_ok=True)
    (export / "stimmprofil.md").write_text(render_markdown(profile), encoding="utf-8")
    written.append(export / "stimmprofil.md")

    # Update the reference in the work configuration.
    work_file = REPO / "shared" / "book" / f"{slug}.json"
    work = json.loads(work_file.read_text(encoding="utf-8"))
    work["voice_profile"] = f"shared/book/{slug}-voice.json"
    work_file.write_text(
        json.dumps(work, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return written


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Stimmprofil eines Werks destillieren.")
    p.add_argument("--work", default="immer-wieder-ruegen")
    p.add_argument("--limit", type=int, help="nur die ersten N Abschnitte (Probelauf)")
    p.add_argument("--parallel", type=int, default=6)
    p.add_argument("--promote", action="store_true",
                   help="den zuletzt erzeugten Kandidaten zum Profil machen (kein neuer Lauf)")
    p.add_argument("--write", action="store_true",
                   help="Lauf UND sofort übernehmen — nur, wenn man ohne Ansehen vertraut")
    p.add_argument("--library", action="store_true", help="zusätzlich in die Mistral Library")
    args = p.parse_args(argv)

    missing = [k for k in ("voice_sample", "voice_profile") if not c.AGENTS.get(k)]
    if missing:
        print(f"Agent-IDs fehlen in shared/book.json: {missing}", file=sys.stderr)
        print("→ cd workflows && make sync-agents", file=sys.stderr)
        return 1

    candidate = REPO / "shared" / "book" / f"{args.work}-voice.candidate.json"

    if args.promote:
        if not candidate.is_file():
            print(f"Kein Kandidat unter {candidate.relative_to(REPO)} — erst einen Lauf machen.")
            return 1
        profile = VoiceProfile.model_validate_json(candidate.read_text(encoding="utf-8"))
        show(profile)
        for path in store(profile, args.work):
            print(f"  → {path.relative_to(REPO)}")
        print("  (Kandidat übernommen — kein neuer Lauf)")
        return 0

    payload = build_input(args.work, limit=args.limit, parallel=args.parallel)
    print(
        f"{args.work}: {len(payload['sections'])} Abschnitte, {payload['words']} Wörter, "
        "nur Manuskripttext"
    )
    print(f"Analyse läuft ({args.parallel} parallel) — das dauert einige Minuten …\n")

    raw = asyncio.run(run(payload))
    profile = VoiceProfile.model_validate(raw if isinstance(raw, dict) else raw.model_dump())
    show(profile)
    candidate.write_text(
        profile.model_dump_json(indent=2, exclude_none=False) + "\n", encoding="utf-8"
    )
    print(f"  → Kandidat: {candidate.relative_to(REPO)}")

    if args.write:
        for path in store(profile, args.work):
            print(f"  → {path.relative_to(REPO)}")
        if args.library:
            from bookcli.sync import into_library

            work = c.load_work(args.work)
            md = work["paths"]["export"] / "stimmprofil.md"
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(render_markdown(profile), encoding="utf-8")
            print(f"  → Library: {into_library([md], work)}")
    else:
        print("Nur Kandidat. Gefällt er: --promote. Gefällt er nicht: neuer Lauf.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
