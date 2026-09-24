"""Das Parsen der Gmail-Antworten trägt die live verifizierten Fallstricke.

``messages: null`` ist Normalfall und schwankt pro Lauf (26–57 bei gleicher
Query — gemessen, nicht geraten). Die Kategorie steckt als ``CATEGORY_*`` in
``labelIds``, das Datum als ISO-Datetime mit Offset. Ein Fehler hier verfälscht
jede Zahl im Report. Getestet mit Fixtures in der exakten Form, die
``search_threads`` liefert.
"""

from __future__ import annotations

from datetime import date

from workflows.inbox.envelope import (
    replied_recipients,
    own_address,
    thread_to_sent,
    thread_to_envelope,
)

THREAD = {
    "id": "t1",
    "messages": [
        {
            "id": "m1",
            "sender": "notifications@github.com",
            "subject": "Run failed: CI",
            "snippet": "CI failed in 14 seconds",
            "labelIds": ["UNREAD", "CATEGORY_UPDATES", "INBOX"],
            "date": "2026-09-23T12:59:32-07:00",
        }
    ],
}

SENT_THREAD = {
    "id": "t2",
    "messages": [
        {
            "id": "m2",
            "sender": "seb@example.com",
            "subject": "Re: Termin",
            "toRecipients": ["marie@example.com"],
            "labelIds": ["SENT"],
            "date": "2026-09-23T14:00:00+02:00",
        }
    ],
}


def test_umschlag_aus_voller_antwort() -> None:
    u = thread_to_envelope(THREAD)
    assert u is not None
    assert u.thread_id == "t1"
    assert u.sender == "notifications@github.com"
    assert u.category == "UPDATES"
    assert u.unread is True
    assert u.received_on == date(2026, 9, 23)


def test_ohne_kategorie_und_gelesen() -> None:
    thread = {
        "id": "t3",
        "messages": [
            {
                "id": "m3",
                "sender": "a@example.com",
                "subject": "Hi",
                "snippet": "",
                "labelIds": ["INBOX"],
                "date": "2026-09-23T10:00:00Z",
            }
        ],
    }
    u = thread_to_envelope(thread)
    assert u is not None
    assert u.category == ""
    assert u.unread is False


def test_messages_null_ist_normalfall_und_liefert_none() -> None:
    # Der häufigste Fallstrick: Threads kommen ohne Message-Liste zurück,
    # nichtdeterministisch, 26-57 pro Lauf. Der Parser liefert None, nie einen Crash.
    assert thread_to_envelope({"id": "t4", "messages": None}) is None
    assert thread_to_envelope({"id": "t5"}) is None
    assert thread_to_envelope({"id": "t6", "messages": []}) is None


def test_unvollstaendige_felder_werden_ertragen() -> None:
    u = thread_to_envelope({"id": "t7", "messages": [{"sender": "x@example.com"}]})
    assert u is not None
    assert u.sender == "x@example.com"
    assert u.subject == ""
    assert u.received_on is None


def test_gesendet_aus_sent_suche() -> None:
    g = thread_to_sent(SENT_THREAD)
    assert g is not None
    assert g.sender == "seb@example.com"
    assert g.to == ["marie@example.com"]
    assert g.received_on == date(2026, 9, 23)


def test_gesendet_mit_string_empfaenger() -> None:
    thread = {
        "id": "t8",
        "messages": [
            {
                "id": "m8",
                "sender": "seb@example.com",
                "subject": "Re:",
                "toRecipients": "marie@example.com",
                "date": None,
            }
        ],
    }
    g = thread_to_sent(thread)
    assert g is not None
    assert g.to == ["marie@example.com"]
    assert g.received_on is None


def test_own_address_ist_der_haeufigste_absender() -> None:
    g1 = thread_to_sent(SENT_THREAD)
    assert g1 is not None
    assert own_address([g1]) == "seb@example.com"
    assert own_address([]) == ""


def test_replied_recipients_kleingeschrieben() -> None:
    g = thread_to_sent(SENT_THREAD)
    assert g is not None
    g.to = ["Marie@Example.com", "  hans@example.com  "]
    assert replied_recipients([g]) == {"marie@example.com", "hans@example.com"}
