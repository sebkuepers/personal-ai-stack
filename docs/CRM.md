# Personal CRM Workflows

Durable Mistral Workflows that wire together your existing Studio assets — the
**CRM Classification Agent** and the **Notion** + **Gmail** connectors — into a
personal-CRM autopilot. Nothing here re-implements your agent or re-creates a
connector; the workflows *trigger* and *reference* what you already built.

## The pieces (all already in your Studio account)

| Asset | What it is | How the workflows use it |
|---|---|---|
| `CRM - Classification Agent` (`ag_019e98…ae79`) | Your Studio agent with its prompt + JSON schema | **Triggered** via the Conversations API — never modified |
| `notion` connector | Your Notion CRM (Organizations / Contacts / Interactions / Projects) | Read + write via durable agent tools |
| `gmail` connector | Your inbox | Read + **draft** (the connector cannot send) |

Config lives in one place: [`../shared/crm.json`](../shared/crm.json) (loaded by
[`../workflows/src/workflows/crm/config.py`](../workflows/src/workflows/crm/config.py)).

## The four workflows

| Workflow | Category | Connectors | Writes? | What it does |
|---|---|---|---|---|
| `crm-interaction-classifier` | core | none | no (dry run) | Classify one interaction → show the exact Notion writes it *would* make |
| `crm-notion-sync` | write | notion | **yes** | Classify, then find-or-create Contact + Org and create the Interaction |
| `crm-email-triage` | inbox | gmail | no (dry run) | Pull recent emails, classify each, return a triage report |
| `crm-followup-digest` | assistant | notion + gmail | drafts only | Find due follow-ups in Notion, draft reminder emails in Gmail |

## How it fits together

```
                 ┌─────────────────────────────┐
 raw text /      │  CRM Classification Agent    │   (your Studio agent,
 email      ───► │  triggered via Conversations │    triggered as-is)
                 └──────────────┬──────────────┘
                                │  structured JSON
                                ▼
                 classification_to_triage()   ← pure mapping (deterministic)
                                │  Notion-shaped "intended writes"
              ┌─────────────────┼──────────────────┐
              ▼ (dry run)        ▼ (write)          ▼ (assistant)
       classifier report   notion-crm-writer    followup-digest
                            agent + `notion`     agent + `notion`+`gmail`
```

## Running them

1. Start the worker (auto-discovers every workflow in `src/workflows/`):
   ```bash
   make start-worker
   ```
2. In another terminal, trigger one:
   ```bash
   make crm-classify      # core — safe, no OAuth, run this first
   make crm-sync          # writes to Notion (first run prompts Notion OAuth)
   make crm-triage-inbox  # reads Gmail (first run prompts Gmail OAuth)
   make crm-digest        # Notion + Gmail; drafts reminders
   ```
   Or with custom input:
   ```bash
   make crm-classify input='{"text":"...","subject":"...","interaction_type":"Email"}'
   ```
   You can also trigger any of them from the Studio Console (Workflows tab).

**First connector run pauses for OAuth.** A workflow that touches a connector is
`on_behalf_of=True`; on first execution it emits an auth URL (visible in the
Studio UI / logs). Authorise once, and later runs are non-interactive.

## Two things to know

- **Scheduling + connectors don't mix.** The SDK forbids `on_behalf_of=True`
  together with `schedules=[...]` (a scheduled run has no user OAuth session).
  So `crm-followup-digest` is trigger-based; to run it daily, schedule the
  trigger externally (cron calling `make crm-digest`, or the executions API).
  A *non-connector* workflow (like the classifier) can use an in-SDK `Schedule`.
- **Mapping decisions** (in `classification_to_triage`): `category="unknown"` →
  Notion select left empty; `priority` is written on the **Contact**, not the
  Interaction; `action_items` are folded into the Interaction's *AI Analysis*;
  and you (USER_ALIASES) are filtered out of contacts.

## Shared code (`src/workflows/crm/`)

| Module | Role |
|---|---|
| `config.py` | Single source of truth — IDs, model names, connector slugs, vocabularies |
| `models.py` | Pydantic: `CRMClassification` (mirrors the agent) + Notion-shaped writes |
| `classify.py` | Triggers your Studio agent and parses its JSON output |
| `agent_tools.py` | Pure helpers + activities exposed to agents as callable tools |
| `notion.py` | Notion-writer durable agent + direct `notion-create-pages` helper |
| `connectors.py` | `connector("notion")` / `connector("gmail")` slot definitions |
| `prompts.py` | Notion-writer instruction context (no classifier prompt — your agent owns that) |
