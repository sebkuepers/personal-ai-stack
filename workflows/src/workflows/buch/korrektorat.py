"""Ebene 1 des Lektorats — Korrektorat für EINEN Abschnitt.

Rechtschreibung, Zeichensetzung, Grammatik, Tempus, Typografie. Stil wird
ausdrücklich nicht angefasst; dafür gibt es ``buch-stil``.

Headless und einzeln aufrufbar, damit man auch „das ganze Kapitel über Nacht"
laufen lassen kann, ohne durch einen Dialog zu müssen. Die konversationelle
Hülle (``buch-lektorat``) ruft denselben Workflow als Kind auf.

Jeder Befund läuft vor der Anzeige durch den Treue-Judge: Er ist der einzige,
der sperren darf, weil das Korrektorat der Schritt ist, der später automatisch
ins Manuskript schreibt.

Auslösen:
  make buch-korrektorat werk=immer-wieder-ruegen uuid=<abschnitt-uuid>
"""

from __future__ import annotations

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    from workflows.buch import config
    from workflows.buch.agenten import bewerte, korrigiere

from workflows.buch.judge import (  # noqa: E402
    aktive_kriterien,
    korrigiere_absatz_index,
    kriterium_text,
    teile_auf,
    verwerfe_eingriffe_in_rede,
    verwerfe_gewollte_umgangssprache,
    verwerfe_nichtbefunde,
    wende_urteil_an,
)
from workflows.buch.models import (  # noqa: E402
    BefundMitUrteil,
    Korrekturen,
    LektoratErgebnis,
    LektoratInput,
)


@workflows.workflow.define(
    name="buch-korrektorat",
    workflow_display_name="Buch · Korrektorat (Ebene 1)",
    workflow_description=(
        "Prüft einen Abschnitt auf Rechtschreibung, Zeichensetzung, Grammatik, Tempus und "
        "Typografie. Jeder Befund wird auf Bedeutungstreue geprüft, bevor er angezeigt wird."
    ),
)
class BuchKorrektoratWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: LektoratInput) -> LektoratErgebnis:
        absaetze = inp.absaetze or [inp.abschnitt.text]

        roh = await korrigiere(titel=inp.abschnitt.titel, absaetze=absaetze)
        korrekturen = Korrekturen.model_validate(roh).korrekturen[: inp.max_befunde]

        befunde = [
            BefundMitUrteil(
                ebene="korrektorat",
                absatz_index=k.absatz_index,
                search=k.search,
                replace=k.replace,
                art=k.art,
                warum=k.warum,
                konfidenz=k.konfidenz,
            )
            for k in korrekturen
        ]

        # Zwei deterministische Filter VOR der Bewertung — sie kosten keinen
        # Agent-Aufruf und fangen ab, was der Agent trotz Instruktion liefert.
        befunde, hinweise = korrigiere_absatz_index(befunde, absaetze)
        befunde, h0 = verwerfe_nichtbefunde(befunde)
        hinweise += h0
        befunde, h2 = verwerfe_eingriffe_in_rede(befunde, absaetze)
        befunde, h3 = verwerfe_gewollte_umgangssprache(befunde)
        hinweise += h2 + h3

        if inp.mit_judge and befunde and config.AGENTS.get("judge"):
            # Alle Bewertungen parallel — jede ist ein eigener, kurzer Agent-Aufruf.
            auftraege = [
                {
                    "index": i,
                    "kriterium": kriterium,
                    "frage": kriterium_text(kriterium),
                    "original": b.search,
                    "vorschlag": b.replace,
                    "warum": b.warum,
                }
                for kriterium in aktive_kriterien()
                for i, b in enumerate(befunde)
            ]
            urteile = await workflows.execute_activities_in_parallel(
                bewerte, items=auftraege, max_concurrent_scheduled_tasks=6
            )
            for u in urteile or []:
                if u and u.get("index") is not None:
                    wende_urteil_an(befunde[u["index"]], u["kriterium"], u["score"])
        elif inp.mit_judge:
            hinweise.append("Ohne Treue-Prüfung: keine Judge-Agent-ID in shared/buch.json.")

        angezeigt, gesperrt = teile_auf(befunde)
        return LektoratErgebnis(
            werk=inp.werk,
            abschnitt_uuid=inp.abschnitt.uuid,
            abschnitt_titel=inp.abschnitt.titel,
            ebene="korrektorat",
            befunde=angezeigt,
            gesperrt=gesperrt,
            hinweise=hinweise,
        )
