"""Direkte Gmail-Tool-Aufrufe als Aktivitäten — kein Lese-Agent (Muster A).

Workflows-CLAUDE.md Abschnitt 6, Muster A: deterministische Aufrufe mit
bekannten Eingaben statt eines Agents, der die Tools selbst entdeckt. Das
Lesen ist Arithmetik — ein Lese-Agent würde ein Modell dafür bezahlen, Zahlen
zu ziehen, die Python exakt liefert.

Live verifiziert (2026-09-23, gegen das Konto gemessen):
- ``resultCountEstimate`` ist als Planzahl unbrauchbar (konstant 201 auf allen
  Nicht-Endseiten) — paginiert wird bis ``nextPageToken`` fehlt.
- Ohne Pause zwischen den Seiten kommt irgendwann eine leere Antwort
  (Rate-Limit). 1,2 s pro Seite lief durch (70 Seiten am Stück).
- ``search_threads`` nimmt ``query``, ``pageSize`` (max 50), ``pageToken``;
  ``get_thread`` nimmt ``threadId`` und ``messageFormat``.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

import mistralai.workflows as workflows
from mistralai.workflows import Depends
from mistralai.workflows.plugins.mistralai.connectors import ToolCallClient

from workflows.crm.connectors import gmail_connector

from . import config

_PAUSE_SEKUNDEN = 1.2  # ohne sie: leere Seiten (Rate-Limit) — live verifiziert
_MAX_SEITEN = 200  # 200 × 50 = 10.000 Threads Deckel gegen Endlosschleifen


def _tool_json(ergebnis: Any) -> dict:
    """Extrahiert das JSON aus einer Tool-Antwort (``content[0].text``), beide Formen.

    ``ToolCallClient.call_tool`` gibt je nach SDK-Pfad das Response-Model oder
    sein dict zurück — beides wird hier genommen.
    """
    content = getattr(ergebnis, "content", None)
    if content is None and isinstance(ergebnis, dict):
        content = ergebnis.get("content")
    if not content:
        raise RuntimeError(f"Tool-Antwort ohne content: {str(ergebnis)[:200]}")
    erstes = content[0]
    text = erstes.get("text") if isinstance(erstes, dict) else getattr(erstes, "text", None)
    if not text:
        raise RuntimeError("Tool-Antwort ohne Text in content[0]")
    return json.loads(text)


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(minutes=15),
)
async def gmail_search_threads(
    query: str,
    max_threads: int,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> dict:
    """Paginierte ``search_threads``-Suche → ``{"threads": [...], "pages": n}``.

    Spam und Trash sind von Gmail standardmäßig ausgeschlossen; wer sie will,
    formuliert es im query (``in:anywhere``).
    """
    threads: list[dict] = []
    token: str | None = None
    pages = 0
    while len(threads) < max_threads and pages < _MAX_SEITEN:
        arguments: dict[str, Any] = {"query": query, "pageSize": 50}
        if token:
            arguments["pageToken"] = token
        payload = _tool_json(
            await gmail.call_tool(
                tool_name=config.GMAIL_TOOLS["search"], arguments=arguments
            )
        )
        threads.extend(payload.get("threads") or [])
        token = payload.get("nextPageToken")
        pages += 1
        if not token:
            break
        await asyncio.sleep(_PAUSE_SEKUNDEN)
    return {"threads": threads[:max_threads], "pages": pages}


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=90),
)
async def gmail_thread_body(
    thread_id: str,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> str:
    """Letzte Message eines Threads als Text (HTML bevorzugt) — für Abmeldelinks.

    Bodies gibt es nur über ``get_thread``; eine einzige Werbemail hatte
    132.689 Zeichen HTML. Deshalb wird das nur einzeln geholt, nie flächig.
    """
    payload = _tool_json(
        await gmail.call_tool(
            tool_name=config.GMAIL_TOOLS["get"],
            arguments={"threadId": thread_id, "messageFormat": "FULL_CONTENT"},
        )
    )
    thread = payload.get("thread") or payload
    msgs = thread.get("messages") or []
    if not msgs:
        return ""
    m = msgs[-1]
    return m.get("htmlBody") or m.get("plaintextBody") or ""


# --------------------------------------------------------------------------- #
# Schreibende Werkzeuge — Stufe 2/3 der Sicherheitsleiter. Sie laufen NUR über
# die freigegebenen Aufräum-Schritte der Sprechstunde, nie im stillen Lauf.
# --------------------------------------------------------------------------- #


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=60),
)
async def gmail_ensure_label(
    name: str,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> str:
    """Holt die Label-ID nach Namen — oder legt das Label an, wenn es fehlt.

    Die Label-Namen kommen aus ``shared/inbox.json`` (``labels``), nie aus
    freier Quelle. ``list_labels`` liefert nur Nutzer-Labels; System-Labels
    (UNREAD, INBOX, SPAM …) brauchen keine IDs.
    """
    # Beide Feldnamen sind live geprueft und NICHT das, was man erwartet:
    # list_labels liefert "labelId" (nicht "id"), und create_label verlangt
    # "displayName" (nicht "name"). Mit den erwarteten Namen fand der Abgleich
    # nie ein vorhandenes Label, und das Anlegen scheiterte an der
    # Schema-Validierung — der ganze Aufraeum-Schritt war tot.
    payload = _tool_json(
        await gmail.call_tool(tool_name=config.GMAIL_TOOLS["list_labels"],
                              arguments={"pageSize": "200"})
    )
    for label in payload.get("labels") or []:
        if label.get("name") == name and label.get("labelId"):
            return str(label["labelId"])
    created = _tool_json(
        await gmail.call_tool(
            tool_name=config.GMAIL_TOOLS["create_label"], arguments={"displayName": name}
        )
    )
    label = created.get("label") or created
    label_id = label.get("labelId") or label.get("id") or ""
    if not label_id:
        raise RuntimeError(f"Label {name!r} angelegt, aber keine ID in der Antwort: {created}")
    return str(label_id)


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=60),
)
async def gmail_process_thread(
    thread_id: str,
    label_id: str,
    archivieren: bool,
    gelesen: bool,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> dict:
    """Setzt das verarbeitet-Label; optional gelesen (UNREAD weg) und archiviert (INBOX weg).

    „Als gelesen markieren" ist in Gmail das Entfernen des UNREAD-System-Labels,
    „archivieren" das Entfernen des INBOX-Labels — die label_thread-Doku nennt
    System-Label-IDs ausdrücklich. Beides ist reversibel; gesendet wird nie.
    """
    await gmail.call_tool(
        tool_name=config.GMAIL_TOOLS["label_thread"],
        arguments={"threadId": thread_id, "labelIds": [label_id]},
    )
    weg: list[str] = []
    if gelesen:
        weg.append("UNREAD")
    if archivieren:
        weg.append("INBOX")
    if weg:
        await gmail.call_tool(
            tool_name=config.GMAIL_TOOLS["unlabel_thread"],
            arguments={"threadId": thread_id, "labelIds": weg},
        )
    return {"thread_id": thread_id}


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=60),
)
async def gmail_draft(
    to: str,
    subject: str,
    body: str,
    reply_to_message_id: str | None = None,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> dict:
    """Legt einen Draft an — der Connector KANN nicht senden (Gotcha 7).

    Für mailto-Abmeldelinks (Absenden bestätigt der Mensch) und später
    vorformulierte Antworten (reply_to_message_id).
    """
    arguments: dict[str, Any] = {"to": to, "subject": subject, "body": body}
    if reply_to_message_id:
        arguments["replyToMessageId"] = reply_to_message_id
    payload = _tool_json(
        await gmail.call_tool(tool_name=config.GMAIL_TOOLS["draft"], arguments=arguments)
    )
    return {"draft": payload.get("id") or payload.get("draft", {}).get("id", "")}
