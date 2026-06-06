# Container image for the Mistral Workflows worker (the workflows/ pillar).
# Build context is the REPO ROOT (it needs both workflows/ and shared/crm.json):
#   docker build -f Dockerfile -t personal-ai-stack-worker .
#
# Runtime env (injected by the host — Cloudflare Container / Fly / VM):
#   MISTRAL_API_KEY   required
#   DEPLOYMENT_NAME   worker/deployment identity (e.g. "personal-ai-stack")
#   HEALTH_SERVER_PORT / HEALTH_SERVER_HOST are baked below so the platform can
#   health-check / wake the container (the worker is otherwise an outbound poller).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# 1) Dependencies first (cached layer): copy only the lockfiles.
COPY workflows/pyproject.toml workflows/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) App code + the shared source of truth.
COPY workflows/src ./src
COPY workflows/worker.py ./worker.py
COPY shared ./shared
RUN uv sync --frozen --no-dev

ENV CRM_CONFIG_PATH=/app/shared/crm.json \
    HEALTH_SERVER_HOST=0.0.0.0 \
    HEALTH_SERVER_PORT=8080 \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Auto-discovers all workflows in src/workflows and starts the worker.
CMD ["uv", "run", "--no-dev", "python", "-m", "entrypoints.worker"]
