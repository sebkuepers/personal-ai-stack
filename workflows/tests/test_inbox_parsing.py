"""Parsing the Gmail answers carries the pitfalls verified live.

``messages: null`` is the normal case and varies per run (26–57 on an identical
query — measured, not guessed). The category sits in ``labelIds`` as
``CATEGORY_*``, the date as an ISO datetime with an offset. A mistake here
distorts every number in the report. Tested with fixtures in the exact shape
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


def test_envelope_from_a_full_answer() -> None:
    u = thread_to_envelope(THREAD)
    assert u is not None
    assert u.thread_id == "t1"
    assert u.sender == "notifications@github.com"
    assert u.category == "UPDATES"
    assert u.unread is True
    assert u.received_on == date(2026, 9, 23)


def test_without_category_and_read() -> None:
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


def test_messages_null_is_normal_and_yields_none() -> None:
    # Der häufigste Fallstrick: Threads kommen ohne Message-Liste zurück,
    # non-deterministic, 26-57 per run. The parser returns None, never a crash.
    assert thread_to_envelope({"id": "t4", "messages": None}) is None
    assert thread_to_envelope({"id": "t5"}) is None
    assert thread_to_envelope({"id": "t6", "messages": []}) is None


def test_incomplete_fields_are_tolerated() -> None:
    u = thread_to_envelope({"id": "t7", "messages": [{"sender": "x@example.com"}]})
    assert u is not None
    assert u.sender == "x@example.com"
    assert u.subject == ""
    assert u.received_on is None


def test_sent_envelope_from_the_sent_search() -> None:
    g = thread_to_sent(SENT_THREAD)
    assert g is not None
    assert g.sender == "seb@example.com"
    assert g.to == ["marie@example.com"]
    assert g.received_on == date(2026, 9, 23)


def test_sent_envelope_with_a_string_recipient() -> None:
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


def test_own_address_is_the_most_frequent_sender() -> None:
    g1 = thread_to_sent(SENT_THREAD)
    assert g1 is not None
    assert own_address([g1]) == "seb@example.com"
    assert own_address([]) == ""


def test_replied_recipients_are_lower_cased() -> None:
    g = thread_to_sent(SENT_THREAD)
    assert g is not None
    g.to = ["Marie@Example.com", "  hans@example.com  "]
    assert replied_recipients([g]) == {"marie@example.com", "hans@example.com"}
