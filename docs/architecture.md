# Architecture & infrastructure decisions

Why this system is shaped the way it is. Written so a future me (or an agent) doesn't re-litigate
decisions that were already reasoned through.

## The system in one picture

```
 Cloudflare worker-host  ──cron 08:00 & 18:00──►  POST /v1/workflows/{name}/execute   [serverless]
   ├─ hosts the Mistral Workflows worker (Docker, ALL workflows)                       [scale-to-zero container]
   └─ scheduled() trigger + wakes the container
 Cloudflare MCP Worker (mcp-server/) ──registered as a Mistral custom connector        [serverless]
        │  consumed by Studio agents · Le Chat · Vibe Work · workflow durable agents
 Skills (skills/)  ──teach Vibe Work when/how to use the MCP tools + workflows
        ▼
 Mistral Studio  →  agents · connectors (notion / gmail) · durable orchestration · observability
```

## Decisions

### 1. Keep Mistral Workflows as the orchestrator
Not a generic queue, not raw Temporal, not Cloudflare Workflows. The reasons:
- **Durable execution** — crash-safe, exactly-once activities, deterministic replay, runs for months.
- **AI-aware observability** — every activity emits an OpenTelemetry span; the Studio "Executions"
  timeline shows each step, parallel task, retry, and branch; full history is queryable via the
  trace REST API. We get this with **zero ops** (Mistral runs Temporal/Postgres/NATS/Tempo/Grafana).
- **Native AI integration** — trigger Studio agents, attach connectors, run durable agents, all
  first-class.

### 2. The schedule lives just outside Mistral
Mistral's in-SDK `Schedule` **cannot** be combined with `on_behalf_of=True`, and connector
workflows are strictly user-OBO (verified in the SDK's connector auth interceptor — it only ever
resolves *user* credentials). A scheduled run has no user OAuth session, so it can't drive a
connector workflow.

→ So a tiny **Cloudflare Cron Worker** calls the Mistral execute API on a schedule. The clock is
external; **all the actual work stays inside Mistral Workflows**. This is one ~3-line `fetch`, not a
second orchestration system.

### 3. The worker runs in a scale-to-zero Cloudflare Container
The Mistral Workflows worker is a long-lived Python/Temporal **poller** with native dependencies —
it cannot run in a Cloudflare Worker isolate (wrong runtime; isolates don't poll). Cloudflare
**Containers** (public beta, 2025) run full Docker images and **scale to zero**: billed per 10ms of
active time, asleep (via `sleepAfter`) otherwise, woken on request (~1–3s cold start). So the worker
exists only for the minutes around each run — no always-on daemon. Durability lives in Mistral's
cloud, so sleeping between runs loses nothing; a paused (e.g. awaiting OAuth) run resumes when the
container is next awake.

### 4. The MCP server is a Cloudflare Worker
The personal MCP server is **inbound HTTPS** (Mistral's cloud calls *it* when an agent uses a tool)
— the exact shape a serverless Worker is built for. Cloudflare has first-class remote-MCP support
(`McpAgent`). It registers with Mistral as a **custom connector**; once attached to an agent, the
model auto-discovers the tools and **Mistral executes them server-side** — the workflow never pings
the MCP itself. The same server is therefore reachable from Studio, Le Chat, Vibe Work, and the
workflow durable agents: one function library, used everywhere.

### 5. Skills teach Vibe Work
Personal skills are Agent Skills (`SKILL.md`, the open standard Mistral Vibe adopted from Anthropic).
They are declarative — they describe *when* to use a capability and point at the MCP tools and
workflows. Version-controlled here alongside the things they describe.

## Cadence: 2×/day batch, not per-email
For a personal CRM, real-time per-email triggering needs an always-on event source (Gmail
watch/Pub-Sub or Apps Script) + webhooks for marginal benefit. A twice-daily batch
(`crm-ingest-recent`: read ~13h of Gmail inbox+sent, dedup vs Notion, classify, write) is the
pragmatic sweet spot. If real-time is ever wanted, the event source POSTs to the same workflow.

## Cost
Roughly the **$5/mo Cloudflare Workers Standard floor** covers everything at this scale — the
Standard plan includes generous container compute (25 GiB-hrs RAM, 375 vCPU-min, 200 GB-hrs disk)
that two short batch runs/day don't approach. Mistral usage is separate (agent + connector calls).

## Operational caveats
- **OBO re-auth:** connector OAuth tokens can lapse; an unattended run then *pauses* (durably, in
  Mistral) for re-authorization and resumes once re-authed and the worker is awake. Expect occasional
  re-auth.
- **Cloudflare Containers** is public beta.
- **Gmail connector can only draft, not send.**

## Source of truth
`shared/crm.json` holds the agent id, Notion data-source IDs, connector slugs/tools, and the category
vocabulary. Python (`workflows/src/workflows/crm/config.py`) and the TS MCP server both read it.
