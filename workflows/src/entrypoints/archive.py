"""Clean up what Studio still lists but the repo no longer defines.

    python -m entrypoints.archive            # preview (default)
    python -m entrypoints.archive --apply    # actually clean up

Every rename leaves its predecessor behind: Studio keeps a registration until
someone removes it, so ``buch-korrektorat`` sits next to ``book-copyedit`` and
the list grows with every iteration. Same for agents — ``Buch · Judge`` outlived
the design it belonged to by weeks, invisible in a list of twelve.

Two object kinds, two levels of severity:

* **Workflows** are *archived*. There is no delete in the API, and archiving is
  reversible (``unarchive_workflow``); the run history survives.
* **Agents** are *deleted*. The API has no archive for them, so this is
  irreversible. But an agent is a definition and lives in ``agents/*.json``:
  whatever gets deleted here can be recreated with ``make sync-agents``, except
  for its ID. What is lost is the ID, and with it the reference in
  ``shared/<domain>.json`` — which is precisely why only agents that no JSON in
  the repo describes are eligible.

The comparison runs against the repo, not against a hand-kept list: workflows
against ``discover_workflows()``, agents against the ``name`` fields in
``agents/*.json``. That way this tool cannot go stale itself — whatever the
repo defines is current by definition, everything else is a leftover.

Preview is the default, as with ``book-apply``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO = Path(__file__).resolve().parents[3]


def defined_workflows() -> set[str]:
    """The workflow names this repo currently defines."""
    from entrypoints.worker import discover_workflows

    names: set[str] = set()
    for cls in discover_workflows():
        spec = getattr(cls, "__workflows_workflow_def", None)
        name = getattr(spec, "name", None) if spec else None
        names.add(name or cls.__name__)
    return names


def defined_agents() -> set[str]:
    """The agent names this repo currently defines, from ``agents/*.json``.

    Deliberately the *name*, not the ID: an agent whose ID is recorded nowhere
    is exactly the case we are looking for, and a definition without a name
    cannot be synced either.
    """
    names: set[str] = set()
    for path in sorted((REPO / "agents").glob("*.json")):
        try:
            name = json.loads(path.read_text(encoding="utf-8")).get("name")
        except json.JSONDecodeError:
            continue  # a broken definition must not cause a deletion
        if name:
            names.add(name)
    return names


async def _workflows(client, keep: set[str], apply: bool) -> int:
    registered = (await client.workflows.get_workflows_async(limit=100)).result.workflows
    live = [w for w in registered if not w.archived]
    stale = [w for w in live if w.name not in keep]

    print(f"WORKFLOWS — {len(live)} aktiv · {len(live) - len(stale)} vom Repo definiert · "
          f"{len(stale)} verwaist")
    if not stale:
        print("  nichts zu archivieren\n")
        return 0
    for w in stale:
        print(f"  {w.name:28} {w.display_name or ''}")
    if not apply:
        print()
        return 0

    result = await client.workflows.bulk_archive_workflows_async(
        workflow_ids=[w.id for w in stale]
    )
    # Only count — the response carries each workflow's full definition.
    errored = list(getattr(result, "errored", []) or [])
    print(f"  → {len(getattr(result, 'archived', []) or [])} archiviert "
          "(rückgängig mit unarchive_workflow)")
    for e in errored:
        print(f"  ✗ {e}")
    print()
    return 1 if errored else 0


async def _agents(client, keep: set[str], apply: bool) -> int:
    listed = await client.beta.agents.list_async()
    agents = listed if isinstance(listed, list) else getattr(listed, "data", [])
    stale = [a for a in agents if a.name not in keep]

    print(f"AGENTEN — {len(agents)} vorhanden · {len(agents) - len(stale)} vom Repo definiert · "
          f"{len(stale)} verwaist")
    if not stale:
        print("  nichts zu löschen\n")
        return 0
    for a in stale:
        print(f"  {str(a.name)[:34]:36} {a.id}")
    if not apply:
        print("  (Löschen ist endgültig — die Definition ließe sich aus agents/*.json neu "
              "anlegen, die ID nicht.)\n")
        return 0

    failed = 0
    for a in stale:
        try:
            await client.beta.agents.delete_async(agent_id=a.id)
            print(f"  → gelöscht: {a.name}")
        except Exception as exc:  # noqa: BLE001 — one failure must not stop the rest
            print(f"  ✗ {a.name}: {exc}")
            failed += 1
    print()
    return 1 if failed else 0


async def run(apply: bool, keep_workflows: set[str], keep_agents: set[str]) -> int:
    load_dotenv(REPO / "workflows" / ".env", override=True)
    from mistralai.client import Mistral

    api_key = os.environ.get("MISTRAL_API_KEY", "")
    if not api_key:
        print("MISTRAL_API_KEY fehlt — workflows/.env prüfen.", file=sys.stderr)
        return 1

    client = Mistral(api_key=api_key)
    code = await _workflows(client, keep_workflows, apply)
    code |= await _agents(client, keep_agents, apply)
    if not apply:
        print("Vorschau — nichts geändert. Mit --apply aufräumen.")
    return code


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Verwaiste Workflows und Agenten in Studio aufräumen."
    )
    p.add_argument("--apply", action="store_true", help="tatsächlich aufräumen")
    p.add_argument(
        "--keep",
        action="append",
        default=[],
        help="zusätzlich behalten, Workflow-Name oder Agent-Name (mehrfach angebbar) — "
             "für Objekte, an denen gerade jemand anderes arbeitet",
    )
    args = p.parse_args(argv)

    extra = set(args.keep)
    return asyncio.run(run(args.apply, defined_workflows() | extra, defined_agents() | extra))


if __name__ == "__main__":
    raise SystemExit(main())
