# AGENTS.md — personal-ai-stack

Pointer file for AI coding agents (Vibe and friends). The full guidance lives in
[`CLAUDE.md`](CLAUDE.md) — read it before touching anything, then the pillar doc
for the part you're changing:

| Touching… | Read first |
|---|---|
| `workflows/` (any workflow code) | [`workflows/CLAUDE.md`](workflows/CLAUDE.md) — verified SDK conventions + 16 gotchas |
| `mcp-server/` | [`mcp-server/README.md`](mcp-server/README.md) |
| the CRM domain | [`docs/CRM.md`](docs/CRM.md) + `agents/README.md` |
| the book domain | [`docs/BOOK.md`](docs/BOOK.md) |
| the inbox domain | [`docs/INBOX.md`](docs/INBOX.md) |

## Golden rules (short form — details and rationale in CLAUDE.md)

1. **Reuse, don't recreate.** Trigger existing Studio agents, reference existing
   connectors, read IDs from `shared/<domain>.json`. Never hardcode an ID or
   re-implement an agent's prompt in code.
2. **`shared/<domain>.json` is the single source of truth.** IDs, connector
   slugs, models and vocabularies live there — never in Python, never in
   TypeScript. Each domain has a config module that loads it
   (`workflows/src/workflows/<domain>/config.py`).
3. **Domain ≠ work.** Agents, workflows and skills are named `<domain>-*`;
   the concrete subject comes in as a parameter (`werk=<slug>`). Per-subject
   config lives in `shared/<domain>/<slug>.json`.
4. **This is a Mistral Pro account.** Judges, Datasets and Traces
   (`/v1/observability/*`) are Enterprise-only (HTTP 404). The repo has its own
   substitutes: `workflows/src/evalkit/` for measurement, judge *agents* for
   scoring. Check the table in [`README.md`](README.md) before assuming a
   feature exists.
5. **Verify against the installed SDK / live API, not from memory.** Ground
   truth: the venv (`workflows/.venv/.../plugins/mistralai/`) and
   `client.beta.connectors.list_async()` / `.agents.list_async()`.
6. **The repo is public, the work is not.** No secrets, no manuscript text, no
   real names. Werk configs, voice profiles and `workflows/data/` are gitignored
   — keep them that way.
7. **Measure before you tune.** Model and setting changes are justified by
   `evalkit` runs, with the numbers recorded next to the setting they justify.
8. **I/O lives in activities, never in the workflow body.** The body is
   replayed; an activity reads once and its result is in the event history.
9. **The repo language is English.** We *converse* in German, but everything
   the repo owns — identifiers, module and workflow names, agent names, schema
   fields, config keys, Gmail/Mistral labels, docs and commit messages — is
   English (like `crm`, like `inbox`). German stays where the *subject matter*
   is German: agent instructions that classify German emails or edit German
   manuscripts, the controlled vocabularies they use, the eval cases, and
   everything Sebastian reads (digests, CLI output, Studio display names).
   Full rule and rationale: [`CLAUDE.md`](CLAUDE.md).

## Verify before you call it done

From `workflows/` (Python side):

```bash
uv run ruff check src/workflows src/bookcli src/evalkit ../agents tests/
uv run pytest tests/ -q
uv run python -c "from entrypoints.worker import discover_workflows as d; print(len(d()))"
```

For `mcp-server/` and `worker-host/`: `npm run typecheck`. CI runs all of these
on every push (`.github/workflows/ci.yml`).
