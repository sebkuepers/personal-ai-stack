"""Ebene 1 des Lektorats — Korrektorat für EINEN Abschnitt, mit QA-Schleife.

Rechtschreibung, Zeichensetzung, Grammatik, Tempus, Typografie. Stil wird nicht
angefasst; dafür gibt es ``buch-stil``.

**Die Schleife ist der Kern.** Ein Judge, der nur sperrt, wirft auch brauchbare
Befunde weg, bloß weil sie zu weit gefasst waren. Hier bekommt der Agent das
Urteil zurück und darf nachbessern:

    korrigiere_offen()      Befunde + conversation_id   (store=True)
      ↓
    Invarianten             Index, Nicht-Befunde — deterministisch, ohne Modell
      ↓
    bewerte()               je Kriterium ein Judge-Aufruf, parallel
      ↓
    alles über der Schwelle? ──ja──► fertig
      ↓ nein
    ueberarbeite()          append auf dieselbe Conversation: der Agent sieht
                            seinen eigenen Vorschlag UND das Urteil
      ↓
    … bis ``max_runden``, dann wird verworfen, was durchfällt

**Warum die Schleife hier steht und nicht im Agenten.** Mistral kennt
``handoffs`` — dabei entscheidet aber der *Agent*, ob und wann er abgibt. Das ist
richtig für Arbeitsteilung („das ist eigentlich ein Stilproblem, übernimm du"),
falsch für ein QA-Gate: Es gäbe keine Schleifenbegrenzung, keine feste Schwelle
und keinen Zugriff auf die Zwischenstände. Kontrollstruktur gehört in den
deterministischen Teil — genau dafür ist durable execution da. Jede Runde steht
danach in der Ereignishistorie.

Auslösen:
  make buch-korrektorat abschnitt="Einführung Strand"
"""

from __future__ import annotations

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    from workflows.buch import config
    from workflows.buch.agenten import bewerte, korrigiere_offen, ueberarbeite

from workflows.buch.judge import (  # noqa: E402
    aktive_kriterien,
    baue_rueckmeldung,
    kontext_pruefen,
    korrigiere_absatz_index,
    kriterium_text,
    teile_auf,
    werk_kontext,
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


def _zu_befunden(roh: dict, grenze: int) -> list[BefundMitUrteil]:
    # Nur das Nutzdatenfeld validieren: korrigiere_offen() legt die
    # conversation_id daneben, und Korrekturen verbietet Extrafelder.
    roh = {"korrekturen": roh.get("korrekturen", [])}
    return [
        BefundMitUrteil(
            ebene="korrektorat",
            absatz_index=k.absatz_index,
            search=k.search,
            replace=k.replace,
            art=k.art,
            warum=k.warum,
            konfidenz=k.konfidenz,
        )
        for k in Korrekturen.model_validate(roh).korrekturen[:grenze]
    ]


def _invarianten(
    befunde: list[BefundMitUrteil], absaetze: list[str]
) -> tuple[list[BefundMitUrteil], list[str]]:
    """Prüfungen ohne Ermessen — billig, absolut, vor jedem Modellaufruf.

    Bewusst getrennt von dem, was der Judge beurteilt: Ob ein Suchtext eindeutig
    auffindbar ist, ist eine Tatsache. Ob eine Korrektur inhaltlich berechtigt
    ist, ist ein Urteil und gehört in die Schleife.
    """
    hinweise: list[str] = []
    befunde, h = korrigiere_absatz_index(befunde, absaetze)
    hinweise += h
    befunde, h = verwerfe_nichtbefunde(befunde)
    hinweise += h
    befunde, h = verwerfe_eingriffe_in_rede(befunde, absaetze)
    hinweise += h
    befunde, h = verwerfe_gewollte_umgangssprache(befunde)
    hinweise += h
    return befunde, hinweise


@workflows.workflow.define(
    name="buch-korrektorat",
    workflow_display_name="Buch · Korrektorat (Ebene 1)",
    workflow_description=(
        "Prüft einen Abschnitt auf Rechtschreibung, Zeichensetzung, Grammatik, Tempus und "
        "Typografie. Abgelehnte Befunde gehen mit dem Urteil an den Agent zurück, der sie "
        "zurückziehen, enger fassen oder begründet verteidigen kann."
    ),
)
class BuchKorrektoratWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: LektoratInput) -> LektoratErgebnis:
        absaetze = inp.absaetze or [inp.abschnitt.text]
        hinweise: list[str] = []

        roh = await korrigiere_offen(titel=inp.abschnitt.titel, absaetze=absaetze)
        conversation_id = str(roh.get("conversation_id") or "")
        befunde = _zu_befunden(roh, inp.max_befunde)

        judge_moeglich = bool(inp.mit_judge and config.AGENTS.get("judge"))
        if inp.mit_judge and not judge_moeglich:
            hinweise.append("Ohne Bewertung: keine Judge-Agent-ID in shared/buch.json.")
        for fehlend in kontext_pruefen():
            # Ein Kriterium ohne sein Domänenwissen urteilt nicht gar nicht,
            # sondern still nach allgemeinen Maßstäben. Das muss sichtbar sein.
            hinweise.append(
                f"Kriterium {fehlend!r} braucht Werkkontext, bekommt aber keinen — "
                f"das Urteil ist unzuverlässig."
            )

        runde = 0
        while True:
            runde += 1
            befunde, h = _invarianten(befunde, absaetze)
            hinweise += h

            if not befunde or not judge_moeglich:
                break

            auftraege = [
                {
                    "index": i,
                    "kriterium": kriterium,
                    "frage": kriterium_text(kriterium),
                    "original": b.search,
                    "vorschlag": b.replace,
                    "warum": b.warum,
                    "kontext": werk_kontext(kriterium),
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

            abgelehnt = [b for b in befunde if b.gesperrt]
            if not abgelehnt:
                break
            if runde >= inp.max_runden or not conversation_id:
                hinweise.append(
                    f"{len(abgelehnt)} Befund(e) nach {runde} Runde(n) weiterhin abgelehnt "
                    "— verworfen."
                )
                break

            # Zurück an den Agent: er sieht seinen Vorschlag und das Urteil.
            hinweise.append(f"Runde {runde}: {len(abgelehnt)} Befund(e) zur Überarbeitung.")
            roh = await ueberarbeite(
                conversation_id=conversation_id,
                rueckmeldung=baue_rueckmeldung(abgelehnt, runde),
                ebene="korrektorat",
            )
            befunde = _zu_befunden(roh, inp.max_befunde)

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
