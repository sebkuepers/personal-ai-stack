"""Scrivener → canonical export (and optionally into the Mistral Library).

    python -m bookcli.sync --work immer-wieder-ruegen [--library] [--markdown]

The export is rebuilt on **every** run and never maintained by hand. The reason
stands as a monument in the project: the earlier hand-made export
(``_export_kapitel.json``) knew three chapters while the binder had long had
four — two days of work were invisible to every analysis.

Produced in ``<work>/export/``:
  manuskript.json        canonical, with UUID, path and sha256 per paragraph
  manuskript.md          one document for the library
  kennzahlen.md          the figures
  rubrik.md              the author's yardstick
  kapitel/<n>-<slug>.md  per chapter, for reading and diffing

The generated documents keep their German names and German content: they are
German documents about a German book, and the author's Vibe project refers to
them by these names.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

from workflows.book import config as c
from workflows.book.scrivener import Manuscript, read_binder

REPO = Path(__file__).resolve().parents[3]

# German headings for the narrative rules. Derived from the key name they would
# read "Publisher note" inside an otherwise German document the author reads —
# the keys are identifiers, the document is his.
NARRATIVE_LABELS = {
    "perspective": "Perspektive",
    "principle": "Prinzip",
    "frame": "Klammer",
    "history_dosage": "Historie-Dosierung",
    "publisher_note": "Verlagshinweis",
}


def slugify(text: str) -> str:
    """Title → file-name slug, following the repo's convention.

    Umlauts are transliterated (ä→ae …), everything else reduced to ASCII.
    """
    replacements = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    text = text.lower()
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text)).strip("-")


def as_markdown(m: Manuscript, work: dict) -> str:
    """The whole manuscript as one document — the form that goes into the library."""
    # One figures line that answers any question about size directly.
    #
    # Without it a model counts headings — and arrives at 57 instead of 48,
    # because chapters (##), sub-groups (###) and sections (####) are all
    # headings and it adds them up. The numbers here stand in the text, so they
    # cannot be confused and cannot be guessed.
    with_text = [s for s in m.sections if s.has_text]
    groups = {tuple(s.path[:2]) for s in with_text if len(s.path) > 1}
    lines = [
        f"# {work['title']}",
        "",
        f"*{work['subtitle']}* — {work['author']}",
        "",
        "## Umfang",
        "",
        f"- **{len(with_text)} Abschnitte** mit Text (die Ebene, auf der geschrieben wird)",
        f"- **{len(m.chapters)} Kapitel**: {' · '.join(m.chapters)}",
        f"- {len(groups)} Untergruppen innerhalb der Kapitel",
        f"- **{m.words:,} Wörter**".replace(",", "."),
        f"- Stand: {date.today().isoformat()}",
        "",
        "> Kapitel, Untergruppen und Abschnitte sind DREI verschiedene Ebenen. "
        "Wer nach der Zahl der Abschnitte gefragt wird, nennt die erste Zahl — "
        "nicht die Summe der Überschriften in diesem Dokument.",
        "",
    ]
    for chapter in m.chapters:
        conf = c.chapter_by_title(m.slug, chapter) or {}
        lines += ["", f"## {chapter}", ""]
        if conf.get("subtitle"):
            lines += [f"*{conf['subtitle']}*", ""]
        last_path: list[str] = []
        for s in m.in_chapter(chapter):
            if not s.has_text:
                continue
            group = s.path[1:]
            if group and group != last_path:
                lines += [f"### {' / '.join(group)}", ""]
                last_path = group
            lines += [f"#### {s.title}", ""]
            if s.synopsis:
                lines += [f"> **Absicht:** {s.synopsis}", ""]
            lines += [s.text, ""]
    return "\n".join(lines)


def metrics_markdown(m: Manuscript, work: dict) -> str:
    """Everything `book-overview` computes — as a document for the library.

    The reason this file exists: without it a model counts the headings in
    ``manuskript.md`` and arrives at 57 instead of 48, because chapters,
    sub-groups and sections are all headings. Numbers that stand in the text
    cannot be miscounted.

    An MCP tool was considered and rejected for this. It would have delivered
    the same thing but needed a KV store, a deployment and a second staleness
    trail — and would have been just as much a snapshot as this file, which the
    same sync writes as all the others. For the live state ``book-overview`` is
    responsible anyway: the worker runs where the file lives.
    """
    with_text = [s for s in m.sections if s.has_text]
    empty = [s for s in m.sections if not s.has_text and not s.is_folder]
    total = sum(s.words for s in with_text)
    mean = total / max(len(with_text), 1)

    state: dict[str, int] = {}
    labels: dict[str, int] = {}
    for s in with_text:
        state[s.status or "—"] = state.get(s.status or "—", 0) + 1
        if s.label and s.label != "Kein Etikett":
            labels[s.label] = labels.get(s.label, 0) + 1
    beyond_draft = sum(n for st, n in state.items() if st not in ("Rohfassung", "—"))

    z = [
        f"# {work['title']} — Kennzahlen",
        "",
        f"Stand: {date.today().isoformat()}. Erzeugt von `make book-sync`, direkt aus dem "
        "Scrivener-Binder gezählt.",
        "",
        "> **Diese Zahlen sind maßgeblich.** Wer nach Umfang gefragt wird, nimmt sie von hier "
        "und zählt keine Überschriften in `manuskript.md` — Kapitel, Untergruppen und "
        "Abschnitte sind drei Ebenen und stehen dort alle als Überschrift.",
        "",
        "## Auf einen Blick",
        "",
        f"- **{len(with_text)} Abschnitte mit Text** — die Ebene, auf der geschrieben wird",
        f"- **{len(m.chapters)} Kapitel**",
        f"- **{total:,} Wörter**".replace(",", "."),
        f"- {round(mean)} Wörter je Abschnitt im Mittel",
        f"- {beyond_draft} von {len(with_text)} Abschnitten sind über die Rohfassung hinaus",
    ]
    if empty:
        z.append(f"- {len(empty)} angelegte Abschnitte ohne einen Satz")
    z += ["", "## Kapitel", "", "| # | Kapitel | Abschnitte | Wörter | Anteil |",
          "|---:|---|---:|---:|---:|"]
    for i, chapter in enumerate(m.chapters, start=1):
        inside = [s for s in with_text if s.chapter == chapter]
        w = sum(s.words for s in inside)
        z.append(
            f"| {i} | {chapter} | {len(inside)} | {w:,} | {w / max(total, 1):.0%} |"
            .replace(",", ".")
        )
    z += ["", "## Stand der Abschnitte", "", "| Status | Abschnitte |", "|---|---:|"]
    for st, n in sorted(state.items(), key=lambda x: -x[1]):
        z.append(f"| {st} | {n} |")
    if labels:
        z += ["", "## Etiketten", "",
              f"{len(with_text) - sum(labels.values())} von {len(with_text)} Abschnitten "
              "tragen kein Etikett.", "", "| Etikett | Abschnitte |", "|---|---:|"]
        for label, n in sorted(labels.items(), key=lambda x: -x[1]):
            z.append(f"| {label} | {n} |")

    thin = sorted((s for s in with_text if (s.status or "Rohfassung") == "Rohfassung"
                   and s.words < mean * 0.6), key=lambda s: s.words)[:8]
    if thin:
        z += ["", "## Dünn geblieben", "",
              f"Rohfassung, deutlich unter dem Schnitt von {round(mean)} Wörtern:", ""]
        z += [f"- **{s.title}** · {s.words} Wörter · {s.chapter}" for s in thin]
    if empty:
        z += ["", "## Noch kein Satz", ""]
        z += [f"- **{s.title}** · {s.chapter or '—'}" for s in empty[:12]]

    z += ["", "## Alle Abschnitte", ""]
    previous = None
    for s in with_text:
        if s.chapter != previous:
            previous = s.chapter
            z += ["", f"### {s.chapter}", "", "| Abschnitt | Etikett | Status | Wörter |",
                  "|---|---|---|---:|"]
        label = (s.label or "—").replace("Kein Etikett", "—")
        z.append(f"| {s.title} | {label} | {s.status or '—'} | {s.words} |")
    return "\n".join(z) + "\n"


def rubric_markdown(work: dict) -> str:
    """Touchstones, narrative rules and the rubric per chapter — the author's yardstick.

    Otherwise this only sits in ``shared/book/<slug>.json`` and was therefore
    invisible to every conversation. But it is exactly what a chapter is meant
    to be measured against.
    """
    touchstones = work.get("touchstones") or {}
    narrative = work.get("narrative_rules") or {}
    z = [
        f"# {work['title']} — Maßstab",
        "",
        f"Stand: {date.today().isoformat()}. Erzeugt aus der Werk-Konfiguration.",
        "",
        "> Das hier ist der Maßstab des Autors, nicht allgemeine Schreiblehre. Wo ein Kapitel "
        "ihn verfehlt, ist das ein Befund — auch wenn es für sich genommen gut geschrieben ist.",
        "",
    ]
    if touchstones:
        z += ["## Die zwei Fragen an jedes Kapitel", ""]
        for key in ("first_question", "second_question"):
            q = touchstones.get(key) or {}
            if not q.get("rule"):
                continue
            z.append(f"**{q['rule']}**")
            if q.get("explanation"):
                z += ["", q["explanation"]]
            if q.get("precedent"):
                z += ["", f"*{q['precedent']}*"]
            z.append("")
    if narrative:
        z += ["## Erzählregeln", ""]
        z += [f"- **{NARRATIVE_LABELS.get(k, k)}:** {v}" for k, v in narrative.items()
              if isinstance(v, str) and not k.startswith("_")]
        z.append("")

    chapters = [k for k in (work.get("chapters") or []) if isinstance(k, dict)]
    if chapters:
        z += ["## Je Kapitel", ""]
        for k in chapters:
            z.append(f"### {k.get('position', '')} {k['title']}".strip())
            if k.get("subtitle"):
                z += ["", f"*{k['subtitle']}*"]
            for field, heading in (("proves", "Beweist"), ("must_carry", "Muss tragen"),
                                   ("need_not_carry", "Muss NICHT tragen"),
                                   ("open_work", "Offene Arbeit")):
                values = k.get(field) or []
                if values:
                    z += ["", f"**{heading}**", ""] + [f"- {v}" for v in values]
            traits = [f"{n}: {k[f]}" for f, n in
                      (("register", "Register"), ("season", "Zeit"), ("aboard", "An Bord"),
                       ("leg", "Strecke")) if k.get(f)]
            if k.get("history_budget") is not None:
                traits.append(f"Historie-Budget: {k['history_budget']}")
            if traits:
                z += ["", " · ".join(traits)]
            z.append("")
    return "\n".join(z) + "\n"


def chapter_markdown(m: Manuscript, chapter: str) -> str:
    conf = c.chapter_by_title(m.slug, chapter) or {}
    lines = [f"# {chapter}", ""]
    if conf.get("subtitle"):
        lines += [f"*{conf['subtitle']}*", ""]
    for s in m.in_chapter(chapter):
        if s.has_text:
            lines += [f"## {s.title}", "", s.text, ""]
    return "\n".join(lines)


def context_markdown(work: dict) -> str:
    """Touchstones, narrative rules and the chapter scaffold as text.

    Embedded into prompts and skills. Deliberately a generated file next to the
    voice profile: it contains the work's strategy and is therefore gitignored,
    while the prompt itself can stay in the repo.
    """
    z = [f"## Die Prüfsteine von „{work['title']}“", ""]
    for key, block in (work.get("touchstones") or {}).items():
        if key.startswith("_") or not isinstance(block, dict):
            continue
        z.append(f"**{block.get('rule', key)}**")
        for field in ("explanation", "benchmark", "precedent"):
            if block.get(field):
                z.append(f"- {block[field]}")
        z.append("")
    if work.get("narrative_rules"):
        z += ["## Erzählregeln", ""]
        z += [f"- **{NARRATIVE_LABELS.get(k, k)}:** {v}"
              for k, v in work["narrative_rules"].items() if not k.startswith("_")]
        z.append("")
    chapters = [k for k in work.get("chapters", []) if k.get("must_carry") or k.get("proves")]
    if chapters:
        z += ["## Was die Kapitel leisten müssen", ""]
        for k in chapters:
            z.append(f"### {k['title']}" + (f" — {k['subtitle']}" if k.get("subtitle") else ""))
            for field, heading in (("proves", "Beweist"), ("must_carry", "Muss tragen"),
                                   ("need_not_carry", "Muss nicht tragen"),
                                   ("open_work", "Offene Arbeit")):
                if k.get(field):
                    z.append(f"- *{heading}:* " + "; ".join(k[field]))
            z.append("")
    return "\n".join(z).strip()


def into_library(files: list[Path], work: dict) -> str:
    """Upload manuscript and context documents into the work's Mistral Library.

    Creates the library if the work configuration has no ID yet; that ID then
    has to be entered by hand into ``shared/book/<slug>.json`` (deliberately no
    self-writing into the source of truth).
    """
    from dotenv import load_dotenv
    from mistralai.client import Mistral

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    lib_id = work["mistral"].get("library_id")
    if not lib_id:
        lib = client.beta.libraries.create(
            name=work["mistral"]["library_name"],
            description=f"Manuskriptstand von „{work['title']}“ — automatisch aus Scrivener.",
        )
        lib_id = lib.id
        print(f"  Library angelegt: {lib_id}")
        print(f"  → in shared/book/{work['slug']}.json unter mistral.library_id eintragen!")

    names = {f.name for f in files}
    # Remove earlier versions, so the library never holds two states.
    for doc in client.beta.libraries.documents.list(library_id=lib_id).data:
        if doc.name in names:
            client.beta.libraries.documents.delete(library_id=lib_id, document_id=doc.id)

    uploaded = []
    for file in files:
        with file.open("rb") as fh:
            client.beta.libraries.documents.upload(library_id=lib_id, file={
                "file_name": file.name, "content": fh,
            })
        uploaded.append(file.name)
    return f"{lib_id}: " + ", ".join(uploaded)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scrivener-Projekt exportieren.")
    p.add_argument("--work", default="immer-wieder-ruegen", help="Slug des Werks")
    p.add_argument("--test", action="store_true", help="die Testkopie lesen statt des Originals")
    p.add_argument("--markdown", action="store_true", help="zusätzlich Kapitel-Markdown schreiben")
    p.add_argument("--library", action="store_true", help="in die Mistral Library laden")
    args = p.parse_args(argv)

    work = c.load_work(args.work)
    package = c.scrivener_path(args.work, test=args.test)
    if not package.is_dir():
        print(f"Scrivener-Projekt nicht gefunden: {package}", file=sys.stderr)
        return 1

    # Not every project puts the chapters directly under the draft, and not
    # every draft holds manuscript only — see read_binder().
    structure = work.get("structure") or {}
    m = read_binder(
        package,
        args.work,
        root=structure.get("root"),
        chapter_level=structure.get("chapter_level", 0),
    )
    export = work["paths"]["export"]
    export.mkdir(parents=True, exist_ok=True)

    target = export / "manuskript.json"
    target.write_text(
        json.dumps(m.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    md_path = export / "manuskript.md"
    md_path.write_text(as_markdown(m, work), encoding="utf-8")

    # Two companion documents for the library: the figures and the yardstick.
    # Both go up with `--library`, because they sit in the export folder.
    metrics_path = export / "kennzahlen.md"
    metrics_path.write_text(metrics_markdown(m, work), encoding="utf-8")
    rubric_path = export / "rubrik.md"
    rubric_path.write_text(rubric_markdown(work), encoding="utf-8")

    # Work context for prompts/skills — sits with the other shared files but is
    # gitignored (the work's strategy does not belong in the public repo).
    context = REPO / "shared" / "book" / f"{args.work}-context.md"
    context.write_text(context_markdown(work), encoding="utf-8")

    print(f"{work['title']} — {package.name}")
    for chapter in m.chapters:
        inside = [s for s in m.in_chapter(chapter) if s.has_text]
        conf = c.chapter_by_title(args.work, chapter) or {}
        open_work = len(conf.get("open_work") or [])
        hint = f"  ({open_work} offene Punkte)" if open_work else ""
        print(
            f"  {chapter:22} {len(inside):3} Abschnitte  "
            f"{sum(s.words for s in inside):6} Wörter{hint}"
        )
    print(
        f"  {'GESAMT':22} {sum(1 for s in m.sections if s.has_text):3} Abschnitte  "
        f"{m.words:6} Wörter"
    )
    print(f"\n  → {target}")
    print(f"  → {md_path}")
    print(f"  → {metrics_path}")
    print(f"  → {rubric_path}")
    print(f"  → {context.relative_to(REPO)}")

    if args.markdown:
        chapter_dir = export / "kapitel"
        chapter_dir.mkdir(exist_ok=True)
        for i, chapter in enumerate(m.chapters, start=1):
            (chapter_dir / f"{i:02d}-{slugify(chapter)}.md").write_text(
                chapter_markdown(m, chapter), encoding="utf-8"
            )
        print(f"  → {chapter_dir}/ ({len(m.chapters)} Kapitel)")

    if args.library:
        # Besides the manuscript, everything that lies in `kontext/` as
        # Markdown: exposé, chapter plan, whatever comes next. A convention
        # instead of a list in the config — adding a document requires no entry.
        context_dir = c.work_path(work["slug"], "context")
        files = [md_path, metrics_path, rubric_path]
        if context_dir.is_dir():
            files += sorted(context_dir.glob("*.md"))
        print(f"  → Library: {into_library(files, work)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
