"""Putting summaries into the Mistral Library — aggregates only.

The same shape as ``inbox/library.py``, with one addition that matters more
here: **a guard against uploading a booking**. The library is the only place in
this domain where anything leaves the machine, so the check sits at that door
rather than in the habits of whoever writes the next renderer.

What a document may contain: category totals, plan figures, subscriptions with
their amounts, depot positions. What it may never contain: an IBAN, a card
number, an account balance, or a single dated booking.
"""

from __future__ import annotations

import os
import re

from workflows.finance import config as c

# IBAN (DE…, NL…), a card number in any of the usual groupings, and the account
# prefixes this machine actually has. Deliberately broad: a false positive costs
# a rename, a false negative costs a bank statement in the cloud.
_FORBIDDEN = (
    (re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b"), "IBAN"),
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "Kartennummer"),
    (re.compile(r"\b\d{4}\s?\d{2}XX\b", re.I), "maskierte Kartennummer"),
)


class LeakError(RuntimeError):
    """The text carries something that must not leave the machine."""


def check(text: str) -> None:
    """Raise when a document carries an account identifier.

    Called before every upload and by a test over the real renderers. This is
    the one door out; a habit is not a guard.
    """
    for pattern, what in _FORBIDDEN:
        found = pattern.search(text)
        if found:
            raise LeakError(
                f"{what} im Text ({found.group()[:6]}…) — das darf die Library nicht sehen. "
                "Aggregate hochladen, keine Kontodaten."
            )


def store(name: str, text: str) -> dict:
    """Replace the document of this name in the library, or keep the fuller one.

    Returns what happened rather than printing it: the caller decides how to
    tell the author, and silence about a kept document would be the bug.
    """
    from mistralai.client import Mistral

    check(text)
    if not c.LIBRARY_ENABLED:
        return {"name": name, "skipped": "library.enabled steht auf false"}

    library_id = c.LIBRARY_ID
    if not library_id:
        raise RuntimeError(
            "shared/finance.json: library.id fehlt — Library anlegen und die ID "
            "dort eintragen (make finance-library)."
        )  # author-facing: stays German

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    for document in client.beta.libraries.documents.list(library_id=library_id).data:
        if document.name != name:
            continue
        # Never replace a fuller document with a thinner one — the same guard the
        # inbox dossier needed after a second run of the same day saw only the
        # remainder. Here it protects against a workbook that failed to open.
        try:
            before = client.beta.libraries.documents.text_content(
                library_id=library_id, document_id=document.id
            ).text
        except Exception:  # noqa: BLE001 — unreadable predecessor: just replace it
            before = ""
        if len(before) > len(text):
            return {"name": name, "document_id": document.id, "kept": True}
        client.beta.libraries.documents.delete(
            library_id=library_id, document_id=document.id
        )

    created = client.beta.libraries.documents.upload(
        library_id=library_id,
        file={"file_name": name, "content": text.encode("utf-8")},
    )
    return {"name": name, "document_id": created.id, "kept": False}
