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
            f"{path.name}: {cls.name} ruft self.wait_for_input(), erbt aber nicht von "
            "InteractiveWorkflow — der Aufruf schlägt zur Laufzeit fehl."
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
            assert name.isascii(), f"{path.name}: Feldname {name!r} ist nicht ASCII."
