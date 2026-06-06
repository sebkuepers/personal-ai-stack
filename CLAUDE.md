# CLAUDE.md — personal-ai-stack monorepo

Guidance for AI agents (and humans) working in this repo. This is the **monorepo-level** map; each
pillar has its own deeper doc. Read this first, then the pillar doc for whatever you're touching.

## What this repo is

A personal AI system with three composable pillars on Mistral + Cloudflare:

| Pillar | Stack | Deep doc |
|---|---|---|
| `workflows/` — durable Mistral Workflows | Python | [`workflows/CLAUDE.md`](workflows/CLAUDE.md) ← **the verified SDK conventions + gotchas** |
| `mcp-server/` — personal MCP server (a Mistral custom connector) | TypeScript · Cloudflare Worker | `mcp-server/README.md` |
| `skills/` — Agent Skills for Vibe Work | Markdown (`SKILL.md`) | `skills/README.md` |

Plus `worker-host/` (Cloudflare Worker: hosts the workflows worker container + the cron trigger),
`Dockerfile` (the worker image), and `shared/` (the source of truth).
See [`README.md`](README.md) for the architecture and [`docs/architecture.md`](docs/architecture.md)
for the infra rationale.

## Golden rules (whole repo)

1. **Reuse, don't recreate.** Trigger existing Studio agents; reference existing connectors; read
   IDs from `shared/crm.json`. Never hardcode an ID or re-implement an agent's prompt.
2. **`shared/crm.json` is the single source of truth.** Agent id, Notion data-source IDs, connector
   slugs/tools, and the category vocab live there. Python reads it via
   `workflows/src/workflows/crm/config.py`; the MCP server imports it. Change it in **one** place.
3. **Verify against the installed SDK / live account, not from memory.** When unsure about a Mistral
   symbol or a connector tool name, check the venv (`workflows/.venv/.../plugins/mistralai/`) or call
   `client.beta.connectors.list_async()` / `.agents.list_async()`.
4. **Secrets never get committed.** API keys live in gitignored `.env` (workflows) and
   `wrangler secret` (Cloudflare). `shared/crm.json` holds only non-secret identifiers.

## Working in each pillar

- **`workflows/`** — Python, `uv`. From `workflows/`: `uv sync`, `make start-worker`,
  `make crm-*`. After ANY change run the offline discovery check:
  `uv run python -c "from entrypoints.worker import discover_workflows as d; print(len(d()))"`.
  **All the SDK gotchas (sandbox imports, connector slugs, trigger-vs-overwrite an agent,
  on_behalf_of+schedule, etc.) are in [`workflows/CLAUDE.md`](workflows/CLAUDE.md) — read it before
  editing workflow code.**
- **`mcp-server/`** — TypeScript Cloudflare Worker (`McpAgent` + `server.tool()` + Zod). One file
  per tool under `src/tools/`. `wrangler dev` / `wrangler deploy`; secrets via `wrangler secret`.
  Tools read IDs from `shared/crm.json`. Registered with Mistral as a custom connector — when an
  agent calls a tool, **Mistral pings the Worker** (not the workflow).
- **`worker-host/`** — Cloudflare Worker that (1) defines the `WorkflowsWorker` Container (runs the
  repo-root `Dockerfile`, scale-to-zero) and (2) has a `scheduled()` cron that wakes the container and
  `fetch`es the Mistral execute API (`/v1/workflows/{name}/execute`, key as a Worker secret).
- **`skills/`** — one folder per skill with a `SKILL.md` (YAML frontmatter + Markdown, open Agent
  Skills standard). Descriptions are *when to use* ("Use when I want to log an interaction…").
  Skills reference the MCP tools and workflows; they don't contain logic.

## Cross-cutting conventions

- **Adding a workflow:** drop a module in `workflows/src/workflows/` (grouped subfolders are
  supported once recursive discovery lands), add a Makefile target, run the discovery check.
- **Adding an MCP tool:** new file in `mcp-server/src/tools/`, register it, `wrangler deploy`; it's
  immediately available to every agent that has the connector.
- **Adding a skill:** new `skills/<name>/SKILL.md`; keep it declarative (point at tools/workflows).
- **Changing an ID/vocab:** edit `shared/crm.json` only.
