# cron — scheduled triggers

A tiny **Cloudflare Cron Worker** that fires the scheduled workflow runs. It exists because Mistral's
in-SDK scheduler can't drive OAuth-connector workflows (see
[`../docs/architecture.md`](../docs/architecture.md)) — so the *clock* lives here, while all the work
stays in Mistral Workflows.

> 🚧 Built in Phase 4.

## What it does

- `wrangler.jsonc`: `"triggers": { "crons": ["0 7 * * *", "0 17 * * *"] }` (2×/day).
- A `scheduled()` handler that (1) wakes the workflows Container and (2) `fetch`es
  `POST /v1/workflows/crm-ingest-recent/execute` with the Mistral API key (a Worker secret).
- Test locally: `wrangler dev --test-scheduled` then hit `/__scheduled`.
