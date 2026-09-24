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


def _defining_modules() -> list[Path]:
    """Only the modules that DEFINE a workflow — those are sandbox-validated.

    A helper module is imported through the workflow module and inherits its
    passthrough; it is the defining module whose import list decides whether
    the worker starts.
    """
    return [p for p in _workflow_modules() if "workflow.define" in p.read_text(encoding="utf-8")]


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


@pytest.mark.parametrize("path", _workflow_modules(), ids=lambda p: p.stem)
def test_todolistitem_has_a_description(path: Path):
    """``TodoListItem(title=…)`` without ``description`` raises at construction.

    The SDK takes both positionally and required. Missing it kills the workflow
    before the first form, and all Le Chat shows is "Workflow failed" — the
    error never reaches the person who could act on it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "TodoListItem"
        ):
            supplied = {kw.arg for kw in node.keywords} | {f"#{i}" for i in range(len(node.args))}
            assert "description" in supplied or "#1" in supplied, (
                f"{path.name}:{node.lineno}: TodoListItem without a description — "
                "the SDK requires it and the workflow dies at construction."
            )


@pytest.mark.parametrize("path", _workflow_modules(), ids=lambda p: p.stem)
def test_child_workflow_params_are_a_model(path: Path):
    """``execute_workflow(params=…)`` takes a Pydantic model, never a dict.

    The SDK serialises it with ``.model_dump_json()``; a dict dies with
    "'dict' object has no attribute 'model_dump_json'" — at runtime, inside the
    conversation, after the user already made a choice.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "execute_workflow"):
            continue
        for kw in node.keywords:
            if kw.arg == "params":
                assert not isinstance(kw.value, ast.Dict), (
                    f"{path.name}:{node.lineno}: execute_workflow(params=…) got a dict — "
                    "the SDK calls .model_dump_json() on it."
                )


@pytest.mark.parametrize("path", _workflow_modules(), ids=lambda p: p.stem)
def test_a_scheduled_workflow_does_not_act_on_behalf_of_a_user(path: Path):
    """``schedules=[…]`` and ``on_behalf_of=True`` cannot both be true.

    A scheduled execution carries no user identity, so the connector has
    nothing to act as — measured live, the run dies with
    ``400 Execution is missing user_id or organization_id``. The SDK refuses
    the combination at class definition, but only when the decorator is
    evaluated, i.e. at worker start; this catches it in the test suite, and it
    catches the reverse mistake too — adding a schedule to a workflow that is
    still declared on_behalf_of. See workflows/CLAUDE.md gotcha 19.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for deco in node.decorator_list:
            if not isinstance(deco, ast.Call):
                continue
            kwargs = {kw.arg: kw.value for kw in deco.keywords if kw.arg}
            if "schedules" not in kwargs:
                continue
            obo = kwargs.get("on_behalf_of")
            is_true = isinstance(obo, ast.Constant) and obo.value is True
            assert not is_true, (
                f"{path.name}: {node.name} has schedules AND on_behalf_of=True — "
                "a scheduled run has no user identity and the connector call fails."
            )


@pytest.mark.parametrize("path", _defining_modules(), ids=lambda p: p.stem)
def test_repo_imports_in_workflow_modules_are_passed_through(path: Path):
    """Every ``workflows.*`` import in a workflow module needs the sandbox bypass.

    Our own modules read files at import — a config module does
    ``Path(...).read_text()`` — and inside the Temporal sandbox that is a
    restricted call. The worker then does not start at all:
    ``Failed validating workflow crm-followup-digest``. It is not caught by the
    discovery check (that only imports), it depends on import order, and it can
    therefore pass on the laptop and kill the container — which is exactly what
    it did on 2026-09-24.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    passed = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With) and any(
            "imports_passed_through" in ast.dump(item.context_expr) for item in node.items
        ):
            for inner in ast.walk(node):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    passed.add(inner.lineno)
    for node in tree.body:  # module level only — inside a function it is fine
        if node.lineno in passed:
            continue
        name = None
        if isinstance(node, ast.ImportFrom) and node.module:
            name = node.module
        elif isinstance(node, ast.Import):
            name = next((a.name for a in node.names if a.name.startswith("workflows")), None)
        if name and name.startswith("workflows"):
            raise AssertionError(
                f"{path.name}:{node.lineno}: '{name}' is imported outside "
                "imports_passed_through() — the worker may refuse to start."
            )


@pytest.mark.parametrize("path", _defining_modules(), ids=lambda p: p.stem)
def test_a_config_module_is_imported_by_its_full_name(path: Path):
    """``from package import module`` does not survive the sandbox (gotcha 10).

    Passthrough applies to module NAMES. ``from workflows.inbox import config``
    is an attribute access on the package, so the sandbox still bites — even
    inside ``imports_passed_through()``. Only ``import workflows.inbox.config
    as config`` (or importing the names directly) works. This cost an hour on
    2026-09-24 because the fix looked applied and was not.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        if not node.module.startswith("workflows"):
            continue
        for alias in node.names:
            assert alias.name != "config", (
                f"{path.name}:{node.lineno}: 'from {node.module} import config' is an "
                "attribute access the sandbox still blocks — use "
                f"'import {node.module}.config as config'."
            )
