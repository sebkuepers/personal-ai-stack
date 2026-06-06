# worker-host — container host + scheduler

One Cloudflare Worker that does two jobs:

1. **Hosts the Mistral Workflows worker** as a scale-to-zero container
   (`WorkflowsWorker extends Container`, image = the repo-root `Dockerfile`,
   `sleepAfter: 20m`). The worker is an outbound poller that also serves the SDK
   health server on port 8080 so this Worker can wake / keep it alive.
2. **Triggers the batch** — a `scheduled()` cron (08:00 & 18:00) wakes the
   container and `POST`s `/v1/workflows/crm-ingest-recent/execute` to Mistral.

`GET /trigger` runs the batch on demand.

## Deploy

```bash
# 0. Docker Desktop must be running (wrangler builds the container image).
cd ~/dev/personal-ai-stack/worker-host
npx wrangler login                       # one-time Cloudflare auth
npx wrangler secret put MISTRAL_API_KEY  # used to trigger + injected into the container
npx wrangler deploy                      # builds the image, deploys the Worker + cron
```

Adjust the schedule in `wrangler.jsonc` (`triggers.crons`) and the batch input in
`src/index.ts` (`BATCH_INPUT`).

## Verified so far

- `tsc` clean; `wrangler deploy --dry-run` bundles; bindings (Durable Object,
  vars) resolve; `../Dockerfile` resolves to the repo-root image.

## Confirm at deploy time

- The container image **build** needs the Docker daemon running (`docker build`
  the repo-root `Dockerfile` to validate independently).
- That a `crm-ingest-recent` execution actually runs on the container and shows
  in the Studio timeline; and that the cron fires (test with
  `wrangler dev --test-scheduled` → `/__scheduled`).
- First run pauses for Gmail + Notion OAuth (on-behalf-of). After authorising,
  later cron runs are non-interactive (until tokens lapse).
