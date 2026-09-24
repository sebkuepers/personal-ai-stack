"""Abmeldelink deterministisch aus dem HTML ziehen — kein Modell, keine Header.

Live verifiziert (2026-09-23): Der Gmail-Connector liefert KEINE Header — ein
List-Unsubscribe-Abweg per RFC 8058 existiert damit nicht. Aber 5–6 von 8
Promo-Mails tragen einen ``<a>``-Anker, dessen Linktext „unsubscribe",
„abmelden", „abbestellen" oder „opt-out" enthält. Das ist reines Python und
trifft reale Abmeldedienste (sendgrid, kmail, …).
"""

from __future__ import annotations

import html
import re

_ANKER = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
_BEGRIFF = re.compile(r"unsubscribe|abmelden|abbestellen|opt[- ]?out", re.I)


def extract_unsub_link(html_text: str) -> str:
    """Der erste Abmeldelink des HTML — "" wenn keiner gefunden wird.

    Der Linktext darf Tags enthalten (``<span>Abmelden</span>``); entscheidend
    ist der Textinhalt. Zurückgegeben wird die unescapte href (``&amp;`` → ``&``).
    """
    for anker in _ANKER.finditer(html_text):
        linktext = re.sub(r"<[^>]+>", " ", anker.group(2))
        if _BEGRIFF.search(linktext):
            return html.unescape(anker.group(1)).strip()
    return ""


def ist_mailto(url: str) -> bool:
    """Ein mailto-Abmeldelink lässt sich als Draft beantworten — merken für Phase 2."""
    return url[:7].lower() == "mailto:"
