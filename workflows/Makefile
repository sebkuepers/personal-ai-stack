.PHONY: start-worker execute installdeps start-examples execute-insurance-claims execute-cargo-release execute-code-modernization crm-classify crm-sync crm-triage-inbox crm-digest crm-ingest inbox-scan inbox-senders sync-agents sync-agents-dry eval

## Install dependencies
installdeps:
	uv sync

## Sync agent definitions (../agents/*.json) to Mistral Studio
sync-agents:
	uv run python ../agents/sync.py

## Validate agent definitions without touching Studio
sync-agents-dry:
	uv run python ../agents/sync.py --dry-run

## Auto-discover all workflows and start the worker (with file-watch auto-reload)
start-worker:
	uv run python -m entrypoints.dev

## Trigger a workflow execution
## Usage: make execute workflow=hello-world input='{"name": "World"}'
execute:
	uv run python -m entrypoints.start $(if $(workflow),--workflow $(workflow),) $(if $(input),--input '$(input)',)

## Start a worker that loads only the example workflows
start-examples:
	uv run python -m examples.worker

## Execute the insurance-claims-triage example workflow
## Usage: make execute-insurance-claims input='{"claim_id": "CLM-001", "claimant_name": "Jane", "description": "My car was hit.", "photos": ["src/examples/insurance_claims/sample_data/photos/claim_low_scratch_door.jpg"]}'
execute-insurance-claims:
	uv run python -m entrypoints.start --workflow insurance-claims-triage $(if $(input),--input '$(input)',--input '{"claim_id":"CLM-2024-001","claimant_name":"Maria Gonzalez","description":"My car was T-boned at an intersection.","photos":["src/examples/insurance_claims/sample_data/photos/claim_high_totaled_front.jpg","src/examples/insurance_claims/sample_data/photos/claim_high_totaled_side.jpg"]}')

## Execute the cargo-release-compliance example workflow
## Usage: make execute-cargo-release input='{"document_uri": "...", "shipment_id": "..."}'
execute-cargo-release:
	uv run python -m entrypoints.start --workflow cargo-release-compliance $(if $(input),--input '$(input)',--input '{"document_uri":"src/examples/cargo_release/sample_data/shipping_doc_normal.png","shipment_id":"BL-2024-HAM-009371"}')

## Execute the code-modernization example workflow
## Usage: make execute-code-modernization input='{"repo_path": "...", "target": "Python 2.7 → 3.12"}'
execute-code-modernization:
	uv run python -m entrypoints.start --workflow code-modernization $(if $(input),--input '$(input)',--input '{"repo_path":"src/examples/code_modernization/sample_data/legacy_repo","target":"Python 2.7 → 3.12"}')

# ===========================================================================
# Personal CRM workflows  (start the worker with `make start-worker` first)
# ===========================================================================

## CORE — classify one interaction, dry run (no connectors, safest first run)
## Usage: make crm-classify input='{"text":"...","subject":"...","interaction_type":"Email"}'
crm-classify:
	uv run python -m entrypoints.start --workflow crm-interaction-classifier $(if $(input),--input '$(input)',--input '{"text":"Hi Seb, loved your talk — we are hiring a Head of AI at Ongiini, can we chat Thursday? — Marie Dubois","subject":"AI meetup follow-up","interaction_type":"Email"}')

## WRITE — classify + write into Notion CRM (Notion connector; first run = OAuth)
## Usage: make crm-sync input='{"text":"...","subject":"..."}'
crm-sync:
	uv run python -m entrypoints.start --workflow crm-notion-sync $(if $(input),--input '$(input)',--input '{"text":"Hi Seb, loved your talk — we are hiring a Head of AI at Ongiini, can we chat Thursday? — Marie Dubois","subject":"AI meetup follow-up","interaction_type":"Email"}')

## INBOX — pull recent Gmail and classify each, dry run (Gmail connector; OAuth)
## Usage: make crm-triage-inbox input='{"query":"newer_than:3d","max_emails":5}'
crm-triage-inbox:
	uv run python -m entrypoints.start --workflow crm-email-triage $(if $(input),--input '$(input)',--input '{"query":"newer_than:7d -category:promotions -category:social","max_emails":10}')

## ASSISTANT — find due follow-ups in Notion and draft reminders (Notion+Gmail; OAuth)
## Usage: make crm-digest input='{"draft_reminders":true,"horizon_days":0}'
crm-digest:
	uv run python -m entrypoints.start --workflow crm-followup-digest $(if $(input),--input '$(input)',--input '{"draft_reminders":true,"horizon_days":0}')

## BATCH — ingest recent Gmail (inbox+sent) → classify → write to Notion (Gmail+Notion; OAuth)
## The twice-daily workhorse (triggered by the Cloudflare cron). Dry run by default.
## Usage: make crm-ingest input='{"window_hours":13,"max_emails":50,"dry_run":false}'
crm-ingest:
	uv run python -m entrypoints.start --workflow crm-ingest-recent $(if $(input),--input '$(input)',--input '{"window_hours":13,"max_emails":50,"dry_run":true}')

# ===========================================================================
# Inbox / triage  (domain "inbox" — the daily round over the mailbox)
# ===========================================================================

# ============================================================================
# FINANCE — private finances, LOCAL ONLY (no Cloudflare, no schedule)
# ============================================================================
.PHONY: finance-tidy finance-tidy-undo finance-overview finance-ingest

finance-tidy:  ## Collect everything private-financial into one place — preview; apply=1 for real
	uv run python -m financecli.tidy $(if $(apply),--apply)

finance-tidy-undo:  ## Take the last tidy run back
	uv run python -m financecli.tidy --undo

finance-overview:  ## Plan, subscriptions, goals and depot — show; upload=1 puts it in the library
	uv run python -m financecli.overview $(if $(upload),--upload)

finance-ingest:  ## Statements → ledger — preview; apply=1 writes it
	uv run python -m financecli.ingest $(if $(apply),--apply)

.PHONY: inbox-scan inbox-daily inbox-senders inbox-review inbox-eval inbox-eval-cascade

## SCAN — triage inbox + sent: newsletters, finance, replies owed (dry run, Gmail; OAuth)
## Phase 1: changes nothing — no label, no draft. The report appears in the Studio timeline.
## Usage: make inbox-scan input='{"window_days":1,"max_threads":50}'
inbox-scan:
	uv run python -m entrypoints.start --workflow inbox-scan $(if $(input),--input '$(input)',--input '{"window_days":1,"max_threads":50}')

## SENDERS — count mails and unread per sender in the window (pure arithmetic, no model)
## Default scope: everything received that reaches you (spam/trash excluded, as Gmail search keeps it).
## Usage: make inbox-senders window=90
inbox-senders:  ## Sender statistic over the window (window=90, query= overrides the scope)
	uv run python -m entrypoints.start --workflow inbox-senders $(if $(input),--input '$(input)',--input '{"window_days":$(or $(window),90)}')

## CONSULTATION — the triage run as a conversation (config in the chat, canvas, library dossier)
inbox-daily:  ## The nightly round by hand — yesterday, complete, dossier into the library
	uv run python -m entrypoints.start --workflow inbox-daily --input '{}'

inbox-review:  ## Conversational run as in Le Chat, but in the terminal
	uv run python -m mistralai.workflows.scripts.dev_interactive_workflow_cli inbox-review \
		--base-url $${SERVER_URL:-https://api.mistral.ai} --deployment $${DEPLOYMENT_NAME:-default} --input '{}'

## EVAL — measure the triage agent (real instructions from ../agents/inbox-review.json)
inbox-eval:  ## Triage agent against the constructed cases (runs=2, only=<config> as usual)
	uv run python -m evalkit --agent inbox-review --cases shared/inbox/eval-review.json $(if $(runs),--runs $(runs),) $(if $(only),--only $(only),)

## EVAL CASCADE — measure first stage → escalation → second stage end to end
inbox-eval-cascade:  ## The cascade against the same cases; compared to small-alone and medium-alone
	uv run python -m workflows.inbox.cascade_eval --cases shared/inbox/eval-review.json $(if $(runs),--runs $(runs),)

# ===========================================================================
# Book / editing  (domain "book" — the work comes in as work=<slug>)
# ===========================================================================

.PHONY: book-sync book-export book-test book-pdf book-instructions book-apply \
        book-decisions book-content book-overview book-editing-chat \
        book-voiceprofile book-voiceprofile-trial book-copyedit book-style \
        book-eval book-eval-cases

## EXPORT — read Scrivener and rebuild the canonical export
## The export is ALWAYS regenerated, never maintained by hand.
## Usage: make book-sync work=immer-wieder-ruegen
book-sync:
	uv run python -m bookcli.sync --work $(or $(work),immer-wieder-ruegen) --markdown

## EXPORT + library — additionally upload into the Mistral Library
book-export:
	uv run python -m bookcli.sync --work $(or $(work),immer-wieder-ruegen) --markdown --library

## TESTS — Scrivener roundtrip against the real project and against textutil
book-test:
	uv run pytest tests/ -q

book-pdf:  ## Typeset the manuscript (chapters=1-3, breaks=all|groups|none, compare=1)
	uv run python -m bookcli.pdf --work $${work:-immer-wieder-ruegen} \
		$(if $(chapters),--chapters $(chapters)) $(if $(breaks),--breaks $(breaks)) \
		$(if $(compare),--compare)

book-instructions:  ## Generate the Vibe project instructions and copy them to the clipboard
	uv run python -m bookcli.instructions --work $${work:-immer-wieder-ruegen} --copy

book-apply:  ## Write decisions into the manuscript — preview; apply=1 for real  (test=1 uses the test copy)
	uv run python -m bookcli.apply --work $${work:-immer-wieder-ruegen} \
		$(if $(uuid),--uuid $(uuid)) $(if $(test),--test) $(if $(apply),--apply)

book-decisions:  ## Count the decision log  (level=style|copyedit, eval=<file> generates test cases)
	uv run python -m bookcli.decisions --work $${work:-immer-wieder-ruegen} \
		--level $${level:-style} $(if $(eval),--eval $(eval)) --last 15

book-content:  ## Level 3 — one chapter against its rubric  (chapter="Voll zur Oma")
	uv run python -m bookcli.content --work $${work:-immer-wieder-ruegen} --chapter "$(chapter)"

book-overview:  ## Structure, density and state of a book (canvas + charts)
	uv run python -m mistralai.workflows.scripts.dev_interactive_workflow_cli book-overview \
		--base-url $${SERVER_URL:-https://api.mistral.ai} --deployment $${DEPLOYMENT_NAME:-default} --input '{}'

book-editing-chat:  ## Editing as a conversation — the same surface as Le Chat, in the terminal
	uv run python -m mistralai.workflows.scripts.dev_interactive_workflow_cli book-editing \
		--base-url $${SERVER_URL:-https://api.mistral.ai} --deployment $${DEPLOYMENT_NAME:-default} --input '{}'

## VOICE PROFILE — distil a work's narrative voice (the worker has to run)
## Usage: make book-voiceprofile work=immer-wieder-ruegen
book-voiceprofile:
	uv run python -m bookcli.voiceprofile --work $(or $(work),immer-wieder-ruegen) --write

## VOICE PROFILE (trial run) — only 6 sections, writes nothing
book-voiceprofile-trial:
	uv run python -m bookcli.voiceprofile --work $(or $(work),immer-wieder-ruegen) --limit 6

## COPYEDIT — level 1 on one section (the worker has to run)
## Usage: make book-copyedit section="Einführung Strand"
book-copyedit:
	uv run python -m bookcli.editing --work $(or $(work),immer-wieder-ruegen) --level copyedit $(if $(section),--section "$(section)",) $(if $(uuid),--uuid $(uuid),)

## STYLE — level 2 on one section, against the voice profile
## Usage: make book-style section="Einführung Strand"
book-style:
	uv run python -m bookcli.editing --work $(or $(work),immer-wieder-ruegen) --level style $(if $(section),--section "$(section)",) $(if $(uuid),--uuid $(uuid),)

## EVAL — generate test cases from the manuscript (annotate them by hand afterwards)
book-eval-cases:
	uv run python -m bookcli.eval --work $(or $(work),immer-wieder-ruegen) --generate

## EVAL — measure model configurations against the test cases (uses evalkit)
## Usage: make book-eval runs=3 only=small/high
book-eval:
	uv run python -m evalkit --agent book-copyedit --cases shared/book/eval-$(or $(work),immer-wieder-ruegen).json $(if $(runs),--runs $(runs),) $(if $(only),--only $(only),)

## EVAL — beliebigen Agent messen (domänenunabhängig)
## Usage: make eval agent=crm-classification cases=shared/crm/eval-cases.json
eval:
	uv run python -m evalkit --agent $(agent) --cases $(cases) $(if $(runs),--runs $(runs),) $(if $(only),--only $(only),) $(if $(count_path),--count-path "$(count_path)",)

## STUDIO — clean up what the repo no longer defines (preview; apply=1 for real)
## Archives orphaned workflows, deletes orphaned agents. keep="<name>" spares one.
.PHONY: archive-stale
archive-stale:
	uv run python -m entrypoints.archive $(if $(apply),--apply) $(if $(keep),--keep "$(keep)")
