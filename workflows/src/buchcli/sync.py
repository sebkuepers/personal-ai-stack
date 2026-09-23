"""Scrivener → kanonischer Export (und optional in die Mistral Library).

    python -m buchcli.sync --werk immer-wieder-ruegen [--library] [--markdown]

Der Export wird bei **jedem** Lauf neu gebaut und nie von Hand gepflegt. Der
Grund steht als Mahnmal im Projekt: der frühere Handexport
(``_export_kapitel.json``) kannte drei Kapitel, während der Binder längst vier
hatte — zwei Tage Arbeit waren für jede Analyse unsichtbar.

Erzeugt in ``<werk>/export/``:
  manuskript.json      kanonisch, mit UUID, Pfad und sha256 je Absatz
  manuskript.md        ein Dokument für die Library
  kapitel/<n>-<slug>.md  je Kapitel, zum Lesen und Diffen
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

from workflows.buch import config as c
from workflows.buch.scrivener import Manuskript, lies_binder


def slugify(text: str) -> str:
    """Titel → Dateinamen-Slug nach der Konvention des Repos.

    Umlaute werden transliteriert (ä→ae …), alles andere auf ASCII reduziert.
    """
    ersetzungen = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}
    text = text.lower()
    for k, v in ersetzungen.items():
        text = text.replace(k, v)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text)).strip("-")


def als_markdown(m: Manuskript, werk: dict) -> str:
    """Das ganze Manuskript als ein Dokument — die Form, die in die Library geht."""
    zeilen = [
        f"# {werk['titel']}",
        "",
        f"*{werk['untertitel']}* — {werk['autor']}",
        "",
        f"Stand: {date.today().isoformat()} · {len(m.kapitel)} Kapitel · {m.woerter:,} Wörter".replace(
            ",", "."
        ),
        "",
    ]
    for kapitel in m.kapitel:
        konf = c.kapitel_nach_titel(m.slug, kapitel) or {}
        zeilen += ["", f"## {kapitel}", ""]
        if konf.get("untertitel"):
            zeilen += [f"*{konf['untertitel']}*", ""]
        letzter_pfad: list[str] = []
        for a in m.in_kapitel(kapitel):
            if not a.hat_text:
                continue
            gruppe = a.pfad[1:]
            if gruppe and gruppe != letzter_pfad:
                zeilen += [f"### {' / '.join(gruppe)}", ""]
                letzter_pfad = gruppe
            zeilen += [f"#### {a.titel}", ""]
            if a.synopsis:
                zeilen += [f"> **Absicht:** {a.synopsis}", ""]
            zeilen += [a.text, ""]
    return "\n".join(zeilen)


def kapitel_markdown(m: Manuskript, kapitel: str) -> str:
    konf = c.kapitel_nach_titel(m.slug, kapitel) or {}
    zeilen = [f"# {kapitel}", ""]
    if konf.get("untertitel"):
        zeilen += [f"*{konf['untertitel']}*", ""]
    for a in m.in_kapitel(kapitel):
        if a.hat_text:
            zeilen += [f"## {a.titel}", "", a.text, ""]
    return "\n".join(zeilen)


def in_library(md: Path, werk: dict) -> str:
    """Lädt das Manuskript in die Mistral Library des Werks.

    Legt die Library an, falls in der Werk-Konfiguration noch keine ID steht; die
    ID muss danach von Hand in ``shared/buch/<slug>.json`` eingetragen werden
    (bewusst kein Selbstschreiben in die Quelle der Wahrheit).
    """
    from dotenv import load_dotenv
    from mistralai.client import Mistral

    load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=False)
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])

    lib_id = werk["mistral"].get("library_id")
    if not lib_id:
        lib = client.beta.libraries.create(
            name=werk["mistral"]["library_name"],
            description=f"Manuskriptstand von „{werk['titel']}“ — automatisch aus Scrivener.",
        )
        lib_id = lib.id
        print(f"  Library angelegt: {lib_id}")
        print(f"  → in shared/buch/{werk['slug']}.json unter mistral.library_id eintragen!")

    # Frühere Fassungen entfernen, damit die Library nie zwei Stände enthält.
    for doc in client.beta.libraries.documents.list(library_id=lib_id).data:
        if doc.name == md.name:
            client.beta.libraries.documents.delete(library_id=lib_id, document_id=doc.id)

    with md.open("rb") as fh:
        doc = client.beta.libraries.documents.upload(library_id=lib_id, file={
            "file_name": md.name, "content": fh,
        })
    return f"{lib_id} / {doc.id}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Scrivener-Projekt exportieren.")
    p.add_argument("--werk", default="immer-wieder-ruegen", help="Slug des Werks")
    p.add_argument("--test", action="store_true", help="die Testkopie lesen statt des Originals")
    p.add_argument("--markdown", action="store_true", help="zusätzlich Kapitel-Markdown schreiben")
    p.add_argument("--library", action="store_true", help="in die Mistral Library laden")
    args = p.parse_args(argv)

    werk = c.lade_werk(args.werk)
    paket = c.scrivener_pfad(args.werk, test=args.test)
    if not paket.is_dir():
        print(f"Scrivener-Projekt nicht gefunden: {paket}", file=sys.stderr)
        return 1

    # Nicht jedes Projekt legt die Kapitel direkt unter den Entwurf, und nicht in
    # jedem Entwurf steht ausschließlich Manuskript — siehe lies_binder().
    struktur = werk.get("struktur") or {}
    m = lies_binder(
        paket,
        args.werk,
        wurzel=struktur.get("wurzel"),
        kapitel_ebene=struktur.get("kapitel_ebene", 0),
    )
    export = werk["pfade"]["export"]
    export.mkdir(parents=True, exist_ok=True)

    ziel = export / "manuskript.json"
    ziel.write_text(
        json.dumps(m.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    md_pfad = export / "manuskript.md"
    md_pfad.write_text(als_markdown(m, werk), encoding="utf-8")

    print(f"{werk['titel']} — {paket.name}")
    for kapitel in m.kapitel:
        ab = [a for a in m.in_kapitel(kapitel) if a.hat_text]
        konf = c.kapitel_nach_titel(args.werk, kapitel) or {}
        offen = len(konf.get("offene_arbeit") or [])
        hinweis = f"  ({offen} offene Punkte)" if offen else ""
        print(f"  {kapitel:22} {len(ab):3} Abschnitte  {sum(a.woerter for a in ab):6} Wörter{hinweis}")
    print(f"  {'GESAMT':22} {sum(1 for a in m.abschnitte if a.hat_text):3} Abschnitte  {m.woerter:6} Wörter")
    print(f"\n  → {ziel}")
    print(f"  → {md_pfad}")

    if args.markdown:
        kap_dir = export / "kapitel"
        kap_dir.mkdir(exist_ok=True)
        for i, kapitel in enumerate(m.kapitel, start=1):
            (kap_dir / f"{i:02d}-{slugify(kapitel)}.md").write_text(
                kapitel_markdown(m, kapitel), encoding="utf-8"
            )
        print(f"  → {kap_dir}/ ({len(m.kapitel)} Kapitel)")

    if args.library:
        print(f"  → Library: {in_library(md_pfad, werk)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
