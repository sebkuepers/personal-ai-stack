"""Der Abmeldelink-Extraktor ist reines Python — hier ist sein Vertrag.

Live verifiziert: Der Connector liefert keine Header (kein List-Unsubscribe),
aber 5–6 von 8 Promo-Mails tragen einen ``<a>``-Anker mit passendem Linktext.
Getestet werden die Formen, die in echten Werbemails vorkommen: verschachtelte
Tags im Linktext, HTML-Entities in der URL, mailto-Abmeldungen und der
Langweilfall (kein Link).
"""

from __future__ import annotations

from workflows.inbox.unsubscribe import extract_unsub_link, ist_mailto


def _mail(linktext: str, href: str) -> str:
    return f'<html><body><p>Hallo!</p><a href="{href}">{linktext}</a></body></html>'


def test_englischer_linktext() -> None:
    url = extract_unsub_link(_mail("Unsubscribe", "https://x.example.com/out?u=1"))
    assert url == "https://x.example.com/out?u=1"


def test_deutsche_linktexte() -> None:
    assert extract_unsub_link(_mail("Abmelden", "https://a.example.com")) == "https://a.example.com"
    assert extract_unsub_link(_mail("Hier abbestellen", "https://b.example.com")) == "https://b.example.com"


def test_linktext_mit_verschachtelten_tags() -> None:
    html = '<a href="https://c.example.com"><span>Abmelden</span></a>'
    assert extract_unsub_link(html) == "https://c.example.com"


def test_opt_out_varianten() -> None:
    assert extract_unsub_link(_mail("Opt-out", "https://d.example.com"))
    assert extract_unsub_link(_mail("opt out here", "https://e.example.com"))


def test_entities_in_der_url_werden_aufgeloest() -> None:
    html = '<a href="https://sendgrid.net/asm/?user_id=1&amp;data=2">Unsubscribe</a>'
    assert extract_unsub_link(html) == "https://sendgrid.net/asm/?user_id=1&data=2"


def test_erster_treffer_gewinnt_kein_abgleich_in_der_prosa() -> None:
    # „Abmelden" im Fließtext, aber ohne passenden Anker, bleibt Link-leer —
    # und ein normaler Anker ohne Abmelde-Begriff wird nicht genommen.
    html = '<p>Wenn du dich abmelden willst, klick <a href="https://f.example.com/shop">hier</a>.</p>'
    assert extract_unsub_link(html) == ""


def test_kein_link_liefert_leerstring() -> None:
    assert extract_unsub_link("<html><body>Nur Text.</body></html>") == ""
    assert extract_unsub_link("") == ""


def test_mailto_erkennen() -> None:
    url = extract_unsub_link(_mail("Unsubscribe", "mailto:leave@list.example.com"))
    assert url == "mailto:leave@list.example.com"
    assert ist_mailto(url) is True
    assert ist_mailto("https://g.example.com") is False
