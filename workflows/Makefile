.PHONY: start-worker execute installdeps start-examples execute-insurance-claims execute-cargo-release execute-code-modernization crm-classify crm-sync crm-triage-inbox crm-digest sync-agents sync-agents-dry

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
