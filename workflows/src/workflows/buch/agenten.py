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
from mistralai.workflows.plugins.mistralai.activities import mistralai_start_conversation
from pydantic import BaseModel

from . import config
from .models import Korrekturen, StimmProbe, StimmProfilRoh, Stilvorschlaege


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


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=300),
)
async def verdichte_stimme(
    proben: list[dict], metrik_text: str, notizregeln: str, max_regeln: int
) -> dict:
    """Reduce-Schritt: verdichtet alle Beobachtungen zu höchstens ``max_regeln`` Regeln."""
    teile = [
        f"HÖCHSTENS {max_regeln} REGELN.",
        "",
        "=== GEMESSENE KENNZAHLEN (Fakten, nicht umdeuten) ===",
        metrik_text,
        "",
    ]
    if notizregeln:
        teile += [
            "=== REGELN, DIE DER AUTOR SELBST FORMULIERT HAT ===",
            "Diese haben Vorrang. Übernimm seine Formulierung und seinen Namen, "
            'setze quelle = "notizen".',
            "",
            notizregeln,
            "",
        ]
    teile += ["=== BEOBACHTUNGEN AUS DEN ABSCHNITTEN ==="]
    for i, p in enumerate(proben, start=1):
        teile.append(f"\n--- Abschnitt {i} ---")
        teile.append(json.dumps(p, ensure_ascii=False, indent=1))

    profil = await _trigger(
        config.AGENTS["stimme_profil"], "\n".join(teile), StimmProfilRoh
    )
    return profil.model_dump(mode="json")


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
