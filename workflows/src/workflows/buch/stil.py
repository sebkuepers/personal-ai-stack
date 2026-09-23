"""Ebene 2 des Lektorats — Stil für EINEN Abschnitt.

Der Auftrag ist nicht, den Text besser zu machen, sondern **dem Autor
ähnlicher**. Glätten und Vereinheitlichen ist genau das, was hier schadet.
Deshalb arbeitet dieser Workflow gegen das Stimmprofil und verwirft alles, was
sich auf keine seiner Regeln berufen kann.

Zwei Filter hintereinander, beide in deterministischem Code:

1. **Regelbezug** — ein Vorschlag ohne gültige ``regel_id`` fliegt raus, außer
   bei Schwere „hoch". Ohne diesen Filter zitiert der Agent das Profil bestenfalls
   dekorativ.
**Kein maschinelles Gegenlesen auf dieser Ebene.** Ebene 1 hat eines, weil ein
übersehenes Komma sonst niemandem auffällt. Ein Stilvorschlag dagegen wird
ohnehin nie ohne Zustimmung des Autors angewendet — das zweite Augenpaar ist
hier er selbst, und seine Entscheidung ist das wertvollere Signal, weil sie ins
Entscheidungslog geht und das Stimmprofil nachschärft. Ein maschinelles
Gegenlesen käme erst infrage, wenn eine Messung zeigt, dass es die Vorschläge
verbessert, die er zu sehen bekommt.

Auslösen:
  make buch-stil werk=immer-wieder-ruegen uuid=<abschnitt-uuid>
"""

from __future__ import annotations

import re

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    from workflows.buch.agenten import stil_pruefen

from workflows.buch.pruefungen import (  # noqa: E402
    filtere_ohne_regelbezug,
    korrigiere_absatz_index,
    teile_auf,
)
from workflows.buch.models import (  # noqa: E402
    BefundMitUrteil,
    LektoratErgebnis,
    LektoratInput,
    Stilvorschlaege,
)

# Regel-IDs im gerenderten Profil stehen als "[R-...]" am Zeilenanfang.
_REGEL_ID = re.compile(r"^\[(R-[a-zA-Z0-9-]+)\]", re.M)


@workflows.workflow.define(
    name="buch-stil",
    workflow_display_name="Buch · Stil (Ebene 2)",
    workflow_description=(
        "Prüft einen Abschnitt gegen das Stimmprofil des Autors. Jeder Vorschlag muss eine "
        "Regel des Profils zitieren; Vorschläge ohne Regelbezug werden verworfen."
    ),
)
class BuchStilWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: LektoratInput) -> LektoratErgebnis:
        absaetze = inp.absaetze or [inp.abschnitt.text]
        hinweise: list[str] = []

        if not inp.stimmprofil_text:
            return LektoratErgebnis(
                werk=inp.werk,
                abschnitt_uuid=inp.abschnitt.uuid,
                abschnitt_titel=inp.abschnitt.titel,
                ebene="stil",
                hinweise=[
                    "Kein Stimmprofil übergeben. Ohne Profil wäre das hier generische "
                    "Stilkritik — erst `make buch-stimmprofil` laufen lassen."
                ],
            )

        roh = await stil_pruefen(
            titel=inp.abschnitt.titel,
            absaetze=absaetze,
            stimmprofil_text=inp.stimmprofil_text,
            max_befunde=inp.max_befunde,
        )
        vorschlaege = Stilvorschlaege.model_validate(roh).vorschlaege

        befunde = [
            BefundMitUrteil(
                ebene="stil",
                absatz_index=v.absatz_index,
                search=v.search,
                replace=v.replace,
                art=v.problem,
                schwere=v.schwere,
                warum=v.warum,
                regel_id=v.regel_id,
            )
            for v in vorschlaege
        ]

        # Filter 0 — Anker prüfen: Der Agent zählt Absätze nicht zuverlässig.
        befunde, idx_hinweise = korrigiere_absatz_index(befunde, absaetze)
        hinweise += idx_hinweise

        # Filter 1 — Regelbezug gegen die IDs, die im Profil tatsächlich stehen.
        bekannte = set(_REGEL_ID.findall(inp.stimmprofil_text))
        befunde, filter_hinweise = filtere_ohne_regelbezug(befunde, bekannte)
        hinweise += filter_hinweise

        # Nach Schwere ordnen, dann kappen.
        rang = {"hoch": 0, "mittel": 1, "niedrig": 2}
        befunde.sort(key=lambda b: rang.get(b.schwere or "niedrig", 3))
        befunde = befunde[: inp.max_befunde]

        angezeigt, gesperrt = teile_auf(befunde)
        return LektoratErgebnis(
            werk=inp.werk,
            abschnitt_uuid=inp.abschnitt.uuid,
            abschnitt_titel=inp.abschnitt.titel,
            ebene="stil",
            befunde=angezeigt,
            gesperrt=gesperrt,
            hinweise=hinweise,
        )
