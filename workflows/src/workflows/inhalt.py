"""Ebene 3 des Lektorats — ein ganzes Kapitel gegen die Rubrik des Autors.

Die beiden anderen Ebenen arbeiten am Satz. Diese arbeitet am Bogen: Trägt das
Kapitel, was es tragen soll? Hält es die beiden Prüfsteine? Steht etwas darin,
das laut Plan gar nicht hineingehört?

**Sie ändert nichts.** Kein ``search``, kein ``replace``, nirgends im Schema. Die
Antwort auf ein inhaltliches Problem ist Schreiben, nicht Ersetzen — und
schreiben tut der Autor. Diese Ebene zeigt ihm, wo das Kapitel seine eigene
Rubrik nicht einlöst, und stellt höchstens fünf Fragen.

Drei Maßstäbe, absteigend verbindlich:

1. **Die Kapitelrubrik** aus ``shared/buch/<slug>.json`` — ``beweist``,
   ``muss_tragen``, ``muss_nicht_tragen``, Register, Zeit, Historie-Budget.
2. **Die Prüfsteine des Werks** — die zwei Fragen, an denen schon ein Kapitel
   („Kreuzen") und ein Ort (Prora) gescheitert sind.
3. **Das Exposé** aus ``kontext/expose.md`` — was das Buch werden soll. Steht
   zuletzt und wird ausdrücklich als Absicht gekennzeichnet: Es beschreibt das
   Buch, wie es Verlagen angeboten wird, nicht wie das Manuskript ist. Wer beides
   verwechselt, hält jede Abweichung für einen Fehler.

Auslösen:
  make buch-inhalt werk=immer-wieder-ruegen kapitel="Voll zur Oma"
"""

from __future__ import annotations

from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows import workflow
from pydantic import BaseModel, Field

with workflow.unsafe.imports_passed_through():
    from workflows.buch.agenten import pruefe_inhalt
    from workflows.buch.lokal import lade_kontext, lies_kapitel

from workflows.buch.models import InhaltBefund  # noqa: E402


class InhaltInput(BaseModel):
    """Eingabe von ``buch-inhalt`` — ein Kapitel eines Werks."""

    werk: str = "immer-wieder-ruegen"
    kapitel: str
    mit_expose: bool = Field(
        default=True, description="Das Exposé als dritten Maßstab mitgeben"
    )


class InhaltErgebnis(BaseModel):
    """Ausgabe von ``buch-inhalt``."""

    werk: str
    kapitel: str
    woerter: int
    abschnitte: int
    befund: InhaltBefund
    hinweise: list[str] = Field(default_factory=list)


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def lies_rubrik(werk: str, kapitel: str) -> tuple[dict, dict]:
    """Rubrik des Kapitels und Prüfsteine des Werks aus ``shared/buch/<slug>.json``."""
    from workflows.buch import config

    w = config.lade_werk(werk)
    rubrik = config.kapitel_nach_titel(werk, kapitel) or {}
    return rubrik, w.get("pruefsteine") or {}


@workflows.workflow.define(
    name="buch-inhalt",
    workflow_display_name="Buch · Inhalt (Ebene 3)",
    workflow_description=(
        "Prüft ein ganzes Kapitel gegen die Rubrik des Autors: Prüfsteine, was es tragen muss, "
        "was nicht hineingehört. Ändert nichts — stellt Fragen und benennt, was fehlt."
    ),
    execution_timeout=timedelta(minutes=30),
)
class BuchInhaltWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: InhaltInput) -> InhaltErgebnis:
        kapitel = await lies_kapitel(inp.werk, inp.kapitel)
        hinweise: list[str] = []

        expose = await lade_kontext(inp.werk, "expose") if inp.mit_expose else ""
        if inp.mit_expose and not expose:
            hinweise.append(
                "Kein Exposé in kontext/expose.md — geprüft wird nur gegen Rubrik und Prüfsteine."
            )

        # Rubrik und Prüfsteine kommen über eine Aktivität, weil sie aus
        # `shared/` gelesen werden — das ist I/O und gehört nicht in den
        # Workflow-Körper, der bei einer Wiederholung erneut abgespielt wird.
        rubrik, pruefsteine = await lies_rubrik(inp.werk, inp.kapitel)
        if not rubrik:
            hinweise.append(
                f"Für {inp.kapitel!r} steht keine Rubrik in shared/buch/{inp.werk}.json — "
                "geprüft wird nur gegen die Prüfsteine des Werks."
            )

        roh = await pruefe_inhalt(
            kapitel=kapitel, rubrik=rubrik, pruefsteine=pruefsteine, expose=expose
        )
        return InhaltErgebnis(
            werk=inp.werk,
            kapitel=inp.kapitel,
            woerter=kapitel["woerter"],
            abschnitte=len(kapitel["abschnitte"]),
            befund=InhaltBefund.model_validate(roh),
            hinweise=hinweise,
        )
