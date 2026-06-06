---
name: crm-categories
description: Use right before classifying or tagging anything for Sebastian's CRM, when you need to know which interaction categories and sub-categories already exist so you reuse them instead of inventing duplicates.
---

# CRM categories

When classifying or tagging an interaction for the personal CRM, **first fetch the
categories already in use** so you stay consistent.

## How

Call the **`get_used_categories`** tool (personal-crm MCP connector). It returns:

```json
{ "source": "notion" | "config", "categories": [...], "sub_categories": [...] }
```

- `source: "notion"` — read live from the Notion Interactions schema (most current).
- `source: "config"` — the canonical vocabulary fallback.

## Then

- **Reuse** an existing category/sub-category whenever one reasonably fits.
- Only **propose a new** category when none of the returned values fit — and say
  so explicitly, so Sebastian can decide whether to add it to the schema.
- Never silently coin a near-duplicate of an existing category (e.g. don't invent
  "job-application" when "job_application" exists).
