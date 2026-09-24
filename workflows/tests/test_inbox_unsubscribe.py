"""Der Abmeldelink-Extraktor ist reines Python — hier ist sein Vertrag.

Live verifiziert: Der Connector liefert keine Header (kein List-Unsubscribe),
but 5–6 of 8 promotional mails carry an ``<a>`` anchor with a matching link
text. What is tested are the shapes that occur in real promotional mail:
nested tags in the link text, HTML entities in the URL, mailto unsubscribes
Langweilfall (kein Link).
"""

from __future__ import annotations

from workflows.inbox.unsubscribe import extract_unsub_link, is_mailto


def _mail(link_text: str, href: str) -> str:
    return f'<html><body><p>Hallo!</p><a href="{href}">{link_text}</a></body></html>'


def test_english_link_text() -> None:
    url = extract_unsub_link(_mail("Unsubscribe", "https://x.example.com/out?u=1"))
    assert url == "https://x.example.com/out?u=1"


def test_german_link_texts() -> None:
    assert extract_unsub_link(_mail("Abmelden", "https://a.example.com")) == "https://a.example.com"
    assert extract_unsub_link(_mail("Hier abbestellen", "https://b.example.com")) == "https://b.example.com"


def test_link_text_with_nested_tags() -> None:
    html = '<a href="https://c.example.com"><span>Abmelden</span></a>'
    assert extract_unsub_link(html) == "https://c.example.com"


def test_opt_out_variants() -> None:
    assert extract_unsub_link(_mail("Opt-out", "https://d.example.com"))
    assert extract_unsub_link(_mail("opt out here", "https://e.example.com"))


def test_entities_in_the_url_are_unescaped() -> None:
    html = '<a href="https://sendgrid.net/asm/?user_id=1&amp;data=2">Unsubscribe</a>'
    assert extract_unsub_link(html) == "https://sendgrid.net/asm/?user_id=1&data=2"


def test_the_first_hit_wins_and_prose_is_not_matched() -> None:
    # „Abmelden" im Fließtext, aber ohne passenden Anker, bleibt Link-leer —
    # and an ordinary anchor without an unsubscribe term is not taken.
    html = '<p>Wenn du dich abmelden willst, klick <a href="https://f.example.com/shop">hier</a>.</p>'
    assert extract_unsub_link(html) == ""


def test_no_link_yields_an_empty_string() -> None:
    assert extract_unsub_link("<html><body>Nur Text.</body></html>") == ""
    assert extract_unsub_link("") == ""


def test_mailto_is_recognised() -> None:
    url = extract_unsub_link(_mail("Unsubscribe", "mailto:leave@list.example.com"))
    assert url == "mailto:leave@list.example.com"
    assert is_mailto(url) is True
    assert is_mailto("https://g.example.com") is False
