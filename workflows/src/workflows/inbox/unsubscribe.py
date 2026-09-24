"""Pull the unsubscribe link deterministically out of the HTML — no model, no headers.

Verified live (2026-09-23): the Gmail connector exposes NO headers — an
RFC 8058 List-Unsubscribe route therefore does not exist. But 5–6 of 8
promotional mails carry an ``<a>`` anchor whose link text contains
"unsubscribe", "abmelden", "abbestellen" or "opt-out". That is pure Python and
hits real unsubscribe services (sendgrid, kmail, …).

The search terms are German and English because the mailbox is.
"""

from __future__ import annotations

import html
import re

_ANCHOR = re.compile(r'<a\s[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
_TERM = re.compile(r"unsubscribe|abmelden|abbestellen|opt[- ]?out", re.I)


def extract_unsub_link(html_text: str) -> str:
    """The first unsubscribe link of the HTML — "" when none is found.

    The link text may contain tags (``<span>Abmelden</span>``); what counts is
    the text content. The returned href is unescaped (``&amp;`` → ``&``).
    """
    for anchor in _ANCHOR.finditer(html_text):
        link_text = re.sub(r"<[^>]+>", " ", anchor.group(2))
        if _TERM.search(link_text):
            return html.unescape(anchor.group(1)).strip()
    return ""


def is_mailto(url: str) -> bool:
    """A mailto unsubscribe link can be answered with a draft — noted for the cleanup step."""
    return url[:7].lower() == "mailto:"
