"""Probe: Rendert Vibe Work eine ``TodoList``?

Kein Produktivworkflow. Er existiert, um EINE Frage zu beantworten, die sich
durch Hinsehen nicht klären ließ: ``buch-lektorat`` sendet nachweislich
``todo_list``-Ereignisse — 27 je Durchlauf, mit Titel und Status —, aber in Vibe
ist keine Häkchenliste zu sehen, auch nicht in der aufgeklappten
„Arbeite"-Zeile.

Zwei Erklärungen waren möglich:

1. Vibe rendert ``todo_list`` nicht.
2. Es rendert sie, aber nicht an der Stelle, an der ich sie erzeuge — bei
   ``buch-lektorat`` steht sie hinter zwei Formularen, im Doku-Beispiel steht sie
   allein.

Dieser Workflow ist das Doku-Beispiel, Zeile für Zeile, nur mit echten Pausen,
damit man beim Zusehen etwas sieht. Läuft die Liste hier, war es Erklärung 2 und
``buch-lektorat`` muss umgebaut werden. Läuft sie hier nicht, war es Erklärung 1
und die TodoList ist in dieser Oberfläche schlicht nicht zu gebrauchen.

Danach kann die Datei weg.

  make fortschritt-probe
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    import mistralai.workflows.plugins.mistralai as workflows_mistralai


@workflows.workflow.define(
    name="fortschritt-probe",
    workflow_display_name="Probe · Fortschrittsanzeige",
    workflow_description=(
        "Zeigt drei Schritte als TodoList mit je fünf Sekunden Pause. Dient nur der Frage, "
        "ob Vibe Work eine TodoList überhaupt darstellt."
    ),
    execution_timeout=timedelta(minutes=10),
)
class FortschrittProbeWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> workflows_mistralai.ChatAssistantWorkflowOutput:
        eins = workflows_mistralai.TodoListItem(
            title="Erster Schritt", description="Läuft fünf Sekunden"
        )
        zwei = workflows_mistralai.TodoListItem(
            title="Zweiter Schritt", description="Läuft auch fünf Sekunden"
        )
        drei = workflows_mistralai.TodoListItem(
            title="Dritter Schritt", description="Und noch einmal fünf"
        )

        async with workflows_mistralai.TodoList(items=[eins, zwei, drei]):
            for posten in (eins, zwei, drei):
                async with posten:
                    # asyncio.sleep ist im Workflow erlaubt: Der Timer läuft
                    # durable auf dem Server, nicht als blockierende Pause im
                    # Worker. Genau dafür ist er da.
                    await asyncio.sleep(5)

        return workflows_mistralai.ChatAssistantWorkflowOutput(
            content=[
                workflows_mistralai.TextOutput(
                    text=(
                        "Fertig. Wenn oben drei abgehakte Schritte standen, rendert Vibe "
                        "die TodoList — dann liegt es bei `buch-lektorat` an der Stelle, an "
                        "der ich sie erzeuge. Wenn nicht, rendert Vibe sie nicht."
                    )
                )
            ]
        )
