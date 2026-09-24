"""How far along is the book? — structure, density and state at a glance.

Scrivener keeps a **label** for every section (what it is about: „Historische
Geschichten", „Beziehungen & Personen") and a **status** („Rohfassung",
„Ausgebaut", „Redigiert" …). The author maintains both anyway — it is the most
honest progress indicator in the whole project, because it comes from him and
not from a model.

This workflow computes nothing that a model would have to decide. It counts.
Everything here is deterministic; no agent is called. That is deliberate: a
progress display that can hallucinate is worse than none.

What it shows:

* a **canvas** with the complete outline — chapters, sections, words, status,
  label; empty outline nodes explicitly marked as such
* a **bar chart** of words per chapter — the density, and where it is missing
* a **pie chart** of the statuses — how much is really more than a first draft
* a **warning** when a chapter from the plan is still missing in the manuscript

The user-facing strings are German: the author reads them.

Start it by choosing the workflow in Le Chat, or
  make book-overview work=immer-wieder-ruegen
"""

from __future__ import annotations

from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.workflows import workflow

with workflow.unsafe.imports_passed_through():
    import mistralai.workflows.plugins.mistralai as wf_mistral
    from workflows.book.local import list_sections, list_works

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

# „Rohfassung" is the beginning, „Fertig" the end. Scrivener only stores the
# order as an ID, hence it is repeated here — for sorting the charts, not as a
# second source of truth.
STAGES = ["Rohfassung", "Ausgebaut", "Redigiert", "Korrigiert", "Letzter Entwurf", "Fertig"]


def _work_choice(works: list[tuple[str, str]]) -> type[wf_chat.FormInput]:
    class WorkChoice(wf_chat.FormInput):
        work: str = wf_chat.SingleChoice(
            options=works, description="Welches Buch?", prefilled_value=works[0][0]
        )

    return WorkChoice


def _by_chapter(sections: list[dict], empty: list[dict]) -> list[dict]:
    """Chapters in binder order, with their sections."""
    chapters: dict[str, dict] = {}
    for s in sections + empty:
        c = chapters.setdefault(
            s["chapter"], {"name": s["chapter"], "sections": [], "words": 0}
        )
        c["sections"].append(s)
        c["words"] += s.get("words", 0)
    return list(chapters.values())


def _outline(catalogue: dict) -> str:
    """The outline as a Markdown table per chapter — the same cut as the outliner."""
    lines = [f"# {catalogue['title']}"]
    if catalogue.get("subtitle"):
        lines.append(f"*{catalogue['subtitle']}*")
    total = sum(s["words"] for s in catalogue["sections"])
    lines += ["", f"{total:,} Wörter".replace(",", "."), ""]

    for c in _by_chapter(catalogue["sections"], catalogue.get("empty", [])):
        with_text = [s for s in c["sections"] if s.get("words")]
        lines += [
            f"## {c['name']}",
            "",
            f"{c['words']:,} Wörter · {len(with_text)} von {len(c['sections'])} "
            "Abschnitten geschrieben".replace(",", "."),
            "",
            # The same table as in the chat: one cut, not two. An empty node
            # shows „—" instead of „0" — it is a reserved slot, not a section
            # written empty.
            outliner(c["sections"]),
            "",
        ]
    return "\n".join(lines)


def metric_cards(catalogue: dict) -> list:
    """Key figures, density per chapter, distribution of states.

    Without a leading underscore, because ``book-editing`` shows them too —
    there, directly before the section choice. One does not pick a section from
    a list of 48 titles but because one knows where the book is thin.
    """
    sections = catalogue["sections"]
    chapters = _by_chapter(sections, catalogue.get("empty", []))
    total = sum(s["words"] for s in sections)
    longest = max(sections, key=lambda s: s["words"], default=None)

    state: dict[str, int] = {}
    for s in sections:
        state[s.get("status") or "—"] = state.get(s.get("status") or "—", 0) + 1
    labels: dict[str, int] = {}
    for s in sections:
        name = s.get("label") or "—"
        if name != "Kein Etikett":
            labels[name] = labels.get(name, 0) + 1

    beyond_draft = sum(n for st, n in state.items() if st not in ("Rohfassung", "—"))

    parts: list = [
        Row(
            gap="md",
            wrap=True,
            children=[
                Card(title=f"{total:,}".replace(",", "."), description="Wörter"),
                Card(title=str(len(sections)), description="Abschnitte mit Text"),
                Card(title=str(len(chapters)), description="Kapitel"),
                Card(
                    title=f"{beyond_draft}/{len(sections)}",
                    description="über Rohfassung hinaus",
                ),
                Card(
                    title=str(round(total / max(len(sections), 1))),
                    description="Wörter je Abschnitt im Mittel",
                ),
            ],
        ),
        Chart(
            variant="bar",
            title="Dichte — Wörter je Kapitel",
            data=[{"Kapitel": c["name"], "Wörter": c["words"]} for c in chapters],
            xAxis="Kapitel",
            yAxis="Wörter",
        ),
    ]

    if len(state) > 1:
        parts.append(
            PieChart(
                title="Stand der Abschnitte",
                data=[
                    {"name": st, "value": state[st]}
                    for st in STAGES + [x for x in state if x not in STAGES]
                    if st in state
                ],
            )
        )
    if labels:
        parts.append(
            PieChart(
                title="Etiketten — worum es geht",
                data=[{"name": n, "value": v} for n, v in sorted(labels.items())],
            )
        )
    if longest:
        parts.append(
            Row(
                gap="sm",
                wrap=True,
                children=[
                    Badge(children="längster Abschnitt", variant="default"),
                    Badge(
                        children=f"{longest['title']} · {longest['words']} Wörter",
                        variant="primary",
                    ),
                ],
            )
        )
    return parts


def where_to_start(catalogue: dict, *, how_many: int = 5) -> list:
    """The actual decision aid: where is the next hour worth spending?

    Key figures say how things stand. They do not say what to do. Hence three
    rankings — all counted, none estimated:

    * **thin** — sections still in first draft with strikingly little text. Not
      in absolute terms but against this book's average; what counts as short
      for this manuscript only this manuscript knows.
    * **stale** — untouched the longest, still in first draft.
    * **empty** — outline nodes without a single sentence.

    Deliberately a list rather than one single recommendation: which of the
    three questions is due right now is the author's call, not the statistics'.
    """
    sections = catalogue["sections"]
    if not sections:
        return []
    mean = sum(s["words"] for s in sections) / len(sections)
    draft = [s for s in sections if (s.get("status") or "Rohfassung") == "Rohfassung"]

    thin = sorted([s for s in draft if s["words"] < mean * 0.6], key=lambda s: s["words"])
    stale = sorted([s for s in draft if s.get("last_changed")], key=lambda s: s["last_changed"])
    # Real sections only, no chapter or group folders: those never have text of
    # their own and would simply be wrong as "still missing".
    empty = [s for s in catalogue.get("empty", []) if not s.get("is_folder")]

    def listing(entries: list[dict], line) -> str:  # noqa: ANN001
        return "\n".join(f"- {line(s)}" for s in entries[:how_many]) or "—"

    cards: list = []
    if thin:
        cards.append(
            Card(
                title="Dünn geblieben",
                description=f"Rohfassung, deutlich unter dem Schnitt von {round(mean)} Wörtern",
                children=listing(
                    thin, lambda s: f"**{s['title']}** · {s['words']} Wörter · {s['chapter']}"
                ),
            )
        )
    if stale:
        cards.append(
            Card(
                title="Am längsten nicht angefasst",
                description="noch Rohfassung",
                children=listing(
                    stale,
                    lambda s: f"**{s['title']}** · {_day(s['last_changed'])} · {s['words']} Wörter",
                ),
            )
        )
    if empty:
        cards.append(
            Card(
                title="Noch kein Satz",
                description=f"{len(empty)} Gliederungsknoten ohne Text",
                children=listing(empty, lambda s: f"**{s['title']}** · {s['chapter']}"),
            )
        )
    return [Row(gap="md", wrap=True, children=cards)] if cards else []


def _day(iso: str) -> str:
    """ISO date as DD.MM. — German order, year omitted."""
    if not iso or len(iso) < 10:
        return "—"
    return f"{iso[8:10]}.{iso[5:7]}."


def outliner(sections: list[dict], *, with_chapters: bool = False) -> str:
    """A table cut like the Scrivener outliner.

    The same columns in the same order the author scans there anyway: title,
    label, status, words, last changed. The point is not completeness but
    **recognisability** — one should not have to learn twice where to look.

    ``with_chapters`` **groups** by chapter instead of appending a chapter
    column. A flat list across all 48 sections repeated „Voll zur Oma"
    twenty-four times — room spent on information the outline already conveys.
    Scrivener indents; this does the same with intermediate headings.
    """
    if with_chapters:
        # Group by the FULL path, not only by chapter: Scrivener knows
        # sub-groups (chapter / scene block / section), and when searching those
        # orient just as much as the chapter itself. Headings instead of
        # indentation, because Markdown has no indentation inside tables.
        groups: dict[tuple[str, ...], list[dict]] = {}
        for s in sections:
            groups.setdefault(tuple(s.get("path") or [s.get("chapter") or "—"]), []).append(s)

        parts: list[str] = []
        previous: tuple[str, ...] = ()
        for path, entries in groups.items():
            # Only emit the levels that changed against the previous group —
            # otherwise the chapter stands above every sub-group.
            for depth, name in enumerate(path):
                if depth < len(previous) and previous[depth] == name:
                    continue
                parts.append(f"{'#' * (3 + depth)} {name}")
            previous = path
            words = sum(x.get("words", 0) for x in entries)
            parts += [
                f"{words:,} Wörter · {len(entries)} Abschnitte".replace(",", "."),
                "",
                outliner(entries),
                "",
            ]
        return "\n".join(parts)

    head = ["Abschnitt", "Etikett", "Status", "Wörter", "zuletzt"]
    lines = [
        "| " + " | ".join(head) + " |",
        "|---|---|---|---:|---|",
    ]
    for s in sections:
        w = s.get("words", 0)
        lines.append(
            "| "
            + " | ".join(
                [
                    s["title"],
                    (s.get("label") or "—").replace("Kein Etikett", "—"),
                    s.get("status") or "—",
                    str(w) if w else "—",
                    _day(s.get("last_changed", "")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def button_label(s: dict) -> str:
    """A section as a line in the choice field — short."""
    # Title and size only. Status and date are in the table above; repeating
    # them here makes the line long and the choice no better.
    return f"{s['title']} · {s['words']} W" if s.get("words") else s["title"]


def _missing_chapters(catalogue: dict) -> list[str]:
    """Chapters that are in the plan but missing from the binder.

    The plan lives in ``shared/book/<slug>.json``, the manuscript in Scrivener.
    That the two drift apart is otherwise only noticed at PDF typesetting time.
    """
    present = {s["chapter"] for s in catalogue["sections"]} | {
        s["chapter"] for s in catalogue.get("empty", [])
    }
    return [c for c in catalogue.get("chapters_planned", []) if c and c not in present]


@workflows.workflow.define(
    name="book-overview",
    workflow_display_name="Book · Overview",
    workflow_description=(
        "Zeigt Struktur, Dichte und Stand eines Buchs: Gliederung als Canvas, Wörter je "
        "Kapitel als Diagramm, Status und Etiketten aus Scrivener. Rein deterministisch — "
        "kein Agent, nichts Geschätztes."
    ),
    execution_timeout=timedelta(hours=2),
)
class BookOverviewWorkflow(workflows.InteractiveWorkflow):
    @workflows.workflow.entrypoint
    async def run(self) -> wf_mistral.ChatAssistantWorkflowOutput:
        works = await list_works()
        if not works:
            return wf_mistral.ChatAssistantWorkflowOutput(
                content=[wf_mistral.TextOutput(text="Kein Werk in `shared/book/` gefunden.")],
                isError=True,
            )
        if len(works) == 1:
            work = works[0]["slug"]
        else:
            chosen = await self.wait_for_input(
                _work_choice([(w["slug"], w["title"]) for w in works]),
                label="Werk",
                timeout=timedelta(hours=4),
            )
            work = chosen.work

        catalogue = await list_sections(work)
        if not catalogue["sections"]:
            return wf_mistral.ChatAssistantWorkflowOutput(
                content=[wf_mistral.TextOutput(text=f"In {work!r} steht noch kein Text.")],
                isError=True,
            )

        content: list = [
            wf_mistral.ResourceOutput(
                resource=wf_mistral.UIComponentResource(
                    component=Column(
                        gap="lg",
                        children=metric_cards(catalogue) + where_to_start(catalogue),
                    )
                )
            )
        ]

        missing = _missing_chapters(catalogue)
        if missing:
            content.append(
                wf_mistral.ResourceOutput(
                    resource=wf_mistral.UIComponentResource(
                        component=Alert(
                            variant="warning",
                            title="Im Plan, aber nicht im Binder",
                            children=", ".join(missing),
                        )
                    )
                )
            )

        content.append(
            wf_mistral.ResourceOutput(
                resource=wf_mistral.CanvasResource(
                    uri=f"file://canvas/overview/{work}",
                    readonly=True,
                    canvas=wf_mistral.CanvasPayload(
                        type="text/markdown",
                        title=f"{catalogue['title']} — Gliederung",
                        content=_outline(catalogue),
                    ),
                )
            )
        )
        return wf_mistral.ChatAssistantWorkflowOutput(
            content=content,
            structuredContent={
                "work": work,
                "words": sum(s["words"] for s in catalogue["sections"]),
                "sections": len(catalogue["sections"]),
                "missing_chapters": missing,
            },
        )
