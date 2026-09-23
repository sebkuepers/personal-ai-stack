"""JSON-Schemata für Studio-Agents aus den Pydantic-Modellen erzeugen.

Ein Agent erzwingt seine Antwortform über ``response_format.json_schema``; der
Rest des Systems arbeitet mit dem Pydantic-Modell aus ``models.py``. Beide
müssen dasselbe sagen — von Hand gepflegt driften sie garantiert auseinander.

Deshalb wird das Schema hier aus dem Modell abgeleitet. Zwei Anpassungen sind
nötig, damit Mistral es akzeptiert:

* **``$defs`` auflösen.** Pydantic lagert verschachtelte Modelle in ``$defs``
  aus und verweist mit ``$ref`` darauf. Wir setzen sie inline ein.
* **``additionalProperties: false`` überall.** Entspricht ``extra="forbid"`` im
  Modell und verhindert, dass ein Agent zusätzliche Felder erfindet.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from pydantic import BaseModel


def _aufloesen(knoten: Any, defs: dict[str, Any]) -> Any:
    """Ersetzt ``$ref``-Verweise rekursiv durch die Definition selbst."""
    if isinstance(knoten, dict):
        if "$ref" in knoten:
            name = knoten["$ref"].rsplit("/", 1)[-1]
            aufgeloest = _aufloesen(deepcopy(defs[name]), defs)
            # Geschwisterfelder neben $ref (z. B. description) gewinnen.
            for k, v in knoten.items():
                if k != "$ref":
                    aufgeloest[k] = v
            return aufgeloest
        return {k: _aufloesen(v, defs) for k, v in knoten.items() if k != "$defs"}
    if isinstance(knoten, list):
        return [_aufloesen(x, defs) for x in knoten]
    return knoten


def _streng(knoten: Any) -> Any:
    """Setzt ``additionalProperties: false`` auf jedem Objekt."""
    if isinstance(knoten, dict):
        if knoten.get("type") == "object" and "properties" in knoten:
            knoten["additionalProperties"] = False
        return {k: _streng(v) for k, v in knoten.items()}
    if isinstance(knoten, list):
        return [_streng(x) for x in knoten]
    return knoten


def json_schema(model: type[BaseModel], *, titel: str, beschreibung: str) -> dict[str, Any]:
    """Baut das flache, strenge Schema für ``response_format.json_schema.schema``."""
    roh = model.model_json_schema()
    defs = roh.get("$defs", {})
    schema = _streng(_aufloesen(roh, defs))
    schema.pop("$defs", None)
    schema["title"] = titel
    schema["description"] = beschreibung
    schema["$schema"] = "http://json-schema.org/draft-07/schema#"
    return schema


def response_format(
    model: type[BaseModel], *, name: str, titel: str, beschreibung: str
) -> dict[str, Any]:
    """Das vollständige ``response_format``-Objekt einer Agent-Definition."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": json_schema(model, titel=titel, beschreibung=beschreibung),
            "description": beschreibung,
            # strict=True lässt die API das Schema DURCHSETZEN statt es nur
            # vorzuschlagen. Ohne das lieferte buch-stil ein `problem`
            # ("doppelt-gesagt"), das nicht im Vokabular steht — der Workflow
            # brach in der Pydantic-Validierung ab, nach drei Wiederholungen.
            # Die Alternative wäre eine Abbildungstabelle im Code gewesen: ein
            # Flicken für einen Einzelfall, der beim nächsten erfundenen Wert
            # wieder aufgeht.
            "strict": True,
        },
    }
