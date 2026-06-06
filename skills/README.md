# skills — Agent Skills for Vibe Work

Personal [Agent Skills](https://docs.mistral.ai/vibe/work/skills) (the open `SKILL.md` standard Mistral
Vibe adopted from Anthropic) that teach **Vibe Work** *when* and *how* to use my MCP tools and
workflows. Version-controlled here alongside the things they describe.

> 🚧 Built in Phase 5.

## Shape

Each skill is a folder with a `SKILL.md` (YAML frontmatter + Markdown) and any supporting files:

```
skills/
└── log-interaction/
    └── SKILL.md     # frontmatter: name + a "when to use" description; body: how to do it
```

Skills are **declarative** — they point at MCP tools and workflows; they don't contain logic. The
description determines activation, so write it as *when to use* ("Use when I want to log an email or
interaction to my CRM…"), not just what it does.

## Planned skills

| Skill | Teaches Vibe Work to… |
|---|---|
| `log-interaction` | classify an interaction and file it to the Notion CRM (MCP + `crm-notion-sync`) |
| `triage-inbox` | pull recent mail and classify it (`crm-email-triage`) |
| `get-categories` | fetch the current CRM category vocabulary (MCP `get_used_categories`) |
