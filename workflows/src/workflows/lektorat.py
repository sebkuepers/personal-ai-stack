"""Das Lektorat als Gespräch — der Arbeitsplatz in Le Chat und Vibe Work.

Die anderen Buch-Workflows sind stumm: Text rein, Befunde raus. Dieser hier ist
die Hülle darum, in der tatsächlich gearbeitet wird. Er fragt, was zu tun ist,
zeigt jeden Befund einzeln, holt die Freigabe und hält fest, was entschieden
wurde.

    liste_abschnitte()          Kapitel und Abschnitte aus Scrivener
      ↓  Formular              Kapitel · Ebenen
      ↓  Formular              Abschnitt (auf das Kapitel gefiltert)
    lies_abschnitt()            Absätze samt Hashes
      ↓  TodoList              eine Zeile je Ebene, live
    buch-korrektorat            Kindworkflow, eigene Historie
      ↓  Diff je Befund        nativ als Suchen/Ersetzen, nicht als Fließtext
      ↓  Freigabe              alle · einzeln · überspringen
    Ebene 1 anwenden            bevor Ebene 2 denselben Text ansieht
    buch-stil                   Kindworkflow auf dem korrigierten Text
      ↓  je Befund             annehmen/ablehnen, bei Ablehnung: warum
    Canvas + LektoratSitzung    das Ergebnis, und die Eingabe fürs Zurückschreiben

**Warum die Ebenen nacheinander und dazwischen angewendet wird.** Ein
Stilvorschlag, der sich auf einen Satz bezieht, in dem noch ein Komma fehlt,
passt nach der Korrektur nicht mehr — sein ``search`` findet nichts. Die
Alternative wäre Konfliktlogik zwischen überlappenden Änderungen. Ein
zusätzlicher Durchlauf ist billiger als die.

**Warum Kindworkflows und keine Aktivitäten.** Jede Ebene bekommt eine eigene
Ereignishistorie: Sie wiederholt sich unabhängig, und in Studio lässt sie sich
einzeln aufklappen. Derselbe Workflow läuft außerdem weiterhin headless über die
CLI — die Hülle fügt nur das Gespräch hinzu, nicht die Logik.

**Warum die Ablehnungsgründe vorgeschlagen werden.** Ein frei getippter Grund ist
Anekdote. Vier Vorschläge plus freies Feld ergeben ein Signal, das sich auszählen
lässt — und genau daraus wird später die Annahmequote je Stimmprofil-Regel.

Geschrieben wird hier nichts. Die Sitzung endet mit ``LektoratSitzung``; das
Zurückschreiben ins Manuskript ist ein eigener, abgesicherter Schritt.

Starten: in Le Chat den Workflow wählen, oder
  make buch-lektorat werk=immer-wieder-ruegen
"""

from __future__ import annotations

import re
from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    import mistralai.workflows.plugins.mistralai as wf_mistral
    from workflows.buch.lokal import (
        lade_stimmprofil,
        lies_abschnitt,
        liste_abschnitte,
        liste_werke,
        schreibe_entscheidungen,
    )

import mistralai.workflows.conversational as wf_chat  # noqa: E402
from mistralai.workflows.plugins.mistralai.conversational_ui_components import (  # noqa: E402
    Markdown,
)

from workflows.buch.models import (  # noqa: E402
    AbschnittEingabe,
    Entscheidung,
    LektoratErgebnis,
    LektoratInput,
    LektoratSitzung,
)
from workflows.buch.korrektorat import BuchKorrektoratWorkflow  # noqa: E402
from workflows.buch.stil import BuchStilWorkflow  # noqa: E402

# Dieselbe Anzeige wie in ``buch-uebersicht`` — importiert, nicht nachgebaut.
# Man wählt einen Abschnitt nicht aus einer Liste von 48 Titeln, sondern weil
# man weiß, wo das Buch dünn ist.
from workflows.uebersicht import knopf_beschriftung, outliner  # noqa: E402

# Vorgeschlagene Ablehnungsgründe. Bewusst kurz und in seinen Worten — ein
# Vorschlag, den man antippt, wird benutzt; ein leeres Textfeld nicht.
GRUENDE = [
    "klingt nicht nach mir",
    "verändert die Bedeutung",
    "zu glatt",
    "die Wiederholung ist Absicht",
    "stimmt sachlich nicht",
]

# Kurze Beschriftungen. Die Erklärung steht in der Workflow-Beschreibung, nicht
# in jeder Auswahlzeile — im Dropdown wird sie abgeschnitten und hilft niemandem.
EBENEN = [("korrektorat", "Korrektorat"), ("stil", "Stil")]

# Obergrenzen je Ebene — bewusst keine Einstellung im Formular.
#
# Beim KORREKTORAT wäre eine Grenze schädlich: Sie schneidet die Liste einfach
# ab, und bei einem Abschnitt mit fünfzehn Kommafehlern verschwinden drei
# stillschweigend. Ein Fehler, den niemand meldet, ist schlimmer als eine lange
# Liste. Deshalb 99 — praktisch keine Grenze, aber ein Schutz gegen einen Agenten,
# der durchdreht.
#
# Beim STIL ist die Grenze eine Entscheidung: Das Stimmprofil hat höchstens zwölf
# Regeln, und mehr als eine Handvoll Vorschläge am Stück arbeitet niemand durch.
MAX_BEFUNDE = {"korrektorat": 99, "stil": 12}


def _werkwahl(werke: list[tuple[str, str]]) -> type[wf_chat.FormInput]:
    class Werkwahl(wf_chat.FormInput):
        werk: str = wf_chat.SingleChoice(
            options=werke, description="An welchem Buch?", prefilled_value=werke[0][0]
        )

    return Werkwahl


def _auswahl(optionen: list[tuple[str, str]]) -> type[wf_chat.FormInput]:
    """Abschnitt und Ebenen in EINEM Formular.

    Die Doku ist eindeutig: Es gibt keine Tabellen-Komponente, und keine
    Zeile lässt sich selbst zur Auswahl machen. ``SingleChoice`` ist ein
    Dropdown, ``ConfirmationInput`` sind Knöpfe — mehr steht nicht zur
    Verfügung. Also: die Tabelle zum Scannen, darunter **ein** Formular. Eine
    Knopfreihe, die jede Tabellenzeile noch einmal wiederholt, ist kein
    Fortschritt gegenüber dem Dropdown, sondern dieselbe Liste zweimal.
    """

    class Auswahl(wf_chat.FormInput):
        uuid: str = wf_chat.SingleChoice(
            options=optionen,
            description="Abschnitt",
            prefilled_value=optionen[0][0],
        )
        ebenen: list[str] = wf_chat.MultiChoice(
            options=EBENEN,
            description="Ebenen",
            prefilled_value=["korrektorat"],
        )
    return Auswahl


def _diff_task(titel: str, uuid: str, text: str, befunde: list[dict]) -> wf_chat.ChatAssistantWorkingTask:
    """Befunde als nativen Suchen/Ersetzen-Diff.

    Le Chat rendert ``FileToolUIState`` mit ``ReplaceFileOperation`` als
    Code-Review-Ansicht: Vorher und Nachher untereinander, Änderung markiert.
    Dieselben Befunde als Fließtext wären eine Wand aus Anführungszeichen — und
    der Unterschied zwischen „Die" und „Sie" darin nicht zu sehen.
    """
    return wf_chat.ChatAssistantWorkingTask(
        type="tool",
        title=titel,
        content=f"{len(befunde)} Befund(e)",
        toolUIState=wf_chat.FileToolUIState(
            toolCallId=uuid,
            operations=[
                wf_chat.ReplaceFileOperation(
                    uri=f"file://abschnitt/{uuid}",
                    fileContentBefore=text,
                    blocks=[
                        wf_chat.SearchReplaceBlock(search=b["search"], replace=b["replace"])
                        for b in befunde
                    ],
                )
            ],
        ),
    )


# Satzgrenzen. Bewusst grob: Abkürzungen wie „z. B." zerlegen hier falsch, aber
# ein Satz zu viel schadet nichts — ein Satz zu wenig schon.
_GRENZE = re.compile(r"(?<=[.!?…])[\s\u00a0]+(?=[„\"'(A-ZÄÖÜ])")


def _satz_um(absatz: str, suchtext: str) -> tuple[str, int, int]:
    """Der ganze Satz, in dem ``suchtext`` steht — plus seine Lage darin.

    Ein Befund zeigt nur das, was sich ändert: „wenn" → „wenn,". Das lässt sich
    nicht beurteilen. Erst der Satz drumherum macht sichtbar, ob das Komma dort
    hingehört. Findet sich der Suchtext nicht, kommt der ganze Absatz zurück —
    lieber zu viel Zusammenhang als keiner.
    """
    stelle = absatz.find(suchtext)
    if stelle < 0:
        return absatz, -1, -1
    anfang = 0
    for m in _GRENZE.finditer(absatz):
        if m.end() > stelle:
            break
        anfang = m.end()
    ende = len(absatz)
    for m in _GRENZE.finditer(absatz):
        if m.start() >= stelle + len(suchtext):
            ende = m.start()
            break
    return absatz[anfang:ende].strip(), stelle - anfang, stelle - anfang + len(suchtext)


def _vorher_nachher(absaetze: list[str], b: dict) -> str:
    """Der Satz vor und nach der Änderung, die Änderung selbst hervorgehoben."""
    i = b.get("absatz_index", 0)
    if not 0 <= i < len(absaetze):
        return f"− {b['search']}\n+ {b['replace']}"
    satz, a, e = _satz_um(absaetze[i], b["search"])
    if a < 0:
        return f"> {satz}\n\n− {b['search']}\n+ {b['replace']}"
    return (
        f"> {satz[:a]}**{satz[a:e]}**{satz[e:]}\n\n"
        f"> {satz[:a]}**{b['replace']}**{satz[e:]}"
    )


def _liste(befunde: list[dict], absaetze: list[str]) -> str:
    zeilen = []
    for i, b in enumerate(befunde, start=1):
        kopf = f"**{i}.** `{b['art']}`  ·  Absatz {b.get('absatz_index', 0)}"
        if b.get("regel_id"):
            kopf += f" · {b['regel_id']}"
        zeilen += [kopf, "", _vorher_nachher(absaetze, b), "", f"_{b.get('warum', '')}_", ""]
    return "\n".join(zeilen)


def _anwenden(absaetze: list[str], entscheidungen: list[Entscheidung]) -> tuple[list[str], list[str]]:
    """Wendet angenommene Befunde auf die Absätze an — im Speicher, nicht auf der Platte.

    Dieselbe Strenge wie beim späteren Schreiben ins Manuskript: Der Suchtext muss
    genau einmal vorkommen. Kein Fuzzy-Matching. Was nicht eindeutig passt, wird
    gemeldet und übersprungen, statt geraten.
    """
    neu = list(absaetze)
    hinweise: list[str] = []
    for e in entscheidungen:
        if e.entscheidung != "angenommen":
            continue
        if not 0 <= e.absatz_index < len(neu):
            hinweise.append(f"Absatz {e.absatz_index} gibt es nicht — {e.search!r} übersprungen.")
            continue
        if e.eigene_fassung:
            # Die Fassung des Autors ersetzt den ganzen Absatz. Weitere Befunde
            # auf demselben Absatz greifen danach meist ins Leere — das ist
            # richtig so: Er hat den Absatz neu geschrieben, nicht geflickt.
            neu[e.absatz_index] = e.eigene_fassung
            continue
        treffer = neu[e.absatz_index].count(e.search)
        if treffer != 1:
            hinweise.append(
                f"{e.search!r} kommt in Absatz {e.absatz_index} {treffer}-mal vor — übersprungen."
            )
            continue
        neu[e.absatz_index] = neu[e.absatz_index].replace(e.search, e.replace, 1)
    return neu, hinweise


@workflows.workflow.define(
    name="buch-lektorat",
    workflow_display_name="Buch · Lektorat (im Gespräch)",
    workflow_description=(
        "Lektoriert einen Abschnitt im Dialog: Kapitel und Ebenen wählen, Befunde als Diff "
        "ansehen, einzeln freigeben oder ablehnen. Schreibt nichts ins Manuskript — das "
        "Ergebnis ist eine Sitzung, die man danach anwenden kann."
    ),
    execution_timeout=timedelta(hours=12),
    # Keine search_keys: Die gibt es nur als Pfade in die ENTRYPOINT-EINGABE,
    # und dieser Workflow hat bewusst keine (siehe run()). Eine Laufzeit-API
    # zum Nachtragen existiert in der SDK nicht — geprüft, nicht vermutet.
    # Auffindbar sind die Sitzungen über das Entscheidungslog, das Werk,
    # Abschnitt und Sitzungs-ID je Zeile trägt.
)
class BuchLektoratWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> wf_mistral.ChatAssistantWorkflowOutput:
        # KEIN Eingabeparameter. Drei Anläufe waren nötig, bis der Start in Le
        # Chat nicht mehr nervte:
        #   1. Modell mit Extrafeld ``werk``        -> roher JSON-Editor
        #   2. ``message`` mit Standardwert          -> ebenfalls JSON-Editor
        #   3. ``message`` als Pflichtfeld           -> Le Chat fragt die
        #      getippte Nachricht ein ZWEITES Mal ab
        # Der Workflow braucht die Nachricht nicht — alles Nötige wird über
        # Formulare gefragt. Ohne Eingabeschema gibt es nichts zu erfragen, und
        # der Workflow läuft sofort los.
        #
        # Die Fortschrittsliste steht GANZ VORN, mit allen Schritten, die kommen
        # können — auch den beiden Auswahlschritten. Sie erst nach der Auswahl zu
        # erzeugen war ein schlechter Tausch: Am Anfang weiß man am wenigsten, wo
        # man ist, und genau dann war das Feld leer. Wird eine Ebene nicht
        # gewählt, bleiben ihre beiden Posten offen — das ist die Wahrheit und
        # liest sich auch so.
        schritt = {
            "werk": wf_chat.TodoListItem(
                title="Buch wählen", description="Welches Manuskript"
            ),
            "auswahl": wf_chat.TodoListItem(
                title="Abschnitt und Ebenen wählen", description="Aus der Gliederung"
            ),
            "korrektorat_pruefen": wf_chat.TodoListItem(
                title="Korrektorat prüfen",
                description="Rechtschreibung, Zeichensetzung, Grammatik — dann gegenlesen",
            ),
            "korrektorat_freigabe": wf_chat.TodoListItem(
                title="Korrektorat freigeben", description="Befunde übernehmen oder ablehnen"
            ),
            "stil_pruefen": wf_chat.TodoListItem(
                title="Stil prüfen", description="Gegen das Stimmprofil, mit Regelbezug"
            ),
            "stil_freigabe": wf_chat.TodoListItem(
                title="Stil freigeben", description="Vorschläge übernehmen oder ablehnen"
            ),
            "abschluss": wf_chat.TodoListItem(
                title="Sitzung abschließen",
                description="Text zusammensetzen, Entscheidungen sichern",
            ),
        }
        async with wf_chat.TodoList(items=list(schritt.values())):
            return await self._sitzung(schritt)

    async def _sitzung(
        self, schritt: dict[str, wf_chat.TodoListItem]
    ) -> wf_mistral.ChatAssistantWorkflowOutput:
        """Die eigentliche Sitzung — ausgelagert, damit die TodoList sie umschließt."""
        werke = await liste_werke()
        if not werke:
            return wf_mistral.ChatAssistantWorkflowOutput(
                content=[wf_mistral.TextOutput(text="Kein Werk in `shared/buch/` gefunden.")],
                isError=True,
            )
        await schritt["werk"].set_status("in_progress")
        if len(werke) == 1:
            werk = werke[0]["slug"]
        else:
            # Nur fragen, wenn es etwas zu wählen gibt. Ein Formular mit einer
            # einzigen Option ist eine Verzögerung, keine Auswahl.
            gewaehltes = await self.wait_for_input(
                _werkwahl([(w["slug"], w["titel"]) for w in werke]),
                label="Werk",
                timeout=timedelta(hours=8),
            )
            werk = gewaehltes.werk
        await schritt["werk"].set_status("done")

        katalog = await liste_abschnitte(werk)
        alle = katalog["abschnitte"]

        if not alle:
            return wf_mistral.ChatAssistantWorkflowOutput(
                content=[wf_mistral.TextOutput(text=f"In {werk!r} steht noch kein Text.")],
                isError=True,
            )

        async with schritt["auswahl"]:
            uuid, ebenen = await self._auswaehlen(katalog, alle)

        abschnitt = await lies_abschnitt(werk, uuid)
        # Eine Kennung je Sitzung, replay-sicher aus dem Workflow-Zufall.
        # `workflow.info()` gibt es in Mistrals Wrapper nicht — das ist
        # temporalio, und der Aufruf ließ die Aktivierung mit AttributeError
        # scheitern, still, nach der ersten Freigabe.
        sitzung_id = str(workflow.uuid4())
        absaetze: list[str] = list(abschnitt["absaetze"])
        hashes: list[str] = list(abschnitt["hashes"])
        sitzung = LektoratSitzung(
            werk=werk,
            abschnitt_uuid=abschnitt["uuid"],
            abschnitt_titel=abschnitt["titel"],
            ebenen=ebenen,
            text_vorher="\n\n".join(absaetze),
        )

        stimmprofil = await lade_stimmprofil(werk) if "stil" in ebenen else ""
        if "stil" in ebenen and not stimmprofil:
            ebenen = [e for e in ebenen if e != "stil"]
            sitzung.hinweise.append(
                "Ohne Stimmprofil wäre die Stilebene generische Stilkritik — übersprungen. "
                "Erst `make buch-stimmprofil` laufen lassen."
            )

        for ebene in ebenen:
            async with schritt[f"{ebene}_pruefen"]:
                eingabe = LektoratInput(
                    werk=werk,
                    abschnitt=AbschnittEingabe(
                        uuid=abschnitt["uuid"],
                        titel=abschnitt["titel"],
                        text="\n\n".join(absaetze),
                        pfad=abschnitt.get("pfad") or [],
                    ),
                    absaetze=absaetze,
                    stimmprofil_text=stimmprofil if ebene == "stil" else "",
                    max_befunde=MAX_BEFUNDE[ebene],
                )
                roh = await workflows.workflow.execute_workflow(
                    BuchKorrektoratWorkflow if ebene == "korrektorat" else BuchStilWorkflow,
                    params=eingabe,
                    execution_timeout=timedelta(minutes=15),
                )
                ergebnis = LektoratErgebnis.model_validate(
                    roh if isinstance(roh, dict) else roh.model_dump()
                )

            async with schritt[f"{ebene}_freigabe"]:
                try:
                    entscheidungen = await self._durchgehen(
                        ebene, ergebnis, absaetze, hashes, abschnitt
                    )
                except TimeoutError:
                    # Der Autor ist weg. Was bis hierher entschieden wurde, ist
                    # bereits im Log (siehe unten) — die Sitzung endet als
                    # Teilsitzung statt als Verlust.
                    sitzung.abgebrochen = True
                    sitzung.hinweise.append(
                        f"{ebene}: Zeitüberschreitung beim Warten auf Freigaben — "
                        "Sitzung als Teilsitzung beendet."
                    )
                    break
            sitzung.entscheidungen += entscheidungen
            sitzung.hinweise += ergebnis.hinweise

            # SOFORT ins Log, nicht erst am Ende. Bricht danach etwas ab, sind
            # diese Entscheidungen trotzdem da. Das Log ist das Kapital des
            # Systems — jeder angetippte Ablehnungsgrund ist ein Datenpunkt fürs
            # Stimmprofil, und bis hierher wurde er beim Schließen des Chats
            # einfach weggeworfen.
            if entscheidungen:
                await schreibe_entscheidungen(
                    werk=werk,
                    abschnitt=abschnitt,
                    sitzung_id=sitzung_id,
                    entscheidungen=[e.model_dump(mode="json") for e in entscheidungen],
                )

            # Ebene 1 anwenden, BEVOR Ebene 2 denselben Text sieht.
            absaetze, h = _anwenden(absaetze, entscheidungen)
            sitzung.hinweise += h

        async with schritt["abschluss"]:
            sitzung.text_nachher = "\n\n".join(absaetze)
            ausgabe = self._abschluss(sitzung)
        return ausgabe

    # ------------------------------------------------------------------
    async def _auswaehlen(
        self, katalog: dict, alle: list[dict]
    ) -> tuple[str, list[str]]:
        """Tabelle zum Scannen, ein Formular zum Wählen.

        Hier standen einmal Kennzahlen und zwei Tortendiagramme. Sie schoben die
        Auswahl zwei Bildschirme nach unten und beantworteten eine Frage, die an
        dieser Stelle niemand stellt. Wer wissen will, wie weit das Buch ist,
        ruft ``buch-uebersicht`` auf.
        """
        await wf_mistral.send_assistant_message(
            [
                wf_mistral.TextOutput(text=f"**{katalog['titel']}**"),
                wf_mistral.ResourceOutput(
                    resource=wf_mistral.UIComponentResource(
                        component=Markdown(content=outliner(alle, mit_kapitel=True))
                    )
                ),
            ]
        )
        wahl = await self.wait_for_input(
            _auswahl([(a["uuid"], knopf_beschriftung(a)) for a in alle]),
            label="Abschnitt und Ebenen",
            timeout=timedelta(hours=8),
        )
        ebenen = [e for e, _ in EBENEN if e in (wahl.ebenen or [])] or ["korrektorat"]
        return wahl.uuid, ebenen

    # ------------------------------------------------------------------
    async def _durchgehen(
        self,
        ebene: str,
        ergebnis: LektoratErgebnis,
        absaetze: list[str],
        hashes: list[str],
        abschnitt: dict,
    ) -> list[Entscheidung]:
        """Zeigt die Befunde einer Ebene und holt die Freigaben."""
        befunde = [b.model_dump(mode="json") for b in ergebnis.befunde]
        name = "Korrektorat" if ebene == "korrektorat" else "Stil"

        if ergebnis.gesperrt:
            await wf_mistral.send_assistant_message(
                f"**{name}:** {len(ergebnis.gesperrt)} Vorschlag/Vorschläge hat das Gegenlesen "
                "zurückgehalten, bevor sie dich erreicht haben:\n\n"
                + "\n".join(f"- `{b.search}` — {b.sperrgrund}" for b in ergebnis.gesperrt)
            )

        if not befunde:
            await wf_mistral.send_assistant_message(
                f"**{name}:** keine Befunde. Der Abschnitt trägt."
            )
            return []

        # Erst der Diff, dann die Liste: Das Bild zuerst, die Begründungen danach.
        async with wf_chat.Task[wf_chat.ChatAssistantWorkingTask](
            type="working",
            state=_diff_task(
                f"{name} · {abschnitt['titel']}",
                abschnitt["uuid"],
                "\n\n".join(absaetze),
                befunde,
            ),
        ):
            pass

        nach_art = " · ".join(f"{n}× {art}" for art, n in sorted(ergebnis.nach_art.items()))
        await wf_mistral.send_assistant_message(
            f"**{name} — {len(befunde)} Befund(e)**  ({nach_art})\n\n"
            + _liste(befunde, absaetze)
        )

        wie = await self.wait_for_input(
            wf_chat.ConfirmationInput(
                options=[
                    ("alle", f"Alle {len(befunde)} übernehmen"),
                    ("einzeln", "Einzeln durchgehen"),
                    ("keine", "Diese Ebene überspringen"),
                ],
                description=f"{name}: wie willst du damit umgehen?",
            ),
            label=f"{name} — Freigabe",
            timeout=timedelta(hours=8),
        )
        modus = getattr(wie, "choice", None) or getattr(wie, "value", "einzeln")

        def bauen(b: dict, wahl: str, grund: str = "") -> Entscheidung:
            i = b["absatz_index"]
            return Entscheidung(
                ebene=ebene,
                absatz_index=i,
                absatz_hash=hashes[i] if 0 <= i < len(hashes) else "",
                search=b["search"],
                replace=b["replace"],
                art=b["art"],
                warum=b.get("warum", ""),
                regel_id=b.get("regel_id"),
                entscheidung=wahl,
                grund=grund,
            )

        if modus == "alle":
            return [bauen(b, "angenommen") for b in befunde]
        if modus == "keine":
            return [bauen(b, "zurueckgestellt") for b in befunde]

        entscheidungen: list[Entscheidung] = []
        for i, b in enumerate(befunde, start=1):
            antwort = await self.wait_for_input(
                wf_chat.ConfirmationInput(
                    options=[
                        ("uebernehmen", "Übernehmen"),
                        ("selbst", "Selbst formulieren"),
                        ("ablehnen", "Ablehnen"),
                    ],
                    description=(
                        f"**{i}/{len(befunde)}** · `{b['art']}` · Absatz {b['absatz_index']}"
                        + (f" · {b['regel_id']}" if b.get("regel_id") else "")
                        + "\n\n"
                        + _vorher_nachher(absaetze, b)
                        + f"\n\n_{b.get('warum', '')}_"
                    ),
                ),
                label=f"{name} {i}/{len(befunde)}",
                timeout=timedelta(hours=8),
            )
            wahl = getattr(antwort, "choice", "ablehnen")

            if wahl == "uebernehmen":
                entscheidungen.append(bauen(b, "angenommen"))
                continue

            if wahl == "selbst":
                # Der wertvollste Ausgang: Der Autor nimmt den Gedanken an und
                # formuliert ihn selbst. Dieses Paar — Vorschlag und seine
                # Fassung — hat kein Modell erzeugt, und es geht so ins Log.
                # Der Canvas zeigt den Absatz MIT angewendetem Vorschlag, denn
                # der ist der Ausgangspunkt, nicht das Original.
                idx = b["absatz_index"]
                if 0 <= idx < len(absaetze):
                    vorlage = absaetze[idx].replace(b["search"], b["replace"], 1)
                    uri = f"file://canvas/{abschnitt['uuid']}/{idx}/{i}"
                    await wf_mistral.send_assistant_message(
                        "Formuliere den Absatz so, wie du ihn haben willst, und schick ihn zurück.",
                        canvas=wf_mistral.CanvasResource(
                            uri=uri,
                            canvas=wf_mistral.CanvasPayload(
                                type="text/markdown",
                                title=f"Absatz {idx} — deine Fassung",
                                content=vorlage,
                            ),
                        ),
                    )
                    eigene = await self.wait_for_input(
                        wf_chat.CanvasInput(uri),
                        label=f"{name} {i}/{len(befunde)} — eigene Fassung",
                        timeout=timedelta(hours=8),
                    )
                    fassung = eigene.canvas.content.strip()
                    e = bauen(b, "angenommen")
                    if fassung and fassung != vorlage:
                        e.eigene_fassung = fassung
                    entscheidungen.append(e)
                    continue

            # Der Grund ist der Ertrag dieser Sitzung — deshalb wird er gefragt,
            # und deshalb steht er als Vorschlag da statt als leeres Feld.
            warum = await self.wait_for_input(
                wf_chat.ChatInput(
                    "Warum nicht? (antippen oder frei schreiben)",
                    suggestions=[[wf_chat.TextChunk(text=g)] for g in GRUENDE],
                ),
                label=f"{name} {i}/{len(befunde)} — Grund",
                timeout=timedelta(hours=8),
            )
            entscheidungen.append(
                bauen(b, "abgelehnt", " ".join(c.text for c in warum.message).strip())
            )
        return entscheidungen

    # ------------------------------------------------------------------
    def _abschluss(self, s: LektoratSitzung) -> wf_mistral.ChatAssistantWorkflowOutput:
        """Canvas mit dem Ergebnis, plus die Sitzung als strukturierte Ausgabe."""
        ja = len(s.angenommen)
        nein = len([e for e in s.entscheidungen if e.entscheidung == "abgelehnt"])
        offen = len([e for e in s.entscheidungen if e.entscheidung == "zurueckgestellt"])

        kopf = [f"**{s.abschnitt_titel}** — {ja} übernommen"]
        if nein:
            kopf.append(f"{nein} abgelehnt")
        if offen:
            kopf.append(f"{offen} zurückgestellt")
        text = ", ".join(kopf)
        if s.hinweise:
            # Getrennt ausweisen: Was hier steht, hat ihn nie erreicht — es sind
            # Vorschläge, die an den Invarianten oder am Gegenlesen gescheitert
            # sind. In einer Liste mit seinen eigenen Entscheidungen liest sich
            # das wie ein Fehler, der ihm unterlaufen ist.
            text += (
                "\n\n_Vorher automatisch aussortiert, ohne dass du sie zu sehen "
                "bekamst:_\n"
                + "\n".join(f"- {h}" for h in s.hinweise)
            )
        if ja:
            text += (
                "\n\nDas Manuskript ist unverändert. Zum Anwenden: "
                f"`make buch-anwenden werk={s.werk} uuid={s.abschnitt_uuid[:8]}`"
            )

        inhalt: list = [wf_mistral.TextOutput(text=text)]
        if ja:
            inhalt.append(
                wf_mistral.ResourceOutput(
                    resource=wf_mistral.CanvasResource(
                        uri=f"file://canvas/{s.abschnitt_uuid}",
                        readonly=True,
                        canvas=wf_mistral.CanvasPayload(
                            type="text/markdown",
                            title=f"{s.abschnitt_titel} — lektoriert",
                            content=s.text_nachher,
                        ),
                    )
                )
            )
        return wf_mistral.ChatAssistantWorkflowOutput(
            content=inhalt,
            structuredContent=s.model_dump(mode="json"),
        )
