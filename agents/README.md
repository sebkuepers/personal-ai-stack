# agents — Mistral agents as code

Version-controlled definitions of my Mistral Studio agents. Each `*.json` file is
the **source of truth** for one agent (model, instructions, tools, and the
`completion_args.response_format` JSON schema). `sync.py` creates or updates them
in Studio via the API, so the Playground is no longer the only place the config
lives.

## Files

| File | Agent |
|---|---|
| `crm-classification.json` | CRM Classification Agent (`ag_019e98…`) — classifies interactions; its response schema is the contract the workflows rely on |
| `sync.py` | create-or-update every definition in Studio |

## Usage

```bash
# validate the definitions round-trip (no API calls, no changes):
uv run --project workflows python agents/sync.py --dry-run

# apply to Studio (OVERWRITES the live agent config from the files):
uv run --project workflows python agents/sync.py
# or: cd workflows && make sync-agents
```

A file with an `id` is **updated**; a file without one is **created** and the new
id is written back. The Mistral API key is read from `workflows/.env`.

## Conventions

- **The repo is the source of truth.** A live sync overwrites the Studio agent —
  edit the JSON here, not the Playground (Studio's "Source" flips from Playground
  to API once managed this way).
- **Don't change `id`.** It's referenced from `shared/crm.json` and by the
  workflows; updating in place keeps it stable.
- **Attaching tools/connectors is declarative** — add the custom MCP connector to
  an agent's `tools` here and `sync` applies it (no one-off API call).
