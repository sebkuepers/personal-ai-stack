"""Sync agent definitions (agents/*.json) to Mistral Studio — create or update.

Each JSON file is the version-controlled source of truth for one Studio agent.
If a file has an ``id``, the agent is UPDATED; otherwise it is CREATED and the
new id is written back into the file.

Usage (run with the workflows env, which has mistralai + the API key):
    uv run --project workflows python agents/sync.py --dry-run   # validate only, no API calls
    uv run --project workflows python agents/sync.py             # apply to Studio

The repo is the source of truth: a live sync OVERWRITES the Studio agent's
config from the file. Edit the JSON here, not the Playground.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv

AGENTS_DIR = Path(__file__).resolve().parent
ROOT = AGENTS_DIR.parent
# API key lives in the workflows pillar's .env (single place for the Mistral key).
load_dotenv(ROOT / "workflows" / ".env", override=False)

from mistralai.client import Mistral  # noqa: E402
from mistralai.client import models as m  # noqa: E402

# Fields that are part of an agent's definition (everything else, e.g. id, is metadata).
SETTABLE = {
    "name", "model", "description", "instructions",
    "tools", "completion_args", "handoffs", "metadata",
}


def _split(defn: dict) -> tuple[str | None, dict]:
    agent_id = defn.get("id")
    fields = {k: v for k, v in defn.items() if k in SETTABLE}
    return agent_id, fields


async def sync_one(client: Mistral | None, path: Path, dry_run: bool) -> None:
    defn = json.loads(path.read_text(encoding="utf-8"))
    agent_id, fields = _split(defn)
    name = defn.get("name", path.stem)

    if dry_run:
        # Validate the round-trip by constructing the request model (no network).
        if agent_id:
            m.UpdateAgentRequest(agent_id=agent_id, **fields)
        else:
            m.CreateAgentRequest(**fields)
        action = f"update {agent_id}" if agent_id else "create"
        print(f"[dry-run] OK  {name:<28} ({action})")
        return

    assert client is not None
    if agent_id:
        await client.beta.agents.update_async(agent_id=agent_id, **fields)
        print(f"updated  {name}  ({agent_id})")
    else:
        created = await client.beta.agents.create_async(**fields)
        path.write_text(
            json.dumps({"id": created.id, **defn}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"created  {name}  ({created.id})  — id written back to {path.name}")


async def main() -> None:
    ap = argparse.ArgumentParser(description="Sync agents/*.json to Mistral Studio.")
    ap.add_argument("--dry-run", action="store_true", help="validate only; no API calls")
    args = ap.parse_args()

    paths = sorted(AGENTS_DIR.glob("*.json"))
    if not paths:
        print("No agent definitions found in agents/.")
        return

    client = None if args.dry_run else Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    for path in paths:
        await sync_one(client, path, args.dry_run)


if __name__ == "__main__":
    asyncio.run(main())
