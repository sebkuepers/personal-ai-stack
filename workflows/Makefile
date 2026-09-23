.PHONY: start-worker execute installdeps start-examples execute-insurance-claims execute-cargo-release execute-code-modernization crm-classify crm-sync crm-triage-inbox crm-digest crm-ingest sync-agents sync-agents-dry buch-sync buch-export buch-test buch-stimmprofil buch-stimmprofil-probe buch-korrektorat buch-stil buch-eval buch-eval-faelle eval

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
# Buch / Lektorat  (Domäne "buch" — das Werk kommt als werk=<slug> herein)
# ===========================================================================

## EXPORT — Scrivener lesen und den kanonischen Export neu bauen
## Der Export wird IMMER neu erzeugt, nie von Hand gepflegt.
## Usage: make buch-sync werk=immer-wieder-ruegen
buch-sync:
	uv run python -m buchcli.sync --werk $(or $(werk),immer-wieder-ruegen) --markdown

## EXPORT + Library — zusätzlich in die Mistral Library laden
buch-export:
	uv run python -m buchcli.sync --werk $(or $(werk),immer-wieder-ruegen) --markdown --library

## TESTS — Scrivener-Roundtrip gegen das echte Projekt und gegen textutil
buch-test:
	uv run pytest tests/ -q

## STIMMPROFIL — die Erzählstimme eines Werks destillieren (Worker muss laufen)
## Usage: make buch-stimmprofil werk=immer-wieder-ruegen
.PHONY: buch-pdf
buch-pdf:  ## Manuskript setzen (kapitel=1-3, trenner=alle|gruppen|keine, vergleich=1)
	uv run python -m buchcli.pdf --werk $${werk:-immer-wieder-ruegen} \
		$(if $(kapitel),--kapitel $(kapitel)) $(if $(trenner),--trenner $(trenner)) \
		$(if $(vergleich),--vergleich)

.PHONY: buch-anweisungen
buch-anweisungen:  ## Anweisungen fürs Vibe-Projekt erzeugen und in die Zwischenablage legen
	uv run python -m buchcli.anweisungen --werk $${werk:-immer-wieder-ruegen} --kopieren

.PHONY: buch-entscheidungen
buch-entscheidungen:  ## Entscheidungslog auszählen  (ebene=stil|korrektorat, eval=<datei> erzeugt Testfälle)
	uv run python -m buchcli.entscheidungen --werk $${werk:-immer-wieder-ruegen} \
		--ebene $${ebene:-stil} $(if $(eval),--eval $(eval)) --letzte 15

.PHONY: buch-inhalt
buch-inhalt:  ## Ebene 3 — ein Kapitel gegen seine Rubrik  (kapitel="Voll zur Oma")
	uv run python -m buchcli.inhalt --werk $${werk:-immer-wieder-ruegen} --kapitel "$(kapitel)"

.PHONY: buch-uebersicht buch-lektorat-chat
buch-uebersicht:  ## Struktur, Dichte und Stand eines Buchs (Canvas + Diagramme)
	uv run python -m mistralai.workflows.scripts.dev_interactive_workflow_cli buch-uebersicht \
		--base-url $${SERVER_URL:-https://api.mistral.ai} --deployment $${DEPLOYMENT_NAME:-default} --input '{}'

buch-lektorat-chat:  ## Lektorat im Gespräch — dieselbe Oberfläche wie in Le Chat, nur im Terminal
	uv run python -m mistralai.workflows.scripts.dev_interactive_workflow_cli buch-lektorat \
		--base-url $${SERVER_URL:-https://api.mistral.ai} --deployment $${DEPLOYMENT_NAME:-default} --input '{}'

buch-stimmprofil:
	uv run python -m buchcli.stimmprofil --werk $(or $(werk),immer-wieder-ruegen) --schreiben

## STIMMPROFIL (Probelauf) — nur 6 Abschnitte, schreibt nichts
buch-stimmprofil-probe:
	uv run python -m buchcli.stimmprofil --werk $(or $(werk),immer-wieder-ruegen) --limit 6

## KORREKTORAT — Ebene 1 an einem Abschnitt (Worker muss laufen)
## Usage: make buch-korrektorat abschnitt="Einführung Strand"
buch-korrektorat:
	uv run python -m buchcli.lektorat --werk $(or $(werk),immer-wieder-ruegen) --ebene korrektorat $(if $(abschnitt),--abschnitt "$(abschnitt)",) $(if $(uuid),--uuid $(uuid),)

## STIL — Ebene 2 an einem Abschnitt, gegen das Stimmprofil
## Usage: make buch-stil abschnitt="Einführung Strand"
buch-stil:
	uv run python -m buchcli.lektorat --werk $(or $(werk),immer-wieder-ruegen) --ebene stil $(if $(abschnitt),--abschnitt "$(abschnitt)",) $(if $(uuid),--uuid $(uuid),)

## EVAL — Testfälle aus dem Manuskript erzeugen (Annotationen dann von Hand)
buch-eval-faelle:
	uv run python -m buchcli.eval --werk $(or $(werk),immer-wieder-ruegen) --erzeuge

## EVAL — Modellkonfigurationen gegen die Testfälle messen (nutzt evalkit)
## Usage: make buch-eval laeufe=3 nur=small/high
buch-eval:
	uv run python -m evalkit --agent buch-korrektorat --faelle shared/buch/eval-$(or $(werk),immer-wieder-ruegen).json $(if $(laeufe),--laeufe $(laeufe),) $(if $(nur),--nur $(nur),)

## EVAL — beliebigen Agent messen (domänenunabhängig)
## Usage: make eval agent=crm-classification faelle=shared/crm/eval-faelle.json
eval:
	uv run python -m evalkit --agent $(agent) --faelle $(faelle) $(if $(laeufe),--laeufe $(laeufe),) $(if $(nur),--nur $(nur),) $(if $(zaehlpfad),--zaehlpfad "$(zaehlpfad)",)
