"""Aktivitäten, die die Studio-Agents der Buch-Domäne auslösen.

Folgt dem Muster aus ``crm/classify.py``: Der Agent wird über die Conversations-
API **getriggert**, nie über ``Agent(id=…)`` + ``Runner`` neu gebaut — das würde
die Definition in Studio mit den übergebenen Feldern überschreiben.

Alle Funktionen hier sind Aktivitäten (also I/O) und müssen in Workflow-Modulen
durch ``workflow.unsafe.imports_passed_through()`` importiert werden. Sie geben
einfache ``dict``s zurück, damit Temporals Datenkonverter sie sauber über die
Sandbox-Grenze bringt.
"""

from __future__ import annotations

import json
from datetime import timedelta
import mistralai.workflows as workflows
from mistralai.client import models as mistralai_models
from mistralai.workflows.plugins.mistralai.activities import (
    ConversationAppendRequest,
    mistralai_append_conversation,
    mistralai_start_conversation,
)
from pydantic import BaseModel

from . import config
from .models import (
    Gegenlesung,
    InhaltBefund,
    StilGegenlesung,
    Korrekturen,
    StimmProbe,
    StimmProfilRoh,
    Stilvorschlaege,
)


def _extract_text(response: mistralai_models.ConversationResponse) -> str:
    """Fügt den Text einer ConversationResponse zusammen.

    ``content`` ist je nach Antwort entweder ein String oder eine Liste von
    Chunks — beides kommt vor.
    """
    parts: list[str] = []
    for output in response.outputs:
        content = getattr(output, "content", None)
        if content is None:
            continue
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for chunk in content:
                text = getattr(chunk, "text", None)
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _parse[T: BaseModel](model: type[T], text: str) -> T:
    """Liest die Agent-Antwort in ihr Pydantic-Modell.

    Die Agents haben ein JSON-Schema als ``response_format``, der Text ist also
    JSON. Defensiv trotzdem: liegt Prosa drumherum, schneiden wir den äußersten
    ``{…}``-Block heraus.
    """
    try:
        return model.model_validate_json(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return model.model_validate(json.loads(text[start : end + 1]))
        raise


async def _trigger[T: BaseModel](agent_id: str, payload: str, model: type[T]) -> T:
    antwort = await mistralai_start_conversation(
        mistralai_models.ConversationRequest(
            agent_id=agent_id,
            inputs=payload,
            store=False,  # Analyseläufe müssen nicht in Studio liegen bleiben
        )
    )
    return _parse(model, _extract_text(antwort))


async def _trigger_offen[T: BaseModel](
    agent_id: str, payload: str, model: type[T]
) -> tuple[T, str]:
    """Wie :func:`_trigger`, hält die Conversation aber für Rückfragen offen.

    ``store=True`` ist dafür Pflicht: Ein ``append`` auf eine nicht gespeicherte
    Conversation antwortet mit HTTP 404 („Conversation … was not found“, live
    geprüft). Der Preis ist, dass diese Läufe in Studio liegen bleiben — dafür
    ist jede Runde des Judge-Loops dort nachvollziehbar.
    """
    antwort = await mistralai_start_conversation(
        mistralai_models.ConversationRequest(agent_id=agent_id, inputs=payload, store=True)
    )
    return _parse(model, _extract_text(antwort)), antwort.conversation_id


async def _fortsetzen[T: BaseModel](conversation_id: str, payload: str, model: type[T]) -> T:
    """Setzt eine offene Conversation fort — der Agent behält seinen Kontext.

    Deshalb ``append`` statt eines neuen Aufrufs: Der Agent sieht, was er selbst
    vorgeschlagen hat, und bezieht das Urteil darauf. Ein Neustart müsste den
    ganzen Kontext wiederholen und verlöre den Bezug.
    """
    antwort = await mistralai_append_conversation(
        ConversationAppendRequest(conversation_id=conversation_id, inputs=payload, store=True)
    )
    return _parse(model, _extract_text(antwort))


# ---------------------------------------------------------------------------
# Stimmprofil — Map und Reduce
# ---------------------------------------------------------------------------


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=120),
)
async def probiere_stimme(abschnitt: dict) -> dict:
    """Map-Schritt: beobachtet die Stimme an EINEM Abschnitt.

    Nimmt ein einzelnes ``dict``, weil ``execute_activities_in_parallel`` genau
    ein Argument je Element übergibt. Benutzt werden ``titel``, ``text`` und
    ``pfad`` — bewusst NICHT ``synopsis`` (siehe unten).
    """
    kopf = [f"ABSCHNITT: {abschnitt['titel']}"]
    if abschnitt.get("pfad"):
        kopf.append(f"GLIEDERUNG: {' / '.join(abschnitt['pfad'])}")
    # Bewusst OHNE synopsis: Die beschreibt, was der Abschnitt leisten soll, nicht
    # wie der Autor schreibt. Für die Stimme ist sie Rauschen; sie gehört zur
    # Inhaltsebene (buch-inhalt).
    payload = "\n".join(kopf) + "\n\n--- TEXT ---\n" + abschnitt["text"]

    probe = await _trigger(config.AGENTS["stimme_probe"], payload, StimmProbe)
    return {"uuid": abschnitt.get("uuid"), "titel": abschnitt["titel"], **probe.model_dump(mode="json")}


def _vergleichbar(text: str) -> str:
    """Vergleichsform für den Katalogabgleich: Leerraum und Anführungszeichen egal."""
    einheitlich = " ".join(str(text).split())
    for a, b in (("„", '"'), ("“", '"'), ("”", '"'), ("‚", "'"), ("‘", "'"), ("’", "'")):
        einheitlich = einheitlich.replace(a, b)
    return einheitlich.strip(" \"'.,;:!?").lower()


def _satzkatalog(proben: list[dict]) -> list[str]:
    """Alle wörtlich belegten Sätze aus den Proben, entdoppelt und stabil geordnet.

    Quelle sind ``beispielsaetze`` und die ``beleg``-Felder der Beobachtungen —
    beides hat der Map-Schritt direkt aus dem Abschnittstext gezogen.
    """
    gesehen: dict[str, None] = {}
    for p in proben:
        for satz in p.get("beispielsaetze") or []:
            if isinstance(satz, str) and len(satz.strip()) > 20:
                gesehen.setdefault(satz.strip(), None)
        for b in p.get("beobachtungen") or []:
            beleg = (b or {}).get("beleg")
            if isinstance(beleg, str) and len(beleg.strip()) > 20:
                gesehen.setdefault(beleg.strip(), None)
    return list(gesehen)


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=300),
)
async def verdichte_stimme(
    proben: list[dict], metrik_text: str, max_regeln: int
) -> dict:
    """Reduce-Schritt: verdichtet alle Beobachtungen zu höchstens ``max_regeln`` Regeln.

    Der Agent bekommt einen **nummerierten Satzkatalog** und verweist mit Nummern
    darauf, statt Zitate abzutippen. Vorher tat er Letzteres — und paraphrasierte
    dabei: In einem gemessenen Lauf fielen zehn von zwölf Regeln durch die
    Belegprüfung, weil ihre „wörtlichen" Fundstellen so nicht im Manuskript
    standen. Eine Nummer kann man nicht paraphrasieren.
    """
    katalog = _satzkatalog(proben)
    teile = [
        f"HÖCHSTENS {max_regeln} REGELN.",
        "",
        "=== GEMESSENE KENNZAHLEN (Fakten, nicht umdeuten) ===",
        metrik_text,
        "",
    ]
    teile += [
        "=== SATZKATALOG — nur aus diesen Nummern darfst du Fundstellen wählen ===",
        "\n".join(f"[{n}] {satz}" for n, satz in enumerate(katalog)),
        "",
        "=== BEOBACHTUNGEN AUS DEN ABSCHNITTEN ===",
    ]
    for i, p in enumerate(proben, start=1):
        teile.append(f"\n--- Abschnitt {i} ---")
        teile.append(json.dumps(p, ensure_ascii=False, indent=1))

    profil = await _trigger(
        config.AGENTS["stimme_profil"], "\n".join(teile), StimmProfilRoh
    )
    roh = profil.model_dump(mode="json")
    # Gegen den Katalog auflösen — Nummern ODER Wortlaut.
    #
    # Gedacht war: nur Nummern, denn eine Nummer kann man nicht paraphrasieren.
    # Gemessen: Das Modell schreibt trotzdem Sätze, auch mit ``strict: true`` im
    # Schema — strict erzwingt Enums, aber keine Zahlentypen. Ein ``list[int]``
    # ließ die Validierung dreimal scheitern und den Lauf hängen.
    #
    # Also beides annehmen und in Python auflösen. Die Garantie bleibt
    # unverändert: Was im Katalog nicht steht, fällt raus. Nur der Weg dorthin
    # ist jetzt tolerant statt starr.
    nach_wortlaut = {_vergleichbar(s): s for s in katalog}
    for r in roh.get("regeln", []):
        aufgeloest: list[str] = []
        for eintrag in r.get("fundstellen", []):
            text = str(eintrag).strip().strip("[]")
            if text.isdigit() and 0 <= int(text) < len(katalog):
                aufgeloest.append(katalog[int(text)])
                continue
            treffer = nach_wortlaut.get(_vergleichbar(text))
            if treffer:
                aufgeloest.append(treffer)
        r["fundstellen"] = aufgeloest
    return roh


# ---------------------------------------------------------------------------
# Lektorat — Ebene 1 und 2
# ---------------------------------------------------------------------------


def _absatzblock(absaetze: list[str]) -> str:
    """Absätze mit ihrem Index — der Agent adressiert Befunde über ``absatz_index``."""
    return "\n\n".join(f"[{i}] {a}" for i, a in enumerate(absaetze))


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def korrigiere(titel: str, absaetze: list[str]) -> dict:
    """Ebene 1: Rechtschreibung, Zeichensetzung, Grammatik, Tempus, Typografie."""
    payload = f"ABSCHNITT: {titel}\n\n--- ABSÄTZE ---\n{_absatzblock(absaetze)}"
    ergebnis = await _trigger(config.AGENTS["korrektorat"], payload, Korrekturen)
    return ergebnis.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def stil_pruefen(
    titel: str, absaetze: list[str], stimmprofil_text: str, max_befunde: int
) -> dict:
    """Ebene 2: macht den Text dem Autor ähnlicher, nicht glatter."""
    payload = (
        f"HÖCHSTENS {max_befunde} VORSCHLÄGE.\n\n"
        f"=== STIMMPROFIL DES AUTORS ===\n{stimmprofil_text}\n\n"
        f"=== ABSCHNITT: {titel} ===\n{_absatzblock(absaetze)}"
    )
    ergebnis = await _trigger(config.AGENTS["stil"], payload, Stilvorschlaege)
    return ergebnis.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=300),
)
async def pruefe_inhalt(
    kapitel: dict, rubrik: dict, pruefsteine: dict, expose: str = ""
) -> dict:
    """Ebene 3: ein ganzes Kapitel gegen die Rubrik des Autors.

    Drei Maßstäbe, in dieser Reihenfolge der Verbindlichkeit: die **Rubrik** des
    Kapitels (was es tragen muss), die **Prüfsteine** des Werks (die zwei Fragen)
    und das **Exposé** (was das Buch insgesamt sein soll). Das Exposé steht
    bewusst zuletzt und wird ausdrücklich als Absicht gekennzeichnet — es
    beschreibt das Buch, wie es Verlagen angeboten wird, nicht wie das Manuskript
    ist. Wer beides verwechselt, hält jede Abweichung für einen Fehler.
    """
    teile: list[str] = []
    if expose:
        teile += [
            "=== EXPOSÉ — was das Buch werden SOLL (Absicht, nicht Ist-Zustand) ===",
            expose.strip(),
            "",
        ]
    teile += ["=== PRÜFSTEINE DES WERKS — die zwei Fragen an jedes Kapitel ==="]
    for schluessel in ("erste_frage", "zweite_frage"):
        frage = pruefsteine.get(schluessel) or {}
        if frage.get("regel"):
            teile.append(f"- {frage['regel']}")
            if frage.get("erlaeuterung"):
                teile.append(f"  {frage['erlaeuterung']}")
    teile.append("")

    teile += [f"=== RUBRIK FÜR DIESES KAPITEL: {rubrik.get('titel', '')} ==="]
    if rubrik.get("untertitel"):
        teile.append(f"Untertitel: {rubrik['untertitel']}")
    for feld, ueberschrift in (
        ("beweist", "Beweist"),
        ("muss_tragen", "Muss tragen"),
        ("muss_nicht_tragen", "Muss NICHT tragen"),
        ("offene_arbeit", "Offene Arbeit laut Plan"),
    ):
        werte = rubrik.get(feld) or []
        if werte:
            teile.append(f"{ueberschrift}:")
            teile += [f"  - {w}" for w in werte]
    for feld, ueberschrift in (("register", "Register"), ("zeit", "Zeit"), ("an_bord", "An Bord")):
        if rubrik.get(feld):
            teile.append(f"{ueberschrift}: {rubrik[feld]}")
    if rubrik.get("historie_budget") is not None:
        teile.append(f"Historie-Budget: {rubrik['historie_budget']} Stellen")
    teile.append("")

    teile.append(f"=== DAS KAPITEL: {kapitel['kapitel']} ({kapitel['woerter']} Wörter) ===")
    for a in kapitel["abschnitte"]:
        teile.append(f"\n## {a['titel']}  ({a['woerter']} Wörter, {a['status'] or 'ohne Status'})")
        if a.get("synopsis"):
            teile.append(f"> Absicht laut Scrivener: {a['synopsis']}")
        teile.append(a["text"])

    ergebnis = await _trigger(config.AGENTS["inhalt"], "\n".join(teile), InhaltBefund)
    return ergebnis.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def gegenlese_stil(
    titel: str, absaetze: list[str], stimmprofil_text: str, vorschlaege: list[dict]
) -> dict:
    """Das zweite Augenpaar über Ebene 2 — eine Frage je Vorschlag.

    Nicht dasselbe wie beim Korrektorat: Dort wird auch gesucht, was FEHLT. Hier
    nicht. Ein übersehener Stilbruch kostet nichts; ein aufgedrängter Vorschlag
    kostet den Autor seine Stimme. Deshalb prüft diese Stufe nur in eine
    Richtung — hält der Vorschlag, was seine Regel verspricht?
    """
    liste = "\n".join(
        f"{i}. „{v.get('search')}“ → „{v.get('replace')}“  [{v.get('regel_id')}] — "
        f"{v.get('warum', '')}"
        for i, v in enumerate(vorschlaege, start=1)
    )
    payload = (
        f"=== STIMMPROFIL DES AUTORS ===\n{stimmprofil_text}\n\n"
        f"=== ABSCHNITT: {titel} ===\n{_absatzblock(absaetze)}\n\n"
        f"--- VORSCHLAEGE DER ERSTEN STUFE ---\n{liste}"
    )
    ergebnis = await _trigger(config.AGENTS["stil_gegenlesen"], payload, StilGegenlesung)
    return ergebnis.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def gegenlese(
    titel: str, absaetze: list[str], befunde: list[dict], kontext: str = ""
) -> dict:
    """Das zweite Augenpaar über einem Lektorat.

    Bekommt DENSELBEN Abschnitt wie die erste Stufe, dazu deren Befunde. Der
    frühere Judge bekam nur ``search`` und ``replace`` — einen Schnipsel ohne
    den Satz, in dem er steht — und konnte schon deshalb nicht beurteilen, ob
    ein Fehler behoben wird. Und weil er je Befund lief, lief er bei null
    Befunden nie: Ein übersehener Fehler war unsichtbar.
    """
    liste = "\n".join(
        f"{i}. Absatz {b.get('absatz_index')}: „{b.get('search')}“ → „{b.get('replace')}“"
        f" ({b.get('art', '')}) — {b.get('warum', '')}"
        for i, b in enumerate(befunde, start=1)
    ) or "(keine)"
    payload = (
        f"ABSCHNITT: {titel}\n\n--- ABSÄTZE ---\n{_absatzblock(absaetze)}\n\n"
        f"--- BEFUNDE DER ERSTEN STUFE ---\n{liste}"
    )
    if kontext:
        payload += f"\n\n=== KONTEXT ===\n{kontext}"
    ergebnis = await _trigger(config.AGENTS["gegenlesen"], payload, Gegenlesung)
    return ergebnis.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def korrigiere_offen(titel: str, absaetze: list[str]) -> dict:
    """Wie :func:`korrigiere`, gibt aber die ``conversation_id`` mit zurück.

    Nur nötig, wenn ein Judge-Loop folgt — ohne Loop bleibt ``store=False``
    richtig, weil dann nichts in Studio liegen bleiben muss.
    """
    payload = f"ABSCHNITT: {titel}\n\n--- ABSÄTZE ---\n{_absatzblock(absaetze)}"
    ergebnis, cid = await _trigger_offen(config.AGENTS["korrektorat"], payload, Korrekturen)
    return {"conversation_id": cid, **ergebnis.model_dump(mode="json")}


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def ueberarbeite(conversation_id: str, rueckmeldung: str, ebene: str) -> dict:
    """Gibt dem Agent das Urteil zurück und lässt ihn nachbessern."""
    modell = Korrekturen if ebene == "korrektorat" else Stilvorschlaege
    ergebnis = await _fortsetzen(conversation_id, rueckmeldung, modell)
    return ergebnis.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Hilfsaktivitäten
# ---------------------------------------------------------------------------


@workflows.activity(start_to_close_timeout=timedelta(seconds=10))
async def heute() -> str:
    """Die Uhr über eine Aktivität lesen — Workflow-Code muss deterministisch bleiben."""
    from datetime import date

    return date.today().isoformat()


def agent_verfuegbar(schluessel: str) -> bool:
    """Ob für diesen Zweck eine Agent-ID hinterlegt ist."""
    return bool(config.AGENTS.get(schluessel))


def fehlende_agents() -> list[str]:
    """Agents ohne ID — nach ``make sync-agents`` müssen die IDs in shared/buch.json."""
    return [k for k, v in config.AGENTS.items() if not v]
