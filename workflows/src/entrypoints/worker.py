"""Auto-discover all workflow classes in the `workflows` package and start a worker."""
# ruff: noqa: E402

import asyncio
import importlib
from dotenv import load_dotenv

import inspect
import pkgutil
import sys

load_dotenv(override=True)

import mistralai.workflows as mistralai_workflows
from mistralai.workflows.core.definition.workflow_definition import (
    get_workflow_definition,
)


def discover_workflows() -> list[type]:
    """Recursively scan the `workflows` package for all workflow classes.

    Uses ``walk_packages`` so workflows can be grouped in subpackages/folders
    (e.g. ``workflows/crm/``) instead of all sitting at the top level. Modules
    without a workflow class (shared helpers like ``crm/config.py``) are simply
    skipped. Results are de-duplicated by identity, so a class that is also
    imported into another module is counted once.
    """
    discovered: list[type] = []
    seen: set[int] = set()
    package = importlib.import_module("workflows")

    for _, modname, _ in pkgutil.walk_packages(package.__path__, prefix="workflows."):
        module = importlib.import_module(modname)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if hasattr(obj, "__workflows_workflow_def") and id(obj) not in seen:
                seen.add(id(obj))
                discovered.append(obj)

    return discovered


async def main() -> None:
    discovered = discover_workflows()

    if not discovered:
        print("No workflows discovered in the `workflows` package.")
        sys.exit(1)

    names = [get_workflow_definition(wf).name for wf in discovered]
    print(f"Discovered {len(discovered)} workflow(s): {', '.join(names)}")

    await mistralai_workflows.run_worker(discovered)


if __name__ == "__main__":
    asyncio.run(main())
