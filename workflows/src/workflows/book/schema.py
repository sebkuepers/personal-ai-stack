"""Generate JSON schemas for Studio agents from the Pydantic models.

An agent enforces its answer shape through ``response_format.json_schema``; the
rest of the system works with the Pydantic model from ``models.py``. Both have
to say the same thing — maintained by hand they are guaranteed to drift apart.

So the schema is derived from the model here. Two adjustments are needed for
Mistral to accept it:

* **Resolve ``$defs``.** Pydantic hoists nested models into ``$defs`` and points
  at them with ``$ref``. We inline them.
* **``additionalProperties: false`` everywhere.** Matches ``extra="forbid"`` on
  the model and stops an agent from inventing extra fields.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def _resolve(node: Any, defs: dict[str, Any]) -> Any:
    """Recursively replace ``$ref`` pointers with the definition itself."""
    if isinstance(node, dict):
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            resolved = _resolve(deepcopy(defs[name]), defs)
            # Sibling fields next to $ref (e.g. description) win.
            for k, v in node.items():
                if k != "$ref":
                    resolved[k] = v
            return resolved
        return {k: _resolve(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_resolve(x, defs) for x in node]
    return node


def _strict(node: Any) -> Any:
    """Set ``additionalProperties: false`` on every object."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
        return {k: _strict(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_strict(x) for x in node]
    return node


def json_schema(model: type[BaseModel], *, title: str, description: str) -> dict[str, Any]:
    """Build the flat, strict schema for ``response_format.json_schema.schema``."""
    raw = model.model_json_schema()
    defs = raw.get("$defs", {})
    schema = _strict(_resolve(raw, defs))
    schema.pop("$defs", None)
    schema["title"] = title
    schema["description"] = description
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    return schema


def response_format(
    model: type[BaseModel], *, name: str, title: str, description: str
) -> dict[str, Any]:
    """The complete ``response_format`` object of an agent definition."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": json_schema(model, title=title, description=description),
            "description": description,
            # strict=True makes the API ENFORCE the schema instead of merely
            # suggesting it. Without it, book-style returned a `problem`
            # ("doppelt-gesagt") that is not in the vocabulary — the workflow
            # died in Pydantic validation, after three retries. The alternative
            # would have been a mapping table in code: a patch for one case
            # that tears open again at the next invented value.
            "strict": True,
        },
    }
