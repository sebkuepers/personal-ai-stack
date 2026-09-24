"""Have a section edited.

    python -m bookcli.editing --work immer-wieder-ruegen --section "Einführung Strand"
    python -m bookcli.editing --uuid 4BEE4E45-… --level style

Reads the section from Scrivener, renders the voice profile and triggers the
matching workflow. Writes nothing — applying is a separate, guarded step
(``bookcli.apply``).

Prerequisite: a running worker (``make start-worker``).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from workflows.book import config as c
from workflows.book.models import EditingResult, VoiceProfile
from workflows.book.scrivener import Section, read_binder
from workflows.book.voice import render_for_agent

REPO = Path(__file__).resolve().parents[3]


def find_section(slug: str, *, uuid: str | None, title: str | None) -> Section:
    """Look up a section by UUID or by (part of) its title."""
    work = c.load_work(slug)
    structure = work.get("structure") or {}
    m = read_binder(
        c.scrivener_path(slug),
        slug,
        root=structure.get("root"),
        chapter_level=structure.get("chapter_level", 0),
    )
    with_text = [s for s in m.sections if s.has_text]

    if uuid:
        hits = [s for s in with_text if s.uuid.lower().startswith(uuid.lower())]
    elif title:
        hits = [s for s in with_text if title.lower() in s.title.lower()]
    else:
        raise SystemExit("--uuid oder --section angeben.")

    if not hits:
        available = ", ".join(s.title for s in with_text[:8])
        raise SystemExit(f"Kein Abschnitt gefunden. Zum Beispiel: {available} …")
    if len(hits) > 1:
        raise SystemExit(
            "Mehrdeutig: " + ", ".join(f"{s.title} ({s.uuid[:8]})" for s in hits[:6])
        )
    return hits[0]


def voice_profile_text(slug: str) -> str:
    """The voice profile in the form the style agent gets."""
    path = REPO / "shared" / "book" / f"{slug}-voice.json"
    if not path.is_file():
        return ""
    return render_for_agent(VoiceProfile.model_validate_json(path.read_text(encoding="utf-8")))


async def run(workflow: str, payload: dict) -> dict:
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
        input=payload,
        deployment_name=os.environ.get("DEPLOYMENT_NAME", "default"),
    )


def show(result: EditingResult) -> None:
    print(f"\n{'=' * 74}")
    print(f"{result.level.upper()} — {result.section_title}")
    print(f"{'=' * 74}")

    if result.by_kind:
        print("  " + " · ".join(f"{n}× {kind}" for kind, n in sorted(result.by_kind.items())))
    print()

    for i, f in enumerate(result.findings, start=1):
        head = f"{i:2}. [{f.kind}]"
        if f.severity:
            head += f" {f.severity}"
        if f.rule_id:
            head += f"  ⟶ {f.rule_id}"
        if f.review:
            head += "  " + " ".join(f"{k}:{v}/5" for k, v in f.review.items())
        print(head)
        print(f"    Absatz {f.paragraph_index}")
        print(f"    − {f.search}")
        print(f"    + {f.replace}")
        print(f"    {f.why}")
        print()

    if result.blocked:
        print(
            f"ZURÜCKGEHALTEN ({len(result.blocked)}) — vom Gegenlesen gesperrt, "
            "bevor sie dich erreichten:"
        )
        for f in result.blocked:
            print(f"  · [{f.kind}] {f.search[:60]!r} — {f.block_reason}")
        print()
    if result.notes:
        print("HINWEISE:")
        for n in result.notes:
            print(f"  · {n}")
        print()
    if not result.findings and not result.blocked:
        print("  Keine Befunde. Der Abschnitt trägt.\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Einen Abschnitt lektorieren lassen.")
    p.add_argument("--work", default="immer-wieder-ruegen")
    p.add_argument("--section", help="Titel oder Titelteil")
    p.add_argument("--uuid", help="UUID oder ihr Anfang")
    p.add_argument("--level", choices=["copyedit", "style"], default="copyedit")
    p.add_argument("--max", type=int, default=12)
    p.add_argument(
        "--without-second-read", action="store_true", help="Gegenlesen überspringen"
    )
    p.add_argument("--rounds", type=int, default=1,
                   help="Gegenlese-Runden: 1 = nur sperren (gemessener Standard), 2+ = Rückkopplung")
    args = p.parse_args(argv)

    s = find_section(args.work, uuid=args.uuid, title=args.section)
    profile = voice_profile_text(args.work) if args.level == "style" else ""

    if args.level == "style" and not profile:
        print("Kein Stimmprofil vorhanden — erst `make book-voiceprofile`.", file=sys.stderr)
        return 1

    payload = {
        "work": args.work,
        "section": {"uuid": s.uuid, "title": s.title, "text": s.text, "path": s.path},
        "paragraphs": s.paragraphs,
        "voice_profile_text": profile,
        "max_findings": args.max,
        "with_second_read": not args.without_second_read,
        "max_rounds": args.rounds,
    }

    print(
        f"{s.title}  ({s.uuid[:8]}, {len(s.paragraphs)} Absätze, {s.words} Wörter) "
        f"→ Ebene {args.level}"
    )
    raw = asyncio.run(run(f"book-{args.level}", payload))
    result = EditingResult.model_validate(
        raw if isinstance(raw, dict) else raw.model_dump()
    )
    show(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
