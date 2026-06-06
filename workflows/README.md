# crm-workflows

A personal-CRM autopilot built on [Mistral Workflows](https://docs.mistral.ai/studio-api/workflows/getting-started/overview)
— durable, multi-step AI processes that wire together a Studio **classification
agent** and the **Notion** + **Gmail** connectors.

The workflows *reuse* existing Studio assets — they trigger the agent and
reference the connectors; nothing is recreated. Because the runtime is durable,
every step is crash-safe, retried, and observable in Studio.

- 📍 **Workflow map & how to run:** [../docs/CRM.md](../docs/CRM.md)
- 🛠 **Engineering conventions & gotchas (for contributors / AI agents):** [CLAUDE.md](CLAUDE.md)
- 🏗 **Whole-system overview:** [../README.md](../README.md) · [../docs/architecture.md](../docs/architecture.md)

---

## What it does

```
 raw text / email ─► CRM Classification Agent (Studio, triggered as-is)
                          │  structured JSON
                          ▼
                  deterministic mapping ─► Notion-shaped "intended writes"
                          │
        ┌─────────────────┼──────────────────┐
        ▼ dry run          ▼ write             ▼ assistant
  classify & report   write to Notion CRM   follow-up digest → Gmail drafts
```

| Workflow | Category | Connectors | Writes? | What it does |
|---|---|---|---|---|
| `crm-interaction-classifier` | core | none | dry run | Classify one interaction; show the exact Notion writes it *would* make |
| `crm-notion-sync` | write | notion | **yes** | Classify, then find-or-create Contact + Org and create the Interaction |
| `crm-email-triage` | inbox | gmail | dry run | Pull recent Gmail, classify each, return a triage report |
| `crm-followup-digest` | assistant | notion + gmail | drafts only | Find due follow-ups in Notion, draft reminder emails (never sends) |

---

## Setup

Requires Python 3.12+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync
```

Create a `.env` (already present locally, git-ignored) with:

```
MISTRAL_API_KEY=...        # from console.mistral.ai/api-keys
SERVER_URL=https://api.mistral.ai
DEPLOYMENT_NAME=<your-hostname>
```

---

## Run

Start the worker (auto-discovers every workflow in `src/workflows/`):

```bash
make start-worker
```

In another terminal, trigger one:

```bash
make crm-classify        # core — no OAuth, safest first run
make crm-sync            # writes to Notion (first run prompts Notion OAuth)
make crm-triage-inbox    # reads Gmail   (first run prompts Gmail OAuth)
make crm-digest          # Notion + Gmail; drafts reminders
```

With custom input:

```bash
make crm-classify input='{"text":"...","subject":"...","interaction_type":"Email"}'
```

You can also trigger any workflow from the Studio Console (**Workflows** tab).

> **First connector run pauses for OAuth.** Connector workflows are
> `on_behalf_of=True`; the first execution emits an auth URL (shown in the Studio
> UI / worker logs). Authorise once — later runs are non-interactive.

---

## Project layout

```
src/
├── entrypoints/            # python -m entrypoints.<module>
│   ├── worker.py           #   discover + run workflows
│   ├── start.py            #   trigger a workflow execution
│   └── dev.py              #   worker with file-watch reload  (make start-worker)
├── workflows/              # the personal-CRM workflows (auto-discovered)
│   ├── crm/                #   shared package — config, models, classify, tools, notion
│   ├── crm_interaction_classifier.py
│   ├── crm_notion_sync.py
│   ├── crm_email_triage.py
│   └── crm_followup_digest.py
└── examples/               # SDK cookbooks (opt-in: make start-examples)
```

All IDs, connector slugs, model names, and vocabularies live in one file:
[`src/workflows/crm/config.py`](src/workflows/crm/config.py).

---

## Development

```bash
uv run ruff format .        # format
uv run ruff check --fix .   # lint

# Offline sanity check — imports every workflow, no cloud needed:
uv run python -c "from entrypoints.worker import discover_workflows as d; print('discovered', len(d()))"
```

To **add a workflow**: drop a top-level module in `src/workflows/` and restart
the worker. See [CLAUDE.md](CLAUDE.md) for the full recipe, the verified SDK
cheat-sheet, and the gotchas (sandbox imports, connector slugs, agent-trigger vs
overwrite, `on_behalf_of` + scheduling, …).

---

## SDK examples

`src/examples/` ships Mistral's cookbooks (not loaded by `make start-worker`):
Insurance Claims Triage, Cargo Release Compliance, Code Modernization. Run them
with `make start-examples` + `make execute-insurance-claims` (etc.).
