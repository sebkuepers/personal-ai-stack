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
 * alive. ``sleepAfter`` gives a batch run time to finish before the container
 * sleeps; if it sleeps mid-run the execution simply resumes (durable in Mistral).
 */
export class WorkflowsWorker extends Container<Env> {
  defaultPort = 8080; // HEALTH_SERVER_PORT in the Dockerfile
  sleepAfter = "20m";

  // Pass the worker's runtime config into the container process (this.env is the
  // Durable Object env, populated by the base constructor before this runs).
  envVars = {
    MISTRAL_API_KEY: this.env.MISTRAL_API_KEY,
    DEPLOYMENT_NAME: this.env.DEPLOYMENT_NAME ?? "personal-ai-stack",
  };
}

const BATCH_INPUT = { window_hours: 13, max_emails: 50, dry_run: false };

/** Start the batch ingest workflow (fire-and-forget) via the Mistral execute API. */
async function triggerIngest(env: Env): Promise<Response> {
  return fetch(`${env.SERVER_URL}/v1/workflows/crm-ingest-recent/execute`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.MISTRAL_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ input: BATCH_INPUT, deployment_name: env.DEPLOYMENT_NAME }),
  });
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

export default {
  // Cron (08:00 & 18:00): make sure the worker is awake, then kick off the batch.
  async scheduled(_event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(wakeContainer(env));
    ctx.waitUntil(triggerIngest(env).then(() => undefined));
  },

  // Manual: GET /trigger runs the batch now; any other path wakes/proxies the container.
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const { pathname } = new URL(request.url);
    if (pathname === "/trigger") {
      ctx.waitUntil(wakeContainer(env));
      const res = await triggerIngest(env);
      return new Response(`triggered crm-ingest-recent (HTTP ${res.status})\n`);
    }
    return getContainer(env.WORKFLOWS_WORKER).fetch(request);
  },
};
