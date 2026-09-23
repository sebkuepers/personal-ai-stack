"""Ebene 1 des Lektorats — Korrektorat für EINEN Abschnitt, nach dem Vier-Augen-Prinzip.

Rechtschreibung, Zeichensetzung, Grammatik, Tempus, Typografie. Stil wird nicht
angefasst; dafür gibt es ``buch-stil``.

    korrigiere()      Befunde der ersten Stufe
      ↓
    Invarianten       Index, Nicht-Befunde, Figurenrede — deterministisch, ohne Modell
      ↓
    gegenlese()       zweites Augenpaar auf DEMSELBEN Abschnitt: was fehlt, was keiner ist
      ↓
    fertig

**Warum das zweite Augenpaar den ganzen Abschnitt sieht.** Der Vorgänger war ein
Judge, der je Befund lief und nur ``search`` und ``replace`` bekam — einen
Schnipsel ohne den Satz, in dem er steht. Er konnte deshalb zwei Dinge nicht:
beurteilen, ob ein Fehler wirklich behoben wird, und bemerken, dass einer fehlt.
Das zweite war der schwerere Mangel: Bei null Befunden lief er gar nicht erst an,
also war ein übersehener Fehler unsichtbar. Ein Prüfer, der nur die Vorschläge
des Ersten sieht, prüft nicht dessen Arbeit, sondern nur dessen Wortwahl.

**Warum keine Rückkopplungsschleife.** Eine frühere Fassung gab abgelehnte
Befunde an den Agenten zurück. Gemessen hat das geschadet: Er nahm „enger fassen"
wörtlich und reduzierte Befunde bis zur Sinnlosigkeit, statt sie zurückzuziehen.
Was das zweite Augenpaar verwirft, wird jetzt verworfen; was es findet, kommt
hinzu. Beides ohne zweite Runde.

**Warum die Kontrollstruktur hier steht und nicht im Agenten.** Mistral kennt
``handoffs`` — dabei entscheidet aber der *Agent*, ob er abgibt. Das ist richtig
für Arbeitsteilung, falsch für ein QA-Gate: Es gäbe keine feste Reihenfolge und
keinen Zugriff auf die Zwischenstände. Jeder Schritt steht so in der
Ereignishistorie.

Auslösen:
  make buch-korrektorat abschnitt="Einführung Strand"
"""

from __future__ import annotations

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    from workflows.buch import config
    from workflows.buch.agenten import gegenlese, korrigiere

from workflows.buch.pruefungen import (  # noqa: E402
    korrigiere_absatz_index,
    teile_auf,
    verwerfe_dubletten,
    verwerfe_eingriffe_in_rede,
    verwerfe_gewollte_umgangssprache,
    verwerfe_nichtbefunde,
    werk_kontext,
)
from workflows.buch.models import (  # noqa: E402
    BefundMitUrteil,
    Gegenlesung,
    Korrekturen,
    LektoratErgebnis,
    LektoratInput,
)


def _zu_befunden(roh: dict, grenze: int) -> list[BefundMitUrteil]:
    # Nur das Nutzdatenfeld validieren: die Aktivität kann Beiwerk danebenlegen,
    # und Korrekturen verbietet Extrafelder.
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

    Bewusst getrennt von dem, was das zweite Augenpaar beurteilt: Ob ein Suchtext
    eindeutig auffindbar ist, ist eine Tatsache. Ob eine Korrektur berechtigt ist,
    ist ein Urteil.
    """
    hinweise: list[str] = []
    befunde, h = korrigiere_absatz_index(befunde, absaetze)
    hinweise += h
    befunde, h = verwerfe_dubletten(befunde)
    hinweise += h
    befunde, h = verwerfe_nichtbefunde(befunde)
    hinweise += h
    befunde, h = verwerfe_eingriffe_in_rede(befunde, absaetze)
    hinweise += h
    befunde, h = verwerfe_gewollte_umgangssprache(befunde)
    hinweise += h
    return befunde, hinweise


def _wende_gegenlesung_an(
    befunde: list[BefundMitUrteil], g: Gegenlesung
) -> tuple[list[BefundMitUrteil], list[str]]:
    """Trägt das Urteil des zweiten Augenpaars ein.

    Verworfene Befunde werden gesperrt, nicht gelöscht — sie erscheinen im
    Ergebnis unter ``gesperrt`` mit Grund. Nur so lässt sich später auswerten,
    ob das zweite Augenpaar zu streng ist.
    """
    hinweise: list[str] = []

    for u in g.unberechtigt:
        i = u.nummer - 1
        if 0 <= i < len(befunde):
            befunde[i].gesperrt = True
            befunde[i].sperrgrund = f"gegenlesen: {u.warum}"
        else:
            hinweise.append(f"Gegenlesen verweist auf Befund {u.nummer}, den es nicht gibt.")

    for f in g.uebersehen:
        befunde.append(
            BefundMitUrteil(
                ebene="korrektorat",
                absatz_index=f.absatz_index,
                search=f.search,
                replace=f.replace,
                art=f.art,
                warum=f"[von der Gegenlesung ergänzt] {f.warum}",
            )
        )
    if g.uebersehen:
        hinweise.append(f"Gegenlesen hat {len(g.uebersehen)} übersehene(n) Fehler ergänzt.")
    return befunde, hinweise


@workflows.workflow.define(
    name="buch-korrektorat",
    workflow_display_name="Buch · Korrektorat (Ebene 1)",
    workflow_description=(
        "Prüft einen Abschnitt auf Rechtschreibung, Zeichensetzung, Grammatik, Tempus und "
        "Typografie. Ein zweites Augenpaar liest denselben Abschnitt gegen und meldet, was "
        "fehlt und was kein Befund ist — auch dann, wenn die erste Stufe nichts gefunden hat."
    ),
)
class BuchKorrektoratWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: LektoratInput) -> LektoratErgebnis:
        absaetze = inp.absaetze or [inp.abschnitt.text]
        hinweise: list[str] = []

        roh = await korrigiere(titel=inp.abschnitt.titel, absaetze=absaetze)
        befunde = _zu_befunden(roh, inp.max_befunde)

        befunde, h = _invarianten(befunde, absaetze)
        hinweise += h

        # Das zweite Augenpaar läuft IMMER — gerade die leere Befundliste ist der
        # Fall, den sonst niemand prüft.
        if inp.mit_judge and config.AGENTS.get("gegenlesen"):
            roh_g = await gegenlese(
                titel=inp.abschnitt.titel,
                absaetze=absaetze,
                befunde=[b.model_dump(mode="json") for b in befunde],
                kontext=werk_kontext("berechtigung"),
            )
            befunde, h = _wende_gegenlesung_an(befunde, Gegenlesung.model_validate(roh_g))
            hinweise += h
            # Ergänzte Befunde noch einmal durch die Invarianten: Auch das zweite
            # Augenpaar kann einen Suchtext danebenschreiben.
            befunde, h = _invarianten(befunde, absaetze)
            hinweise += h
        elif inp.mit_judge:
            hinweise.append("Ohne Gegenlesen: keine Agent-ID in shared/buch.json.")

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
