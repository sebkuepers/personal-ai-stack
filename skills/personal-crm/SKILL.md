---
name: personal-crm
description: Use when Sebastian wants to classify, log, triage, summarise, or follow up on an interaction (email, meeting, call, message) in his personal CRM, or asks about contacts/organizations/interactions. Explains the CRM's Notion structure and the workflows and MCP tools that operate it.
---

# Personal CRM

Sebastian runs a personal CRM in Notion, fed by a Mistral classification agent and
a set of durable workflows. This skill tells you how it's wired so you use the
right tool instead of improvising.

## The Notion CRM (three databases)

- **Organizations** — companies/foundations/networks. Key props: Name, Status
  (Active/Past/Potential/Rejected), Org Type, Industry.
- **Contacts** — people. Key props: Name, Email, Primary Role, Relationship
  Status, **Priority** (High/Medium/Low), Auto-Tags, AI Summary, Next Follow-up.
- **Interactions** — every touchpoint. Key props: Name, Contact (→Contacts),
  Organization (→Organizations), Category, Sub-Category, Interaction Type,
  Channel, Subject, Raw Content, AI Summary, AI Analysis, Sentiment, Date,
  Follow-up Date, Follow-up Needed.

## How classification works

A Studio agent ("CRM - Classification Agent") classifies each interaction into a
fixed schema (category, sub_category, interaction_type, sentiment, priority,
people_mentioned, organizations_mentioned, summary, analysis, action_items,
suggested_follow_up_date).

- **Before proposing a category, call the `get_used_categories` tool** (from the
  personal-crm MCP connector) to get the categories already in use, and reuse an
  existing one rather than inventing a near-duplicate. Only coin a new category
  when none fit.

## The workflows (prefer these over doing it by hand)

| Want to… | Use |
|---|---|
| Classify one interaction and see the intended writes (no changes) | `crm-interaction-classifier` (dry run) |
| Classify one interaction and file it into Notion | `crm-notion-sync` |
| Review recent inbox, classified, without writing | `crm-email-triage` |
| Batch-ingest recent Gmail (inbox+sent) into the CRM | `crm-ingest-recent` (runs twice daily) |
| Find due follow-ups and draft reminder emails | `crm-followup-digest` |

## Rules that matter

- **Don't add Sebastian himself as a contact** — he's filtered out of
  people_mentioned.
- **Priority lives on the Contact**, not the Interaction.
- **Category "unknown" → leave the Notion select empty** (it has no such option).
- **Gmail can only draft, never send.** Any "reminder/reply" is a draft Sebastian
  reviews.
- **Don't duplicate interactions** — the batch dedups by Gmail message id.

## Source of truth

IDs, the category vocabulary, and connector names live in `shared/crm.json`. If
you need a database id or the exact category list, that's the canonical place.
