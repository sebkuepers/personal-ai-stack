# worker-host — the remote home of the workflows worker

One Cloudflare Worker with two jobs:

1. **It hosts the Mistral Workflows worker** as a scale-to-zero container
   (`WorkflowsWorker extends Container`, image = the repo-root `Dockerfile`,
   `sleepAfter: 20m`). The worker is an outbound poller; it also serves the SDK
   health server on port 8080, which is how this Worker wakes it.
2. **It is the metronome.** Every five minutes its `scheduled()` asks Mistral one
   question — *are executions waiting for this deployment?* — and wakes the
   container only if the answer is yes. That is ~288 cheap API calls a day
   instead of a container that never sleeps.

It triggers nothing itself. Schedules live in the workflow code
(`@workflow.define(schedules=[…])`) and the worker registers them with Studio at
startup, so adding or changing one needs no deploy here.

## The two deployments

A Mistral *deployment* is a named worker identity, and the repo has exactly two:

| Deployment | Where | Set in | Runs |
|---|---|---|---|
| `macbook-pro` | the laptop, `make start-worker` | `workflows/.env` | whatever is triggered by hand |
| `cloudflare` | this container | `wrangler.jsonc` → `vars.DEPLOYMENT_NAME` | the scheduled rounds |

The names are not cosmetic. A worker registers a workflow's schedules **under its
own deployment name**, so two workers would register two schedules for the same
workflow and the nightly round would run twice. `shared/inbox.json` →
`schedule.deployment` therefore names which deployment owns the schedule;
everywhere else the workflow is trigger-only. A test pins that this name and
`vars.DEPLOYMENT_NAME` here stay the same.

The consequence worth remembering: **the nightly round only runs when this
container is deployed.** On the laptop alone it would fire only while the laptop
happens to be awake, which is precisely what a nightly job must not depend on.

## Deploy

```bash
# 0. Docker Desktop must be running (wrangler builds the container image).
cd ~/dev/personal-ai-stack/worker-host
npx wrangler login                       # one-time Cloudflare auth
npx wrangler secret put MISTRAL_API_KEY  # injected into the container, and used by the metronome
npx wrangler deploy                      # builds the image, deploys the Worker + cron
```

`GET /` runs the metronome check on demand, `POST /wake` force-wakes the
container (both guarded by the API key), anything else is proxied to it.

## Verified

- `tsc` clean; `wrangler deploy --dry-run` bundles; bindings resolve;
  `../Dockerfile` resolves to the repo-root image.
- `GET /v1/workflows/runs?status=RUNNING&deployment_name=…` answers 200 — but its
  list is called **`executions`**, not `runs`. The Worker read `body.runs`,
  counted zero on every tick and never woke the container. Fixed 2026-09-24.

## Confirm at deploy time

- The image **build** needs the Docker daemon (`docker build` the repo-root
  `Dockerfile` to validate it independently).
- That the `cloudflare` deployment appears in
  `client.workflows.deployments.list_deployments()` after the first start.
- That the schedule then shows up with `deployment_name: "cloudflare"` in
  `client.workflows.schedules.get_schedules()` — that is the proof the nightly
  round belongs to the container and not to the laptop.
- The Gmail connector runs as the **deployment**, not on behalf of a user, so no
  OAuth pause is expected. Reading credentials is the worker's API key; see
  `workflows/CLAUDE.md` gotcha 19.
