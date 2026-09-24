import { Container, getContainer } from "@cloudflare/containers";

export interface Env {
  WORKFLOWS_WORKER: DurableObjectNamespace<WorkflowsWorker>;
  MISTRAL_API_KEY: string;
  SERVER_URL: string;
  DEPLOYMENT_NAME: string;
}

/**
 * Hosts the Mistral Workflows worker as a scale-to-zero container.
 *
 * The container runs the Python poller (CMD in the repo-root Dockerfile) and
 * serves the SDK health server on port 8080 so this Worker can wake / keep it
 * alive. ``sleepAfter`` gives a run time to finish before the container
 * sleeps; if it sleeps mid-run the execution simply resumes (durable in
 * Mistral) — and the metronom re-wakes it on the next tick anyway.
 */
export class WorkflowsWorker extends Container<Env> {
  defaultPort = 8080; // HEALTH_SERVER_PORT in the Dockerfile
  sleepAfter = "20m";

  // Pass the worker's runtime config into the container process (this.env is the
  // Durable Object env, populated by the base constructor before this runs).
  envVars = {
    MISTRAL_API_KEY: this.env.MISTRAL_API_KEY,
    DEPLOYMENT_NAME: this.env.DEPLOYMENT_NAME ?? "cloudflare",
  };
}

/**
 * The metronom asks Mistral exactly one question: are there executions waiting
 * for THIS deployment? Schedules live in Studio (account-level, server-side)
 * and fire whether or not this container is awake — the durable execution
 * waits for a worker, and this Worker bridges the gap by waking the container.
 *
 * Deliberately schedule-agnostic: no workflow names, no inputs, no times.
 * Adding, changing, pausing or deleting a schedule happens in Studio and
 * requires NO change here. New workers (more containers) would add one entry
 * to a deployment→container mapping — nothing else.
 */
async function runningRuns(env: Env): Promise<number> {
  const url =
    `${env.SERVER_URL}/v1/workflows/runs?status=RUNNING` +
    `&deployment_name=${encodeURIComponent(env.DEPLOYMENT_NAME)}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${env.MISTRAL_API_KEY}` },
  });
  if (!res.ok) {
    // Fail-quiet: a transient API error must not wake the container 288×/day
    // (that would quietly become an always-on container). The next tick
    // retries; a persistent error surfaces in the logs.
    console.error(`[metronom] runs query failed: HTTP ${res.status}`);
    return 0;
  }
  // The list is called "executions", NOT "runs" — verified live on 2026-09-24
  // against GET /v1/workflows/runs?status=RUNNING. Reading body.runs returned
  // undefined on every tick, so this counted zero and never woke the container.
  const body = (await res.json()) as { executions?: unknown[] };
  return body.executions?.length ?? 0;
}

/** Wake the (singleton) worker container so it is polling when the execution lands. */
async function wakeContainer(env: Env): Promise<void> {
  const container = getContainer(env.WORKFLOWS_WORKER);
  try {
    await container.fetch(new Request("http://container/healthz"));
  } catch {
    // The first request after sleep is what wakes it; errors here are fine.
  }
}

async function metronom(env: Env): Promise<void> {
  const anzahl = await runningRuns(env);
  if (anzahl > 0) {
    await wakeContainer(env);
    console.log(
      `[metronom] ${anzahl} execution(s) running for deployment ` +
        `"${env.DEPLOYMENT_NAME}" — container woken.`,
    );
  } else {
    console.log(`[metronom] nothing running for "${env.DEPLOYMENT_NAME}" — staying asleep.`);
  }
}

export default {
  // Every 5 minutes: ask Mistral if work is waiting for this deployment,
  // wake the container only if it is. The schedule itself lives in Studio.
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(metronom(env));
  },

  // GET /  → metronom logic on demand (manual check without waiting for a tick).
  // POST /wake → force-wake the container (bootstrap: first registration of the
  //              deployment, or ops). Guarded by the Mistral API key.
  // Anything else → proxied to the container.
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const { pathname } = new URL(request.url);
    const authorized = request.headers.get("Authorization") === `Bearer ${env.MISTRAL_API_KEY}`;

    if (pathname === "/wake") {
      if (!authorized) return new Response("unauthorized\n", { status: 401 });
      ctx.waitUntil(wakeContainer(env));
      return new Response(`waking container for deployment "${env.DEPLOYMENT_NAME}"\n`);
    }

    if (pathname === "/") {
      if (!authorized) return new Response("unauthorized\n", { status: 401 });
      const anzahl = await runningRuns(env);
      return new Response(
        `deployment "${env.DEPLOYMENT_NAME}": ${anzahl} execution(s) running` +
          (anzahl > 0 ? " — container woken.\n" : " — nothing to do.\n"),
      );
    }

    return getContainer(env.WORKFLOWS_WORKER).fetch(request);
  },
}
