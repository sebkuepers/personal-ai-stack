# CLAUDE.md — building Mistral Workflows in this repo

Guidance for AI agents (and humans) working in this project. It captures the
**verified** conventions, exact SDK symbols, and the gotchas that cost real
debugging time. Everything here was confirmed against the installed SDK
(`mistralai-workflows[mistralai]>=3.0.0`) and this account's live Studio.

> **Golden rules**
> 1. **Reuse, don't recreate.** Trigger existing Studio agents and reference
>    existing connectors. Never re-implement an agent's prompt or register a
>    new connector for something that already exists.
> 2. **Verify symbols against the installed SDK, not from memory.** The local
>    docs live in `.agents/skills/workflows/references/`; the working examples
>    live in the venv (see "Finding ground truth").
> 3. **Run the offline discovery check after every change** (see "Verifying").

---

## 1. Mental model

Mistral Workflows is a **Python SDK for durable, multi-step programs**, built on
Temporal. Not a visual builder. Four concepts:

- **Workflow** — the deterministic "brain." Orchestrates steps, holds state, can
  wait seconds→months. Its body is *replayed* on recovery, so it must be
  deterministic: no clock reads, no randomness, no direct I/O.
- **Activity** — the "hands." Any I/O (LLM call, HTTP, connector tool, reading
  the clock). Gets retries, distributed scheduling, per-call observability.
- **Worker** — a process on *your* machine that runs the code and connects
  *outbound* to Mistral. `make start-worker`.
- **Studio (cloud)** — hosts the orchestrator, UI, and the REST API that
  triggers workflows. Stores the event history (why crashes don't lose work).

---

## 2. Project layout & auto-discovery

```
src/
├── entrypoints/            # python -m entrypoints.<module>
│   ├── worker.py           #   discovers + runs workflows
│   ├── dev.py              #   worker + file-watch reload  (make start-worker)
│   └── start.py            #   triggers an execution        (make execute ...)
├── workflows/              # YOUR workflows — auto-discovered, recursively
│   ├── crm/                #   domain package: shared code AND workflows
│   ├── book/               #   domain package (agents, models, scrivener, typeset/)
│   ├── crm_*.py            #   top-level workflows
│   └── lektorat.py …       #   top-level workflows of the book domain
└── examples/               # cookbooks (opt-in: make start-examples)
```

**How discovery works** (`entrypoints/worker.py`): it walks the **whole** `workflows`
package for any class carrying `__workflows_workflow_def` (set by
`@workflows.workflow.define`). Consequences:

- ✅ **Subpackages ARE scanned.** `discover_workflows()` uses `pkgutil.walk_packages`,
  so a workflow class in `workflows/book/copyedit.py` is found. (An earlier
  version of this file said the opposite — it was written before discovery became
  recursive. Results are de-duplicated by identity, so a class imported into
  another module is counted once.)
- **Activities auto-register** via the `@activity()` decorator — `run_worker()`
  only needs the workflow classes; you never list activities.

---

## 3. Recipe: add a new workflow

1. Create `src/workflows/<name>.py` — top level or in a domain subpackage,
   both are found.
2. Import activities through the sandbox boundary; import pure code normally:
   ```python
   import mistralai.workflows as workflows
   from mistralai.workflows import workflow

   with workflow.unsafe.imports_passed_through():
       from workflows.crm.classify import classify_interaction   # activities
   from workflows.crm.models import InteractionInput             # pure (models)
   ```
3. Define the class:
   ```python
   @workflows.workflow.define(name="my-workflow", workflow_display_name="…",
                              workflow_description="…")
   class MyWorkflow:
       @workflows.workflow.entrypoint
       async def run(self, params: InteractionInput) -> SomeModel:
           result = await classify_interaction(params.text)   # activity call
           ...
   ```
4. Add a `make` target in the Makefile (copy an existing `crm-*` target).
5. Run the offline discovery check (section 6). Restart the worker to register.

**Input shape:** a single Pydantic model maps to top-level JSON keys. Multiple
plain params also work. Return a Pydantic model or dict.

---

## 4. SDK cheat-sheet (verified imports)

```python
# Core
import mistralai.workflows as workflows
from mistralai.workflows import workflow, Depends, run_worker, Schedule
from mistralai.workflows import execute_activities_in_parallel

# Decorators
@workflows.activity(retry_policy_max_attempts=3, retry_policy_backoff_coefficient=2.0,
                    start_to_close_timeout=timedelta(seconds=60))
@workflows.workflow.define(name="…", on_behalf_of=False, schedules=None)
@workflows.workflow.entrypoint

# LLM plugin
from mistralai.client import models as mistralai_models   # ChatCompletionRequest,
#   UserMessage, SystemMessage, TextChunk, ImageURLChunk, ConversationRequest, …
from mistralai.workflows.plugins.mistralai.activities import (
    chat_parse_to_model,              # (Model, request) -> validated Model  (structured output)
    mistralai_chat_complete,          # (request) -> ChatCompletionResponse
    mistralai_start_conversation,     # (ConversationRequest) -> ConversationResponse  (trigger an agent)
    mistralai_append_conversation,
)

# Durable agents
import mistralai.workflows.plugins.mistralai as wf_mistral   # Agent, Runner, RemoteSession,
#   LocalSession, MCPStdioConfig, MCPSSEConfig
agent = wf_mistral.Agent(model="mistral-medium-latest", name="…", instructions="…",
                         tools=[some_activity], handoffs=[other_agent],
                         connectors=[slot], mcp_clients=[cfg])
outputs = await wf_mistral.Runner.run(agent=agent, inputs="…")   # session optional

# Connectors
from mistralai.workflows.plugins.mistralai.connectors import (
    connector, ToolCallClient, uses_connectors, ConnectorSlot,
)
```

**Structured output**: prefer `chat_parse_to_model(MyModel, request)` — it
validates against your Pydantic model and the worker retries on mismatch.

**Models default to `mistral-medium-latest`**; vision uses `mistral-small-latest`
in the examples.

---

## 5. ⚠️ Gotchas that cost time

1. **Sandbox imports.** Workflow files must import any activity (anything that
   imports `mistralai.client`/httpx) inside
   `with workflow.unsafe.imports_passed_through():` — otherwise the Temporal
   sandbox raises on `urllib`/`httpx` import. Pure modules (models, config) are
   imported normally.

2. **Don't shadow types with field names.** A Pydantic field named `date` with
   annotation `date | None` evaluates to `None | None` under
   `from __future__ import annotations` →
   `TypeError: unsupported operand for |`. We renamed the field to `occurred_on`.
   Same trap for any field named after its type.

3. **Connector identifiers are lowercase slugs, NOT display names.** Studio shows
   "Notion"/"Gmail"; the API slugs are `notion`/`gmail`. `connector("Notion")`
   may not resolve. Always confirm with `client.beta.connectors.list_async()`.

4. **Triggering an existing agent vs. overwriting it.**
   - ✅ **Trigger** (read-only): `mistralai_start_conversation(ConversationRequest(
     agent_id=…, inputs=…, store=False))`. Leaves the remote agent untouched.
   - ❌ **`Agent(id="ag_…")` + `Runner.run`** is documented to *update/overwrite*
     the remote agent from the (often sparse) fields you pass. Don't use it to
     "call" an existing carefully-built agent.

5. **`on_behalf_of=True` cannot combine with `schedules=[...]`.** The SDK raises.
   A scheduled run has no user OAuth session. Schedule connector workflows
   externally (cron / executions API); use in-SDK `Schedule` only for
   non-connector workflows.

6. **Connector workflows need `on_behalf_of=True` + `@uses_connectors(...)`** and
   pause on first run for OAuth (auth URL appears in the UI/logs, ~10-min window).

7. **Gmail connector can only DRAFT, not send** (`create_draft`). Good for
   safety; don't write a "send email" step expecting it to exist.

8. **`store=False`** on `ConversationRequest` avoids persisting throwaway
   classification conversations in Studio.

9. **`Path(__file__).resolve()` blows up the sandbox.** Temporal forbids
   `pathlib.Path.resolve` in workflow code. A `config.py` that looks for a file
   at import time therefore drags down **every** module that imports it
   directly or transitively (including via `connectors.py`) — the worker then
   does not start at all. `__file__` is absolute at import anyway, so just use
   `Path(__file__)` without `.resolve()`. Important: the offline discovery check
   does **not** catch this, because it only imports and does not validate. Only
   a real worker start shows it.

10. **Passthrough applies to module *names*, not to package attributes.** Inside
    `imports_passed_through()`, `from package.module import X` and
    `import package.module as m` work, but `from package import module` does not
    — Python resolves that as an attribute access and the sandbox still bites.

11. **Conversational workflows: the input schema decides how it starts.** A
    `@le_chat_input` model tolerates **no** extra field and **no** `message` with
    a default — either makes Vibe fall back to a raw JSON editor. With `message`
    as a required field Le Chat asks for the typed message a second time. If you
    do not need it, define **no** input schema at all; then the workflow starts
    immediately. Measured against the live object, in that order.

12. **Vibe does not render the `TodoList` in the transcript** but as a fixed
    field above the input box — and only while the context manager is open. Wrap
    it around a short step only and it is gone before anyone looks. It belongs
    around the whole session, waiting times for input included.

13. **There is no table component and no selectable table row.** Per the docs:
    `SingleChoice` is a dropdown, `ConfirmationInput` are buttons, and that is
    all. A table to scan plus **one** form to choose from is the only usable
    shape; a row of buttons repeating every table row is the same list twice.

14. **`strict: true` enforces enums, but not numeric types.** A `list[int]` in
    the schema does not stop the model from delivering strings. And a field with
16. **A rename leaves its predecessor behind — in two places.** Studio keeps a
    workflow registration until someone removes it, so after renaming
    `buch-korrektorat` to `book-copyedit` both sit in the list and the old one
    is indistinguishable from a live one. The same for agents: `Buch · Judge`
    outlived the design it belonged to by weeks. Workflows have **no delete**,
    only `archive_workflow` / `bulk_archive_workflows` (reversible via
    `unarchive_workflow`); agents have **only delete**, which is not. Also note
    that `workflow_display_name` is set at *registration* — after changing it,
    Studio shows the old one until the worker restarts, or you push it with
    `workflows.update_workflow(display_name=…)`.
    `make archive-stale` compares both against the repo — workflows against
    `discover_workflows()`, agents against the `name` fields in `agents/*.json`
    — and cleans up whatever it no longer defines. Preview is the default.

17. **Never edit a workflow while one of its sessions is open.** A conversational
    workflow is replayed from its event history on every input. `make start-worker`
    watches files and reloads, so an edit mid-session makes the replay diverge:
    `determinism error: No command scheduled for event …`. In the chat nothing
    happens at all — the Send button simply does nothing, with no error. The
    session is unrecoverable; start a new one. During a test run, stop editing.

18. **Scaffold bug:** `pyproject.toml` shipped `[tool.uv] exclude-newer = "7 days"`
   which uv rejects (wants an RFC3339 date). Removed; deps are pinned in
   `uv.lock`.

---

## 6. Connector & agent patterns

**A. Direct tool call (deterministic, known inputs):**
```python
@workflows.activity()
async def create_page(title: str, notion: ToolCallClient = Depends(notion_connector)):
    return await notion.call_tool(tool_name="notion-create-pages", arguments={...})
```

**B. Agent-driven (model discovers & calls the right MCP tools):**
```python
agent = wf_mistral.Agent(name="writer", model=AGENT_MODEL,
                         instructions=SCHEMA_CONTEXT, connectors=[notion_connector])
outputs = await wf_mistral.Runner.run(agent=agent, inputs=task_text)
```
Prefer **B** when the exact tool names/arg schemas are uncertain (e.g.
find-or-create-relate across Notion). Prefer **A** for fixed, audited writes.

Read a durable agent's text output via an **activity** (it imports the client):
```python
@workflows.activity(name="extract-agent-text")
async def extract_agent_text(outputs: object) -> str:
    from mistralai.client import models as m
    return "\n".join(c.text for c in outputs if isinstance(c, m.TextChunk))
```

---

## 7. Verifying changes (do this every time)

```bash
# 1. Lint
uv run ruff check src/workflows

# 2. Offline discovery — catches import/syntax/annotation errors WITHOUT the cloud
uv run python -c "from entrypoints.worker import discover_workflows as d; \
print('discovered', len(d()))"        # 15 as of 2026-09-24

# 3. (optional) Live smoke test of the agent path — triggers the real agent,
#    no worker/Temporal needed. See the pattern used during the initial build:
#    Mistral().beta.conversations.start_async(...) -> _extract_text -> _parse.
```
Discovery imports every workflow module, so it surfaces most breakage instantly.
It does **not** connect to Mistral until `run_worker()`.

**Finding ground truth** when unsure about a symbol:
```bash
PKG=$(.venv/bin/python -c "import mistralai.workflows,os;print(os.path.dirname(mistralai.workflows.__file__))")
ls "$PKG/plugins/mistralai/"                       # agent.py, runner.py, connectors/, …
ls "$PKG/plugins/mistralai/connectors/examples/"   # WORKING notion/github examples
```
The `connectors/examples/` files are the most reliable reference for the exact,
version-correct calling conventions.

---

## 8. This project's specifics

- **Single source of truth:** `../shared/crm.json` (agent id, Notion data-source IDs, connector
  slugs, tool names, vocabularies, user aliases). `src/workflows/crm/config.py` loads it and
  re-exposes the constants — edit the JSON, not the Python.
- **The agent owns classification** — there is deliberately no classifier prompt
  in this repo (`prompts.py` only holds the Notion-writer context). Keep it that
  way so the two can't drift.
- **Mapping decisions** live in `agent_tools.classification_to_triage`:
  `category="unknown"` → empty Notion select; `priority` → Contact not
  Interaction; `action_items` → folded into AI Analysis; self filtered out.
- See **../docs/CRM.md** for the workflow map and **README.md** for setup/run.
- When you change a connector/agent in Studio, re-confirm IDs/slugs/tool names
  with `client.beta.connectors.list_async()` / `client.beta.agents.list_async()`
  and update `config.py`.
