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

REPO = Path(__file__).resolve().parents[3]


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
    # Eine Kennzahlen-Zeile, die jede Frage nach Umfang direkt beantwortet.
    #
    # Ohne sie zählt ein Modell Überschriften — und kommt auf 57 statt 48, weil
    # Kapitel (##), Untergruppen (###) und Abschnitte (####) alle Überschriften
    # sind und es sie addiert. Die Zahlen hier stehen im Text, sind also nicht zu
    # verwechseln und nicht zu erraten.
    mit_text = [a for a in m.abschnitte if a.hat_text]
    gruppen = {tuple(a.pfad[:2]) for a in mit_text if len(a.pfad) > 1}
    zeilen = [
        f"# {werk['titel']}",
        "",
        f"*{werk['untertitel']}* — {werk['autor']}",
        "",
        "## Umfang",
        "",
        f"- **{len(mit_text)} Abschnitte** mit Text (die Ebene, auf der geschrieben wird)",
        f"- **{len(m.kapitel)} Kapitel**: {' · '.join(m.kapitel)}",
        f"- {len(gruppen)} Untergruppen innerhalb der Kapitel",
        f"- **{m.woerter:,} Wörter**".replace(",", "."),
        f"- Stand: {date.today().isoformat()}",
        "",
        "> Kapitel, Untergruppen und Abschnitte sind DREI verschiedene Ebenen. "
        "Wer nach der Zahl der Abschnitte gefragt wird, nennt die erste Zahl — "
        "nicht die Summe der Überschriften in diesem Dokument.",
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



def kennzahlen_markdown(m, werk: dict, slug: str) -> str:
    """Alles, was `buch-uebersicht` rechnet — als Dokument für die Bibliothek.

    Der Grund, warum es diese Datei gibt: Ohne sie zählt ein Modell die
    Überschriften in ``manuskript.md`` und kommt auf 57 statt 48, weil Kapitel,
    Untergruppen und Abschnitte alle Überschriften sind. Zahlen, die im Text
    stehen, kann man nicht falsch zählen.

    Erwogen und verworfen wurde dafür ein MCP-Tool. Es hätte dasselbe geliefert,
    aber einen KV-Speicher, ein Deployment und eine zweite Veralterungsspur
    gebraucht — und wäre genauso ein Schnappschuss gewesen wie diese Datei, die
    derselbe Sync schreibt wie alle anderen. Für den Livestand ist ohnehin
    ``buch-uebersicht`` zuständig: Der Worker läuft dort, wo die Datei liegt.
    """
    mit_text = [a for a in m.abschnitte if a.hat_text]
    leer = [a for a in m.abschnitte if not a.hat_text and not a.ist_ordner]
    gesamt = sum(a.woerter for a in mit_text)
    mittel = gesamt / max(len(mit_text), 1)

    stand: dict[str, int] = {}
    etiketten: dict[str, int] = {}
    for a in mit_text:
        stand[a.status or "—"] = stand.get(a.status or "—", 0) + 1
        if a.etikett and a.etikett != "Kein Etikett":
            etiketten[a.etikett] = etiketten.get(a.etikett, 0) + 1
    ueber_roh = sum(n for st, n in stand.items() if st not in ("Rohfassung", "—"))

    z = [
        f"# {werk['titel']} — Kennzahlen",
        "",
        f"Stand: {date.today().isoformat()}. Erzeugt von `make buch-sync`, direkt aus dem "
        "Scrivener-Binder gezählt.",
        "",
        "> **Diese Zahlen sind maßgeblich.** Wer nach Umfang gefragt wird, nimmt sie von hier "
        "und zählt keine Überschriften in `manuskript.md` — Kapitel, Untergruppen und "
        "Abschnitte sind drei Ebenen und stehen dort alle als Überschrift.",
        "",
        "## Auf einen Blick",
        "",
        f"- **{len(mit_text)} Abschnitte mit Text** — die Ebene, auf der geschrieben wird",
        f"- **{len(m.kapitel)} Kapitel**",
        f"- **{gesamt:,} Wörter**".replace(",", "."),
        f"- {round(mittel)} Wörter je Abschnitt im Mittel",
        f"- {ueber_roh} von {len(mit_text)} Abschnitten sind über die Rohfassung hinaus",
    ]
    if leer:
        z.append(f"- {len(leer)} angelegte Abschnitte ohne einen Satz")
    z += ["", "## Kapitel", "", "| # | Kapitel | Abschnitte | Wörter | Anteil |", "|---:|---|---:|---:|---:|"]
    for i, kapitel in enumerate(m.kapitel, start=1):
        ab = [a for a in mit_text if a.kapitel == kapitel]
        w = sum(a.woerter for a in ab)
        z.append(f"| {i} | {kapitel} | {len(ab)} | {w:,} | {w / max(gesamt, 1):.0%} |".replace(",", "."))
    z += ["", "## Stand der Abschnitte", "", "| Status | Abschnitte |", "|---|---:|"]
    for st, n in sorted(stand.items(), key=lambda x: -x[1]):
        z.append(f"| {st} | {n} |")
    if etiketten:
        z += ["", "## Etiketten", "",
              f"{len(mit_text) - sum(etiketten.values())} von {len(mit_text)} Abschnitten "
              "tragen kein Etikett.", "", "| Etikett | Abschnitte |", "|---|---:|"]
        for e, n in sorted(etiketten.items(), key=lambda x: -x[1]):
            z.append(f"| {e} | {n} |")

    duenn = sorted((a for a in mit_text if (a.status or "Rohfassung") == "Rohfassung"
                    and a.woerter < mittel * 0.6), key=lambda a: a.woerter)[:8]
    if duenn:
        z += ["", "## Dünn geblieben", "",
              f"Rohfassung, deutlich unter dem Schnitt von {round(mittel)} Wörtern:", ""]
        z += [f"- **{a.titel}** · {a.woerter} Wörter · {a.kapitel}" for a in duenn]
    if leer:
        z += ["", "## Noch kein Satz", ""]
        z += [f"- **{a.titel}** · {a.kapitel or '—'}" for a in leer[:12]]

    z += ["", "## Alle Abschnitte", ""]
    letztes = None
    for a in mit_text:
        if a.kapitel != letztes:
            letztes = a.kapitel
            z += ["", f"### {a.kapitel}", "", "| Abschnitt | Etikett | Status | Wörter |",
                  "|---|---|---|---:|"]
        etikett = (a.etikett or "—").replace("Kein Etikett", "—")
        z.append(f"| {a.titel} | {etikett} | {a.status or '—'} | {a.woerter} |")
    return "\n".join(z) + "\n"


def rubrik_markdown(werk: dict) -> str:
    """Prüfsteine, Erzählregeln und die Rubrik je Kapitel — der Maßstab des Autors.

    Steht sonst nur in ``shared/buch/<slug>.json`` und war damit für jedes
    Gespräch unsichtbar. Es ist aber genau das, woran sich ein Kapitel messen
    lassen soll.
    """
    ps = werk.get("pruefsteine") or {}
    er = werk.get("erzaehlregeln") or {}
    z = [
        f"# {werk['titel']} — Maßstab",
        "",
        f"Stand: {date.today().isoformat()}. Erzeugt aus der Werk-Konfiguration.",
        "",
        "> Das hier ist der Maßstab des Autors, nicht allgemeine Schreiblehre. Wo ein Kapitel "
        "ihn verfehlt, ist das ein Befund — auch wenn es für sich genommen gut geschrieben ist.",
        "",
    ]
    if ps:
        z += ["## Die zwei Fragen an jedes Kapitel", ""]
        for k in ("erste_frage", "zweite_frage"):
            f = ps.get(k) or {}
            if not f.get("regel"):
                continue
            z.append(f"**{f['regel']}**")
            if f.get("erlaeuterung"):
                z += ["", f["erlaeuterung"]]
            if f.get("belegfall"):
                z += ["", f"*{f['belegfall']}*"]
            z.append("")
    if er:
        z += ["## Erzählregeln", ""]
        z += [f"- **{k.replace('_', ' ').capitalize()}:** {v}" for k, v in er.items()
              if isinstance(v, str) and not k.startswith("_")]
        z.append("")

    kapitel = [k for k in (werk.get("kapitel") or []) if isinstance(k, dict)]
    if kapitel:
        z += ["## Je Kapitel", ""]
        for k in kapitel:
            z.append(f"### {k.get('position', '')} {k['titel']}".strip())
            if k.get("untertitel"):
                z += ["", f"*{k['untertitel']}*"]
            for feld, titel in (("beweist", "Beweist"), ("muss_tragen", "Muss tragen"),
                                ("muss_nicht_tragen", "Muss NICHT tragen"),
                                ("offene_arbeit", "Offene Arbeit")):
                werte = k.get(feld) or []
                if werte:
                    z += ["", f"**{titel}**", ""] + [f"- {w}" for w in werte]
            merkmale = [f"{n}: {k[f]}" for f, n in
                        (("register", "Register"), ("zeit", "Zeit"), ("an_bord", "An Bord"),
                         ("strecke", "Strecke")) if k.get(f)]
            if k.get("historie_budget") is not None:
                merkmale.append(f"Historie-Budget: {k['historie_budget']}")
            if merkmale:
                z += ["", " · ".join(merkmale)]
            z.append("")
    return "\n".join(z) + "\n"


def kapitel_markdown(m: Manuskript, kapitel: str) -> str:
    konf = c.kapitel_nach_titel(m.slug, kapitel) or {}
    zeilen = [f"# {kapitel}", ""]
    if konf.get("untertitel"):
        zeilen += [f"*{konf['untertitel']}*", ""]
    for a in m.in_kapitel(kapitel):
        if a.hat_text:
            zeilen += [f"## {a.titel}", "", a.text, ""]
    return "\n".join(zeilen)


def kontext_markdown(werk: dict) -> str:
    """Prüfsteine, Erzählregeln und Kapitelgerüst als Text.

    Wird in Prompts und Skills eingebettet (siehe prompts/sync.py). Bewusst als
    generierte Datei neben dem Stimmprofil: Sie enthält Werkstrategie und ist
    deshalb gitignored, während der Prompt selbst im Repo bleiben kann.
    """
    z = [f"## Die Prüfsteine von „{werk['titel']}“", ""]
    for schluessel, block in (werk.get("pruefsteine") or {}).items():
        if schluessel.startswith("_") or not isinstance(block, dict):
            continue
        z.append(f"**{block.get('regel', schluessel)}**")
        for feld in ("erlaeuterung", "messlatte", "belegfall"):
            if block.get(feld):
                z.append(f"- {block[feld]}")
        z.append("")
    if werk.get("erzaehlregeln"):
        z += ["## Erzählregeln", ""]
        z += [f"- **{k}:** {v}" for k, v in werk["erzaehlregeln"].items() if not k.startswith("_")]
        z.append("")
    kapitel = [k for k in werk.get("kapitel", []) if k.get("muss_tragen") or k.get("beweist")]
    if kapitel:
        z += ["## Was die Kapitel leisten müssen", ""]
        for k in kapitel:
            z.append(f"### {k['titel']}" + (f" — {k['untertitel']}" if k.get("untertitel") else ""))
            for feld, titel in (("beweist", "Beweist"), ("muss_tragen", "Muss tragen"),
                                ("muss_nicht_tragen", "Muss nicht tragen"),
                                ("offene_arbeit", "Offene Arbeit")):
                if k.get(feld):
                    z.append(f"- *{titel}:* " + "; ".join(k[feld]))
            z.append("")
    return "\n".join(z).strip()


def in_library(dateien: list[Path], werk: dict) -> str:
    """Lädt Manuskript und Kontextdokumente in die Mistral Library des Werks.

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

    namen = {d.name for d in dateien}
    # Frühere Fassungen entfernen, damit die Library nie zwei Stände enthält.
    for doc in client.beta.libraries.documents.list(library_id=lib_id).data:
        if doc.name in namen:
            client.beta.libraries.documents.delete(library_id=lib_id, document_id=doc.id)

    geladen = []
    for datei in dateien:
        with datei.open("rb") as fh:
            client.beta.libraries.documents.upload(library_id=lib_id, file={
                "file_name": datei.name, "content": fh,
            })
        geladen.append(datei.name)
    return f"{lib_id}: " + ", ".join(geladen)


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

    # Zwei Begleitdokumente für die Bibliothek: die Zahlen und der Maßstab.
    # Beide gehen mit `--library` hoch, weil sie im Export-Ordner liegen.
    kennzahlen_pfad = export / "kennzahlen.md"
    kennzahlen_pfad.write_text(kennzahlen_markdown(m, werk, args.werk), encoding="utf-8")
    rubrik_pfad = export / "rubrik.md"
    rubrik_pfad.write_text(rubrik_markdown(werk), encoding="utf-8")

    # Werkkontext für Prompts/Skills — liegt bei den übrigen shared-Dateien,
    # ist aber gitignored (Werkstrategie gehört nicht ins öffentliche Repo).
    kontext = REPO / "shared" / "buch" / f"{args.werk}-kontext.md"
    kontext.write_text(kontext_markdown(werk), encoding="utf-8")

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
    print(f"  → {kennzahlen_pfad}")
    print(f"  → {rubrik_pfad}")
    print(f"  → {kontext.relative_to(REPO)}")

    if args.markdown:
        kap_dir = export / "kapitel"
        kap_dir.mkdir(exist_ok=True)
        for i, kapitel in enumerate(m.kapitel, start=1):
            (kap_dir / f"{i:02d}-{slugify(kapitel)}.md").write_text(
                kapitel_markdown(m, kapitel), encoding="utf-8"
            )
        print(f"  → {kap_dir}/ ({len(m.kapitel)} Kapitel)")

    if args.library:
        # Neben dem Manuskript alles, was in `kontext/` als Markdown liegt:
        # Exposé, Kapitelplan, was noch kommt. Eine Konvention statt einer Liste
        # in der Config — wer ein Dokument dazulegt, muss nichts eintragen.
        kontext_ordner = c.werk_pfad(werk["slug"], "kontext")
        dateien = [md_pfad, kennzahlen_pfad, rubrik_pfad]
        if kontext_ordner.is_dir():
            dateien += sorted(kontext_ordner.glob("*.md"))
        print(f"  → Library: {in_library(dateien, werk)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
