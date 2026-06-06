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

## Skills

| Skill | Teaches Vibe Work to… |
|---|---|
| `personal-crm` | understand the CRM (Notion structure, the classification agent, and which workflow to use for classify / log / triage / ingest / follow-up) |
| `crm-categories` | fetch the current category vocabulary via the `get_used_categories` MCP tool before classifying, so it reuses categories instead of inventing duplicates |
