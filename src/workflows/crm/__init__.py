"""Shared building blocks for Sebastian's personal-CRM workflows.

This subpackage is intentionally NOT a workflow module — the worker's
auto-discovery (``entrypoints/worker.py``) skips subpackages, so nothing
here is registered directly.  Top-level modules in ``workflows/`` import
from here.

Layout:
  config.py      — single source of truth: agent id, Notion data-source IDs,
                   model names, and the select-option vocabularies.
  models.py      — Pydantic models mirroring the Studio agent's output schema
                   and the Notion-shaped "intended writes".
  prompts.py     — system prompts (mirrors the Studio CRM Classification agent).
  classify.py    — the classification activity (typed, structured output).
  agent_tools.py — small activities exposed to durable agents as callable tools.
  notion.py      — Notion connector slot + writer helpers/agent builder.
"""
