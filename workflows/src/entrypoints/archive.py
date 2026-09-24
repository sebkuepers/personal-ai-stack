"""Archive workflows that Studio still lists but the repo no longer defines.

    python -m entrypoints.archive            # preview (default)
    python -m entrypoints.archive --apply    # actually archive

Every rename leaves its predecessor behind: Studio keeps a registration until
someone removes it, so ``buch-korrektorat`` sits next to ``book-copyedit`` and
the list grows with every iteration. The API has no delete — only
``archive_workflow``, which hides the entry and keeps its run history.

The comparison is against ``discover_workflows()``, not against a hand-kept
list. That way this tool cannot go stale: whatever the worker registers is
current by definition, everything else is a leftover.

Preview is the default, as with ``book-apply``. Archiving is reversible
(``unarchive_workflow``), but a list that silently shrinks is worse than one
click too many.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[3]


def defined_names() -> set[str]:
    """The workflow names this repo currently defines."""
    from entrypoints.worker import discover_workflows

    names: set[str] = set()
    for cls in discover_workflows():
        spec = getattr(cls, "__workflows_workflow_def", None)
        name = getattr(spec, "name", None) if spec else None
        names.add(name or cls.__name__)
    return names


async def run(apply: bool, keep: set[str]) -> int:
    load_dotenv(REPO / "workflows" / ".env", override=True)
    from mistralai.client import Mistral

    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        print("MISTRAL_API_KEY fehlt — workflows/.env prüfen.", file=sys.stderr)
        return 1

    client = Mistral(api_key=api_key)
    registered = (await client.workflows.get_workflows_async(limit=100)).result.workflows
    live = [w for w in registered if not w.archived]

    stale = [w for w in live if w.name not in keep]
    current = [w for w in live if w.name in keep]

    print(f"{len(live)} aktive Registrierungen · {len(current)} vom Repo definiert · "
          f"{len(stale)} verwaist\n")
    if not stale:
        print("Nichts zu archivieren.")
        return 0

    for w in stale:
        print(f"  {w.name:28} {w.display_name or ''}")

    if not apply:
        print("\nVorschau — nichts geändert. Mit --apply archivieren.")
        return 0

    result = await client.workflows.bulk_archive_workflows_async(
        workflow_ids=[w.id for w in stale]
    )
    # Nur zählen, nicht die ganzen Objekte ausgeben — die Antwort enthält je
    # Workflow die vollständige Definition samt Beschreibung.
    errored = list(getattr(result, "errored", []) or [])
    print(f"\n{len(getattr(result, 'archived', []) or [])} archiviert.")
    if errored:
        print(f"{len(errored)} fehlgeschlagen:")
        for e in errored:
            print(f"  ✗ {e}")
        return 1
    print("Rückgängig einzeln mit client.workflows.unarchive_workflow(workflow_identifier=…).")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Verwaiste Workflow-Registrierungen in Studio archivieren."
    )
    p.add_argument("--apply", action="store_true", help="tatsächlich archivieren")
    p.add_argument(
        "--keep",
        action="append",
        default=[],
        help="zusätzlich behalten (mehrfach angebbar) — für Workflows, an denen "
             "gerade jemand anderes arbeitet",
    )
    args = p.parse_args(argv)

    keep = defined_names() | set(args.keep)
    return asyncio.run(run(args.apply, keep))


if __name__ == "__main__":
    raise SystemExit(main())
