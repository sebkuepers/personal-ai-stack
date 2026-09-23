"""Wie weit ist das Buch? — Struktur, Dichte und Stand auf einen Blick.

Scrivener kennt zu jedem Abschnitt ein **Etikett** (worum es geht: „Historische
Geschichten", „Beziehungen & Personen") und einen **Status** („Rohfassung",
„Ausgebaut", „Redigiert" …). Beides pflegt der Autor ohnehin — es ist die
ehrlichste Fortschrittsangabe im ganzen Projekt, weil sie von ihm kommt und
nicht von einem Modell.

Dieser Workflow rechnet nichts aus, was ein Modell entscheiden müsste. Er zählt.
Alles hier ist deterministisch; kein Agent wird aufgerufen. Das ist Absicht: Eine
Fortschrittsanzeige, die halluzinieren kann, ist schlimmer als keine.

Gezeigt wird:

* ein **Canvas** mit der vollständigen Gliederung — Kapitel, Abschnitte, Wörter,
  Status, Etikett; leere Gliederungsknoten ausdrücklich als solche markiert
* ein **Balkendiagramm** der Wörter je Kapitel — die Dichte, und wo sie fehlt
* ein **Tortendiagramm** der Status — wie viel ist wirklich mehr als Rohfassung
* eine **Warnung**, wenn ein Kapitel aus dem Plan im Manuskript noch fehlt

Starten: in Le Chat den Workflow wählen, oder
  make buch-uebersicht werk=immer-wieder-ruegen
"""

from __future__ import annotations

from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    import mistralai.workflows.plugins.mistralai as wf_mistral
    from workflows.buch.lokal import liste_abschnitte, liste_werke

import mistralai.workflows.conversational as wf_chat  # noqa: E402
from mistralai.workflows.plugins.mistralai.conversational_ui_components import (  # noqa: E402
    Alert,
    Badge,
    Card,
    Chart,
    Column,
    PieChart,
    Row,
)

# „Rohfassung" ist der Anfang, „Fertig" das Ende. Die Reihenfolge steckt in
# Scrivener nur als ID, deshalb hier noch einmal — für die Sortierung der
# Diagramme, nicht als zweite Quelle der Wahrheit.
STUFEN = ["Rohfassung", "Ausgebaut", "Redigiert", "Korrigiert", "Letzter Entwurf", "Fertig"]


def _werkwahl(werke: list[tuple[str, str]]) -> type[wf_chat.FormInput]:
    class Werkwahl(wf_chat.FormInput):
        werk: str = wf_chat.SingleChoice(
            options=werke, description="Welches Buch?", prefilled_value=werke[0][0]
        )

    return Werkwahl


def _nach_kapitel(abschnitte: list[dict], leer: list[dict]) -> list[dict]:
    """Kapitel in Binder-Reihenfolge, mit ihren Abschnitten."""
    kapitel: dict[str, dict] = {}
    for a in abschnitte + leer:
        k = kapitel.setdefault(
            a["kapitel"], {"name": a["kapitel"], "abschnitte": [], "woerter": 0}
        )
        k["abschnitte"].append(a)
        k["woerter"] += a.get("woerter", 0)
    return list(kapitel.values())


def _gliederung(katalog: dict) -> str:
    """Die Gliederung als Markdown-Tabelle je Kapitel — Zuschnitt wie im Outliner."""
    zeilen = [f"# {katalog['titel']}"]
    if katalog.get("untertitel"):
        zeilen.append(f"*{katalog['untertitel']}*")
    gesamt = sum(a["woerter"] for a in katalog["abschnitte"])
    zeilen += ["", f"{gesamt:,} Wörter".replace(",", "."), ""]

    for k in _nach_kapitel(katalog["abschnitte"], katalog.get("leer", [])):
        mit_text = [a for a in k["abschnitte"] if a.get("woerter")]
        zeilen += [
            f"## {k['name']}",
            "",
            f"{k['woerter']:,} Wörter · {len(mit_text)} von {len(k['abschnitte'])} "
            "Abschnitten geschrieben".replace(",", "."),
            "",
            # Dieselbe Tabelle wie im Chat: ein Zuschnitt, nicht zwei. Ein leerer
            # Knoten steht mit „—" statt „0" — er ist ein freigehaltener Platz,
            # kein leergeschriebener Abschnitt.
            outliner(k["abschnitte"]),
            "",
        ]
    return "\n".join(zeilen)


def kennzahlen_karten(katalog: dict) -> list:
    """Kennzahlen, Dichte je Kapitel, Verteilung der Stände.

    Ohne Unterstrich, weil ``buch-lektorat`` sie ebenfalls zeigt — dort direkt
    vor der Abschnittswahl. Man wählt einen Abschnitt nicht aus einer Liste von
    48 Titeln, sondern weil man weiß, wo das Buch dünn ist.
    """
    abschnitte = katalog["abschnitte"]
    kapitel = _nach_kapitel(abschnitte, katalog.get("leer", []))
    gesamt = sum(a["woerter"] for a in abschnitte)
    laengster = max(abschnitte, key=lambda a: a["woerter"], default=None)

    stand: dict[str, int] = {}
    for a in abschnitte:
        stand[a.get("status") or "—"] = stand.get(a.get("status") or "—", 0) + 1
    etiketten: dict[str, int] = {}
    for a in abschnitte:
        name = a.get("etikett") or "—"
        if name != "Kein Etikett":
            etiketten[name] = etiketten.get(name, 0) + 1

    ueber_rohfassung = sum(n for s, n in stand.items() if s not in ("Rohfassung", "—"))

    teile: list = [
        Row(
            gap="md",
            wrap=True,
            children=[
                Card(title=f"{gesamt:,}".replace(",", "."), description="Wörter"),
                Card(title=str(len(abschnitte)), description="Abschnitte mit Text"),
                Card(title=str(len(kapitel)), description="Kapitel"),
                Card(
                    title=f"{ueber_rohfassung}/{len(abschnitte)}",
                    description="über Rohfassung hinaus",
                ),
                Card(
                    title=str(round(gesamt / max(len(abschnitte), 1))),
                    description="Wörter je Abschnitt im Mittel",
                ),
            ],
        ),
        Chart(
            variant="bar",
            title="Dichte — Wörter je Kapitel",
            data=[{"Kapitel": k["name"], "Wörter": k["woerter"]} for k in kapitel],
            xAxis="Kapitel",
            yAxis="Wörter",
        ),
    ]

    if len(stand) > 1:
        teile.append(
            PieChart(
                title="Stand der Abschnitte",
                data=[
                    {"name": s, "value": stand[s]}
                    for s in STUFEN + [x for x in stand if x not in STUFEN]
                    if s in stand
                ],
            )
        )
    if etiketten:
        teile.append(
            PieChart(
                title="Etiketten — worum es geht",
                data=[{"name": n, "value": v} for n, v in sorted(etiketten.items())],
            )
        )
    if laengster:
        teile.append(
            Row(
                gap="sm",
                wrap=True,
                children=[
                    Badge(children="längster Abschnitt", variant="default"),
                    Badge(
                        children=f"{laengster['titel']} · {laengster['woerter']} Wörter",
                        variant="primary",
                    ),
                ],
            )
        )
    return teile


def wo_rangehen(katalog: dict, *, wie_viele: int = 5) -> list:
    """Die eigentliche Entscheidungshilfe: Wo lohnt sich die nächste Stunde?

    Kennzahlen sagen, wie es steht. Sie sagen nicht, was zu tun ist. Deshalb hier
    drei Ranglisten — alle abgezählt, keine geschätzt:

    * **dünn** — Abschnitte in Rohfassung mit auffällig wenig Text. Nicht absolut,
      sondern gegen den Durchschnitt dieses Buchs; was für dieses Manuskript kurz
      ist, weiß nur dieses Manuskript.
    * **liegengeblieben** — am längsten nicht angefasst, noch in Rohfassung.
    * **leer** — Gliederungsknoten ohne einen einzigen Satz.

    Bewusst als Liste und nicht als eine einzige Empfehlung: Welche der drei
    Fragen gerade dran ist, entscheidet der Autor, nicht die Statistik.
    """
    abschnitte = katalog["abschnitte"]
    if not abschnitte:
        return []
    mittel = sum(a["woerter"] for a in abschnitte) / len(abschnitte)
    roh = [a for a in abschnitte if (a.get("status") or "Rohfassung") == "Rohfassung"]

    duenn = sorted([a for a in roh if a["woerter"] < mittel * 0.6], key=lambda a: a["woerter"])
    alt = sorted([a for a in roh if a.get("zuletzt")], key=lambda a: a["zuletzt"])
    # Nur echte Abschnitte, keine Kapitel- oder Gruppenordner: Die haben nie
    # eigenen Text und wären als „fehlt noch" schlicht falsch.
    leer = [a for a in katalog.get("leer", []) if not a.get("ist_ordner")]

    def liste(eintraege: list[dict], zeile) -> str:  # noqa: ANN001
        return "\n".join(f"- {zeile(a)}" for a in eintraege[:wie_viele]) or "—"

    karten: list = []
    if duenn:
        karten.append(
            Card(
                title="Dünn geblieben",
                description=f"Rohfassung, deutlich unter dem Schnitt von {round(mittel)} Wörtern",
                children=liste(
                    duenn, lambda a: f"**{a['titel']}** · {a['woerter']} Wörter · {a['kapitel']}"
                ),
            )
        )
    if alt:
        karten.append(
            Card(
                title="Am längsten nicht angefasst",
                description="noch Rohfassung",
                children=liste(
                    alt, lambda a: f"**{a['titel']}** · {_tag(a['zuletzt'])} · {a['woerter']} Wörter"
                ),
            )
        )
    if leer:
        karten.append(
            Card(
                title="Noch kein Satz",
                description=f"{len(leer)} Gliederungsknoten ohne Text",
                children=liste(leer, lambda a: f"**{a['titel']}** · {a['kapitel']}"),
            )
        )
    return [Row(gap="md", wrap=True, children=karten)] if karten else []


def _tag(iso: str) -> str:
    """ISO-Datum als TT.MM. — deutsche Reihenfolge, Jahr weggelassen."""
    if not iso or len(iso) < 10:
        return "—"
    return f"{iso[8:10]}.{iso[5:7]}."


def outliner(abschnitte: list[dict], *, mit_kapitel: bool = False) -> str:
    """Eine Tabelle im Zuschnitt des Scrivener-Outliners.

    Dieselben Spalten in derselben Reihenfolge, die der Autor dort ohnehin
    scannt: Titel, Etikett, Status, Wörter, zuletzt geändert. Der Sinn ist nicht
    Vollständigkeit, sondern **Wiedererkennbarkeit** — man soll nicht zweimal
    lernen müssen, wo man hinschaut.

    ``mit_kapitel`` **gruppiert** nach Kapitel, statt eine Kapitelspalte
    anzuhängen. Eine flache Liste über alle 48 Abschnitte wiederholte „Voll zur
    Oma" vierundzwanzigmal — Platz für eine Information, die aus der Gliederung
    ohnehin hervorgeht. Scrivener rückt ein; das hier tut dasselbe mit
    Zwischenüberschriften.
    """
    if mit_kapitel:
        # Nach dem VOLLEN Pfad gruppieren, nicht nur nach Kapitel: Scrivener
        # kennt Untergruppen (Kapitel / Szenenblock / Abschnitt), und die sind
        # beim Suchen genauso Orientierung wie das Kapitel selbst. Überschriften
        # statt Einrückung, weil Markdown keine Einrückung in Tabellen kennt.
        gruppen: dict[tuple[str, ...], list[dict]] = {}
        for a in abschnitte:
            gruppen.setdefault(tuple(a.get("pfad") or [a.get("kapitel") or "—"]), []).append(a)

        teile: list[str] = []
        letzter: tuple[str, ...] = ()
        for pfad, eintraege in gruppen.items():
            # Nur die Ebenen ausgeben, die sich gegenüber der vorigen Gruppe
            # geändert haben — sonst steht das Kapitel über jeder Untergruppe.
            for tiefe, name in enumerate(pfad):
                if tiefe < len(letzter) and letzter[tiefe] == name:
                    continue
                teile.append(f"{'#' * (3 + tiefe)} {name}")
            letzter = pfad
            woerter = sum(x.get("woerter", 0) for x in eintraege)
            teile += [
                f"{woerter:,} Wörter · {len(eintraege)} Abschnitte".replace(",", "."),
                "",
                outliner(eintraege),
                "",
            ]
        return "\n".join(teile)

    kopf = ["Abschnitt", "Etikett", "Status", "Wörter", "zuletzt"]
    zeilen = [
        "| " + " | ".join(kopf) + " |",
        "|---|---|---|---:|---|",
    ]
    for a in abschnitte:
        w = a.get("woerter", 0)
        zeilen.append(
            "| "
            + " | ".join(
                [
                    a["titel"],
                    (a.get("etikett") or "—").replace("Kein Etikett", "—"),
                    a.get("status") or "—",
                    str(w) if w else "—",
                    _tag(a.get("zuletzt", "")),
                ]
            )
            + " |"
        )
    return "\n".join(zeilen)


def knopf_beschriftung(a: dict) -> str:
    """Ein Abschnitt als Zeile im Auswahlfeld — kurz."""
    # Nur Titel und Umfang. Status und Datum stehen in der Tabelle darüber; sie
    # hier zu wiederholen macht die Zeile lang und die Auswahl nicht besser.
    return f"{a['titel']} · {a['woerter']} W" if a.get("woerter") else a["titel"]


def _fehlende_kapitel(katalog: dict) -> list[str]:
    """Kapitel, die im Plan stehen, aber im Binder fehlen.

    Der Plan lebt in ``shared/buch/<slug>.json``, das Manuskript in Scrivener.
    Dass die beiden auseinanderlaufen, merkt man sonst erst beim PDF-Satz.
    """
    vorhanden = {a["kapitel"] for a in katalog["abschnitte"]} | {
        a["kapitel"] for a in katalog.get("leer", [])
    }
    return [k for k in katalog.get("kapitel_geplant", []) if k and k not in vorhanden]


@workflows.workflow.define(
    name="buch-uebersicht",
    workflow_display_name="Buch · Übersicht",
    workflow_description=(
        "Zeigt Struktur, Dichte und Stand eines Buchs: Gliederung als Canvas, Wörter je "
        "Kapitel als Diagramm, Status und Etiketten aus Scrivener. Rein deterministisch — "
        "kein Agent, nichts Geschätztes."
    ),
    execution_timeout=timedelta(hours=2),
)
class BuchUebersichtWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> wf_mistral.ChatAssistantWorkflowOutput:
        werke = await liste_werke()
        if not werke:
            return wf_mistral.ChatAssistantWorkflowOutput(
                content=[wf_mistral.TextOutput(text="Kein Werk in `shared/buch/` gefunden.")],
                isError=True,
            )
        if len(werke) == 1:
            werk = werke[0]["slug"]
        else:
            gewaehlt = await self.wait_for_input(
                _werkwahl([(w["slug"], w["titel"]) for w in werke]),
                label="Werk",
                timeout=timedelta(hours=4),
            )
            werk = gewaehlt.werk

        katalog = await liste_abschnitte(werk)
        if not katalog["abschnitte"]:
            return wf_mistral.ChatAssistantWorkflowOutput(
                content=[wf_mistral.TextOutput(text=f"In {werk!r} steht noch kein Text.")],
                isError=True,
            )

        inhalt: list = [
            wf_mistral.ResourceOutput(
                resource=wf_mistral.UIComponentResource(
                    component=Column(
                        gap="lg",
                        children=kennzahlen_karten(katalog) + wo_rangehen(katalog),
                    )
                )
            )
        ]

        fehlt = _fehlende_kapitel(katalog)
        if fehlt:
            inhalt.append(
                wf_mistral.ResourceOutput(
                    resource=wf_mistral.UIComponentResource(
                        component=Alert(
                            variant="warning",
                            title="Im Plan, aber nicht im Binder",
                            children=", ".join(fehlt),
                        )
                    )
                )
            )

        inhalt.append(
            wf_mistral.ResourceOutput(
                resource=wf_mistral.CanvasResource(
                    uri=f"file://canvas/uebersicht/{werk}",
                    readonly=True,
                    canvas=wf_mistral.CanvasPayload(
                        type="text/markdown",
                        title=f"{katalog['titel']} — Gliederung",
                        content=_gliederung(katalog),
                    ),
                )
            )
        )
        return wf_mistral.ChatAssistantWorkflowOutput(
            content=inhalt,
            structuredContent={
                "werk": werk,
                "woerter": sum(a["woerter"] for a in katalog["abschnitte"]),
                "abschnitte": len(katalog["abschnitte"]),
                "fehlende_kapitel": fehlt,
            },
        )
