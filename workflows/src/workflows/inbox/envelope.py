"""Reines Parsen der Gmail-Antworten in Umschläge — die Fallstricke wohnen hier.

Live verifiziert (2026-09-23, gegen das Konto gemessen):
- ``search_threads`` liefert Bodies IMMER null (644 Messages, zwei Läufe).
- Ein Teil der Threads kommt mit ``messages: null`` zurück — nichtdeterministisch,
  26–57 pro Lauf bei identischer Query. Kein Fehler, nur ein Zustand.
- Die Kategorie (UPDATES/PROMOTIONS/…) steckt in ``labelIds`` als ``CATEGORY_*``.
- Spam und Trash sind von der Suche standardmäßig ausgeschlossen.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from workflows.inbox.models import InboxEnvelope, SentEnvelope


def _datum(text: str | None) -> date | None:
    """ISO-Datetime („2026-09-23T12:59:32-07:00") auf das Datum kürzen."""
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def thread_to_envelope(thread: dict) -> InboxEnvelope | None:
    """Ein roher Thread aus search_threads → Umschlag; None bei ``messages: null``.

    Der Umschlag ist die LETZTE Message des Threads — bei einer Antwort von
    Sebastian selbst steht dort seine eigene Adresse (siehe own_address()).
    """
    msgs = thread.get("messages")
    if not msgs:
        return None
    m = msgs[-1]
    labels = m.get("labelIds") or []
    category = next(
        (label[len("CATEGORY_") :] for label in labels if label.startswith("CATEGORY_")),
        "",
    )
    return InboxEnvelope(
        thread_id=thread.get("id") or "",
        message_id=m.get("id") or "",
        sender=m.get("sender") or "",
        subject=m.get("subject") or "",
        snippet=m.get("snippet") or "",
        labels=labels,
        category=category,
        unread="UNREAD" in labels,
        received_on=_datum(m.get("date")),
    )


def thread_to_sent(thread: dict) -> SentEnvelope | None:
    """Ein roher Thread aus der Sent-Suche → gesendeter Umschlag; None ohne Messages."""
    msgs = thread.get("messages")
    if not msgs:
        return None
    m = msgs[-1]
    to = m.get("toRecipients") or []
    if isinstance(to, str):
        to = [to]
    return SentEnvelope(
        thread_id=thread.get("id") or "",
        message_id=m.get("id") or "",
        sender=m.get("sender") or "",
        to=[a for a in to if a],
        subject=m.get("subject") or "",
        received_on=_datum(m.get("date")),
    )


def own_address(gesendet: list[SentEnvelope]) -> str:
    """Die eigene Adresse — die häufigste Absender-Adresse im Sent-Fenster.

    Leer, wenn nichts gesendet wurde; dann bleiben alle Inbox-Umschläge
    Sichtungs-Kandidaten (der Filter greift nur mit bekannter Adresse).
    """
    zaehler = Counter(s.sender for s in gesendet if s.sender)
    if not zaehler:
        return ""
    return zaehler.most_common(1)[0][0]


def replied_recipients(gesendet: list[SentEnvelope]) -> set[str]:
    """Alle Adressen (kleingeschrieben), an die im Fenster geschrieben wurde.

    Die Grundlage für den Antwort-Zustand: Ein „antwortbedürftig"-Kandidat,
    dessen Absender hier steht, ist vermutlich schon beantwortet.
    """
    menge: set[str] = set()
    for s in gesendet:
        for adresse in s.to:
            menge.add(adresse.strip().lower())
    return menge
