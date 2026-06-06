# personal-ai-stack

My personal AI system — a monorepo of **durable workflows**, a **personal MCP server**, and
**personal skills**, orchestrated by [Mistral](https://docs.mistral.ai/) and hosted on
[Cloudflare](https://developers.cloudflare.com/).

It started as a personal CRM (classify every email/interaction and file it into a Notion CRM) and
is built to grow into a general personal automation system.

## Three pillars

| Pillar | What it is | Stack | Lives in |
|---|---|---|---|
| **Workflows** | Durable, multi-step automations (the CRM pipeline and more) | Python · Mistral Workflows | [`workflows/`](workflows/) |
| **MCP server** | My personal function library, callable by *every* agent (Studio, Le Chat, Vibe Work, and the workflows) | TypeScript · Cloudflare Worker | [`mcp-server/`](mcp-server/) |
| **Skills** | Agent Skills (`SKILL.md`) that teach Mistral **Vibe Work** when/how to use the MCP tools + workflows | Markdown · open Agent Skills standard | [`skills/`](skills/) |

A fourth folder, [`cron/`](cron/), is a tiny Cloudflare Cron Worker that triggers the scheduled
workflow runs. [`shared/crm.json`](shared/crm.json) is the **single source of truth** (IDs, schema,
vocab) that both the Python and TypeScript sides read.

## Architecture

```
 Cloudflare Cron Worker (cron/)     ──schedule──►  Mistral execute API
 Cloudflare Container (workflows/)  ──hosts────►  Mistral Workflows worker (all workflows)   [scale-to-zero]
 Cloudflare MCP Worker (mcp-server/)──registered as a Mistral custom connector               [serverless]
        │  used by Studio agents · Le Chat · Vibe Work · workflow durable agents
 Skills (skills/)  ──teach Vibe Work how/when to use the MCP tools + workflows
        ▼
 Mistral Studio   →  agents · connectors (notion / gmail) · durable orchestration · observability
```

**Why this shape** (full rationale in [`docs/architecture.md`](docs/architecture.md)):
- **Mistral Workflows** for durable execution + AI-Studio observability + native agent/connector integration.
- The **schedule lives just outside Mistral** (a Cloudflare cron) because OAuth connector workflows
  can't be combined with Mistral's in-SDK scheduler — but *all the work stays in Mistral Workflows*.
- The worker is a long-lived poller, so it runs in a **scale-to-zero Cloudflare Container** (pay per run).
- The MCP server is inbound HTTPS → a natural **Cloudflare Worker**.
- Roughly **$5/mo** (Cloudflare Workers Standard floor) covers the lot.

## Repository layout

```
personal-ai-stack/
├── workflows/     # Python · Mistral Workflows worker  (see workflows/README.md, workflows/CLAUDE.md)
├── agents/        # Mistral agents as code (definitions + sync)
├── mcp-server/    # TypeScript · Cloudflare Worker — personal MCP server
├── cron/          # TypeScript · Cloudflare Worker — scheduled triggers
├── skills/        # Agent Skills (SKILL.md) for Vibe Work
├── shared/        # crm.json — single source of truth (IDs, schema, vocab)
├── docs/          # CRM.md (workflow map), architecture.md (infra rationale)
├── README.md      # this file
└── CLAUDE.md      # engineering conventions across the monorepo
```

## Getting started

Each pillar is self-contained. Start with the workflows:

```bash
cd workflows
uv sync
make start-worker          # run the Mistral Workflows worker
make crm-classify          # trigger the CRM classifier (no OAuth; safe first run)
```

See [`workflows/README.md`](workflows/README.md) for all workflow commands and
[`docs/CRM.md`](docs/CRM.md) for the CRM workflow map. The MCP server and skills have their own
READMEs as they come online.

## Status

- ✅ Workflows pillar: 4 CRM workflows + shared package, verified against the live agent.
- 🚧 MCP server, container hosting, cron trigger, and skills: in progress (see the build plan).

> Personal project. `shared/crm.json` contains non-secret identifiers (agent id, Notion data-source
> IDs) — usable only with my API key/OAuth, which never leave the gitignored `.env` / Worker secrets.
