"""Contracts every workflow in this repo has to keep, checked across all of them.

These are not tests of one feature. They are the invariants that no single
domain's test suite would catch, because each one looks only at its own code.

The first was written after ``InboxReviewWorkflow`` shipped without
``InteractiveWorkflow`` as its base while calling ``self.wait_for_input()``.
Nothing complained: ruff sees a valid attribute access on ``self``, the
discovery check only imports, and the unit tests never construct the workflow.
It would have died at the first form in Le Chat — which is exactly where
nobody is watching a stack trace.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "workflows"


def _workflow_modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if p.name != "__init__.py")


def _classes_calling(tree: ast.Module, method: str) -> list[ast.ClassDef]:
    """Classes whose body contains a ``self.<method>(...)`` call."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == method
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id == "self"
            ):
                found.append(node)
                break
    return found


def _base_names(cls: ast.ClassDef) -> set[str]:
    names = set()
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


@pytest.mark.parametrize("path", _workflow_modules(), ids=lambda p: p.stem)
def test_wait_for_input_requires_interactive_workflow(path: Path):
    """``self.wait_for_input`` only exists on ``InteractiveWorkflow`` subclasses.

    Without the base class the attribute is simply missing, and the failure
    surfaces at runtime in the chat — after the user already started the run.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for cls in _classes_calling(tree, "wait_for_input"):
        assert "InteractiveWorkflow" in _base_names(cls), (
            f"{path.name}: {cls.name} calls self.wait_for_input() but does not inherit "
            "InteractiveWorkflow — the call fails at runtime."
        )


@pytest.mark.parametrize("path", _workflow_modules(), ids=lambda p: p.stem)
def test_field_names_are_ascii(path: Path):
    """No umlauts in Pydantic field names.

    They work in Python but travel through JSON schemas, Temporal's converter
    and the Studio UI. ``übersprungen`` was one; an identifier is not the place
    to be German.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            assert name.isascii(), f"{path.name}: field name {name!r} is not ASCII."


# ---------------------------------------------------------------------------
# Agent schema ↔ Pydantic mirror
# ---------------------------------------------------------------------------

AGENTS = Path(__file__).resolve().parents[2] / "agents"

# Hand-written agent definitions and the Pydantic model that mirrors them.
# The book domain is absent on purpose: its schemas are GENERATED from the
# models (agents/build_book_agents.py), so they cannot drift. Only hand-written
# JSON can — and did: `Inbox · Review` returned `amount` while the mirror
# declared `betrag`, with extra="forbid". Every single triage call died in
# validation, and the only visible symptom was a workflow at 50 % health.
MIRRORS = [
    ("inbox-review", "workflows.inbox.models", "InboxReview"),
    ("inbox-second-review", "workflows.inbox.models", "InboxReview"),
]


@pytest.mark.parametrize(("agent", "module", "model"), MIRRORS, ids=[m[0] for m in MIRRORS])
def test_agent_schema_matches_its_mirror(agent: str, module: str, model: str):
    """The agent's response schema and its Pydantic mirror declare the same fields.

    With ``extra="forbid"`` on the mirror, one extra field in the answer is not
    a warning — it is a ValidationError on every call.
    """
    import importlib
    import json

    path = AGENTS / f"{agent}.json"
    if not path.is_file():
        pytest.skip(f"agent definition missing: {path.name}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    properties = set(
        schema["completion_args"]["response_format"]["json_schema"]["schema"]["properties"]
    )
    fields = set(getattr(importlib.import_module(module), model).model_fields)

    assert properties == fields, (
        f"{agent}.json and {model} disagree — "
        f"only in the schema: {sorted(properties - fields)}, "
        f"only in the model: {sorted(fields - properties)}"
    )
