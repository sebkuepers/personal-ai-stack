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

The workflows pillar currently hosts **two domains**: the personal CRM and a **book-editing**
domain that supports writing manuscripts in Scrivener — export, a distilled *voice profile*, and
layered copy-editing. See [`docs/BUCH.md`](docs/BUCH.md).

A fourth folder, [`worker-host/`](worker-host/), is the Cloudflare Worker that hosts the workflows
worker in a scale-to-zero container **and** triggers the scheduled batch runs (cron).
[`shared/crm.json`](shared/crm.json) is the **single source of truth** (IDs, schema, vocab) that both
the Python and TypeScript sides read.

## Architecture

```
 Cloudflare worker-host       ──cron 08:00 & 18:00──►  Mistral execute API
   ├─ hosts the Mistral Workflows worker (Docker, all workflows)              [scale-to-zero container]
   └─ scheduled() trigger for the batch ingest                               [serverless]
 Cloudflare MCP Worker (mcp-server/)──registered as a Mistral custom connector  [serverless]
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

## Built for a Mistral **Pro** account — and what that changes

This repo is deliberately shaped around a single-seat **Pro** plan. Several Studio features exist
but are not reachable from such an account, so the repo solves those jobs itself. All of this was
**verified against the live API**, not inferred from docs — with dates and method, so it can be
re-checked when Mistral changes something.

| Studio feature | On this account | How the repo solves it instead |
|---|---|---|
| **Judges** (`/v1/observability/judges`) | ✗ HTTP 404 · *"Private Preview … Enterprise-tier organizations only"* | A second-reader **agent** with a strict schema, called as a normal workflow step. It sees the same input as the first stage, so a later migration stays small — Mistral's judge also scores a response in the context of its request. |
| **Datasets / Campaigns** (`/v1/observability/*`) | ✗ HTTP 404 (`campaigns` is gone from the SDK entirely) | `evalkit/` — a domain-independent harness: cases × configurations → hit rate and trap rate. |
| **Traces / Explorer** | ✗ Enterprise only | Studio's execution timeline still shows every workflow run, retry and failure — that part is not gated. |
| **Prompts** (`/v2/prompts`) | ✓ available | `prompts/` + `prompts/sync.py` |
| **Skills** (`/v2/skills`) | ✓ available | `skills/` + `skills/sync.py` |
| **Libraries** (`/v1/libraries`) | ✓ available | `buchcli.sync --library` |

**Two 404s that mean different things.** `{"detail":"Not Found"}` comes from the application — the
route exists, the account may not use it. `{"message":"no Route matched with those values"}` comes
from the gateway — that path does not exist at all. Worth distinguishing before concluding a feature
is missing; it cost one wrong conclusion here (`/v1/prompts` vs. the real `/v2/prompts`).

### Not a plan limit, but an API limit

Two things are unavailable to *everyone*, regardless of plan — verified with control probes against
`/v1/chat/completions`, `/v1/conversations` and `/v1/agents`, all of which reject unknown fields
with `extra_forbidden`:

- **A Studio agent cannot load a Skill.** Allowed tool types are `code_interpreter`, `connector`,
  `document_library`, `function`, `image_generation`, `web_search` — there is no skill type, and
  `CreateAgentRequest` has no such field. Skills apply to **Vibe Work, Vibe Code and Projects**.
- **No API call can reference a stored Prompt by id.** Prompts are a versioned text library; you
  fetch the text and send it yourself.

Details and the exact test method: [`docs/BUCH.md`](docs/BUCH.md).

## Repository layout

```
personal-ai-stack/
├── workflows/     # Python · Mistral Workflows worker  (see workflows/README.md, workflows/CLAUDE.md)
├── agents/        # Mistral agents as code (definitions + sync)
├── mcp-server/    # TypeScript · Cloudflare Worker — personal MCP server
├── worker-host/   # TypeScript · Cloudflare Worker — hosts the worker container + cron
├── Dockerfile     # the workflows worker image (built by worker-host)
├── skills/        # Agent Skills (SKILL.md) for Vibe Work
├── shared/        # one <domain>.json per domain — single source of truth (IDs, schema, vocab)
├── docs/          # CRM.md, BUCH.md (workflow maps), architecture.md (infra rationale)
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

- ✅ **CRM domain**: 5 workflows + shared package, verified against the live agent.
- ✅ **Book domain**: Scrivener export (RTF round-trip verified against `textutil`), 5 Studio
  agents, and the `buch-stimmprofil` map/reduce workflow. See [`docs/BUCH.md`](docs/BUCH.md).
- ✅ MCP server, container hosting, cron trigger, and skills: built (Phases 1–5).
- 🚧 Book domain: write-back to Scrivener, the conversational editing workflow, and PDF
  typesetting are next.

> Personal project. `shared/crm.json` contains non-secret identifiers (agent id, Notion data-source
> IDs) — usable only with my API key/OAuth, which never leave the gitignored `.env` / Worker secrets.
