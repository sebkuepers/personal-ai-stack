# mcp-server — personal MCP server

A remote [MCP](https://modelcontextprotocol.io/) server running as a **Cloudflare Worker**, registered
with Mistral as a **custom connector**. It's my personal function library: once attached to an agent,
the model auto-discovers these tools and **Mistral executes them server-side** — so the same functions
are available in the Studio Playground, Le Chat, Vibe Work, and the workflow durable agents.

> 🚧 Built in Phase 1. Scaffolded with
> `npm create cloudflare@latest -- mcp-server --template=cloudflare/ai/demos/remote-mcp-authless`
> (`McpAgent` + `server.tool()` + Zod). One file per tool under `src/tools/`.

## Tools (planned)

| Tool | Purpose |
|---|---|
| `get_used_categories` | Return the live CRM category + sub-category vocabulary (from the Notion Interactions schema) so the classification agent reuses existing categories instead of inventing duplicates. |

## Conventions

- Tools read IDs from [`../shared/crm.json`](../shared/crm.json) — the single source of truth.
- Secrets via `wrangler secret put` (e.g. `NOTION_TOKEN`). Never committed.
- Deploy: `npx wrangler deploy` → `https://mcp-server.<account>.workers.dev/mcp`.
- Register with Mistral: a custom connector (name + URL + scope), then attach to the agent.
