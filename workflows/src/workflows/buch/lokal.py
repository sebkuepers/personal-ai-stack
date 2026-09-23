"""Aktivitäten, die die lokale Platte anfassen.

Der ursprüngliche Entwurf verbot das kategorisch: Workflows sollten Text rein /
Text raus sein, weil der Worker im Cloudflare-Container lief und ``~/Werk/…``
dort nicht existiert. Der Worker läuft jetzt lokal, also fällt der Grund weg —
und mit ihm eine unnötige Einschränkung: Ein conversational Workflow, der die
Kapitel selbst auflisten kann, lässt sich aus Le Chat heraus ohne einen einzigen
Parameter starten.

Was bleibt, ist die Trennung, auf die es wirklich ankommt: **I/O steht in
Aktivitäten, nie im Workflow-Körper.** Der Workflow wird bei einer Wiederholung
erneut abgespielt; eine Datei, die sich zwischendurch geändert hat, würde ihn
dabei aus der Bahn werfen. Eine Aktivität liest genau einmal, und ihr Ergebnis
steht danach in der Ereignishistorie.

Geschrieben wird hier nichts. Das Zurückschreiben ins Manuskript ist ein eigener,
abgesicherter Schritt und bleibt bewusst außerhalb jedes Workflows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import mistralai.workflows as workflows

from . import config
from .models import Stimmprofil
from .scrivener import lies_binder
from .stimme import render_fuer_agent

REPO = Path(__file__).parents[4]


def _geaendert(paket: Path, uuid: str) -> str:
    """ISO-Datum der letzten Änderung eines Abschnitts, leer wenn unbekannt."""
    datei = paket / "Files" / "Data" / uuid / "content.rtf"
    if not datei.is_file():
        return ""
    return datetime.fromtimestamp(datei.stat().st_mtime, tz=UTC).date().isoformat()


def _manuskript(werk: str):
    w = config.lade_werk(werk)
    struktur = w.get("struktur") or {}
    return lies_binder(
        config.scrivener_pfad(werk),
        werk,
        wurzel=struktur.get("wurzel"),
        kapitel_ebene=struktur.get("kapitel_ebene", 0),
    )


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def liste_abschnitte(werk: str) -> dict:
    """Alle Abschnitte mit Text, für die Auswahl im Chat."""
    m = _manuskript(werk)
    paket = config.scrivener_pfad(werk)
    abschnitte = [
        {
            "uuid": a.uuid,
            "titel": a.titel,
            "kapitel": a.pfad[0] if a.pfad else "—",
            "pfad": a.pfad,
            "woerter": a.woerter,
            "absaetze": len(a.absaetze),
            "etikett": a.etikett,
            "status": a.status,
            # Wann der Abschnitt zuletzt angefasst wurde. Steht NICHT im Binder —
            # Scrivener zeigt die Spalte, speichert sie aber als Dateidatum der
            # content.rtf. Genau deshalb muss das eine Aktivität lesen.
            "zuletzt": _geaendert(paket, a.uuid),
        }
        for a in m.abschnitte
        if a.hat_text
    ]
    # Auch die Gliederungsknoten ohne Text: Ein Kapitel, in dem noch nichts steht,
    # ist für die Übersicht die wichtigste Information überhaupt.
    ohne_text = [
        {
            "uuid": a.uuid,
            "titel": a.titel,
            "kapitel": a.pfad[0] if a.pfad else "—",
            "pfad": a.pfad,
            "ist_ordner": a.ist_ordner,
        }
        for a in m.abschnitte
        if not a.hat_text
    ]
    w = config.lade_werk(werk)
    return {
        "werk": werk,
        "titel": w.get("titel", werk),
        "untertitel": w.get("untertitel", ""),
        "abschnitte": abschnitte,
        "leer": ohne_text,
        "kapitel_geplant": [k.get("titel", "") for k in (w.get("kapitel") or []) if isinstance(k, dict)],
    }


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def lies_abschnitt(werk: str, uuid: str) -> dict:
    """Ein Abschnitt samt Absätzen und Absatz-Hashes.

    Die Hashes wandern durch die ganze Sitzung mit: Beim späteren Anwenden wird
    geprüft, ob der Absatz noch derselbe ist. Eine Sitzung kann Stunden offen
    stehen — in der Zeit kann in Scrivener alles passieren.
    """
    m = _manuskript(werk)
    a = next((x for x in m.abschnitte if x.uuid == uuid), None)
    if a is None:
        raise ValueError(f"Abschnitt {uuid} gibt es in {werk} nicht.")
    return {
        "uuid": a.uuid,
        "titel": a.titel,
        "pfad": a.pfad,
        "text": a.text,
        "absaetze": a.absaetze,
        "hashes": [a.absatz_hash(i) for i in range(len(a.absaetze))],
        "woerter": a.woerter,
    }


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def lade_stimmprofil(werk: str) -> str:
    """Das Stimmprofil in der Form, die der Stil-Agent bekommt — leer, wenn keins da ist."""
    pfad = REPO / "shared" / "buch" / f"{werk}-stimme.json"
    if not pfad.is_file():
        return ""
    return render_fuer_agent(Stimmprofil.model_validate_json(pfad.read_text(encoding="utf-8")))


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def liste_werke() -> list[dict]:
    """Alle Werke, für die eine Config in ``shared/buch/`` liegt.

    Damit kann der Gesprächs-Workflow ohne jeden Parameter starten — und fragt
    nur dann nach dem Werk, wenn es mehr als eines gibt.
    """
    ordner = REPO / "shared" / "buch"
    werke = []
    for pfad in sorted(ordner.glob("*.json")):
        name = pfad.stem
        if name.endswith(("-stimme", "-kontext")) or name.startswith(("eval-", "werk.")):
            continue
        if ".example" in pfad.name:
            continue
        try:
            w = config.lade_werk(name)
        except Exception:  # noqa: BLE001 — eine kaputte Config darf den Rest nicht kippen
            continue
        werke.append({"slug": name, "titel": w.get("titel", name)})
    return werke


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def lies_kapitel(werk: str, kapitel: str) -> dict:
    """Ein ganzes Kapitel mit allen Abschnitten — die Eingabe der Inhaltsebene.

    Ebene 3 urteilt über Bögen, Besetzung und Auslassungen. Das ist am einzelnen
    Abschnitt nicht zu sehen, deshalb kommt hier das Kapitel am Stück.
    """
    m = _manuskript(werk)
    drin = [a for a in m.abschnitte if a.hat_text and a.pfad and a.pfad[0] == kapitel]
    if not drin:
        raise ValueError(f"Kapitel {kapitel!r} hat in {werk} keinen Text.")
    return {
        "kapitel": kapitel,
        "abschnitte": [
            {
                "titel": a.titel,
                "pfad": a.pfad,
                "text": a.text,
                "woerter": a.woerter,
                "synopsis": a.synopsis or "",
                "status": a.status,
                "etikett": a.etikett,
            }
            for a in drin
        ],
        "woerter": sum(a.woerter for a in drin),
    }


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def lade_kontext(werk: str, name: str) -> str:
    """Ein Kontextdokument aus ``kontext/`` — Exposé, Kapitelplan, was dazukommt.

    Leerer String, wenn es fehlt: Ein fehlendes Exposé soll die Prüfung nicht
    verhindern, nur schwächer machen — und das steht dann in den Hinweisen.
    """
    ordner = config.werk_pfad(werk, "kontext")
    datei = ordner / f"{name}.md"
    if not datei.is_file():
        return ""
    return datei.read_text(encoding="utf-8")
