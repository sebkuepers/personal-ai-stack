"""Store the dossier in the Mistral Library — the delivery route for Vibe.

Vibe cannot read local files; the library it can (document_library). The
dossier is a rolling ONE document per day: what stands there is today's state —
the history is in the Studio executions, not in the library. Earlier versions
of the same day are replaced (as in bookcli.sync: "the library never holds two
states").
"""

from __future__ import annotations

from datetime import timedelta

import mistralai.workflows as workflows

from . import config


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=60),
)
async def store_dossier(name: str, text: str) -> dict:
    """Store the dossier as a document in the inbox library; replace the day's predecessor.

    Returns a dict (JSON mode) with name and document ID — clean across the
    sandbox boundary. The library ID comes from ``shared/inbox.json``; if it is
    missing that is a configuration error and the run has to go red instead of
    silently creating a new library (the source of truth is maintained by hand,
    as in bookcli).
    """
    import os

    from mistralai.client import Mistral

    # Explicit, not implicit: relying on the SDK reading MISTRAL_API_KEY from
    # the environment hides a missing key behind an authentication error at the
    # first request instead of naming it here.
    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    lib_id = config.LIBRARY_ID
    if not lib_id:
        raise RuntimeError(
            "shared/inbox.json: mistral.library_id fehlt — Library 'Inbox' anlegen "
            "und die ID dort eintragen."
        )  # author-facing: stays German

    for doc in client.beta.libraries.documents.list(library_id=lib_id).data:
        if doc.name == name:
            client.beta.libraries.documents.delete(library_id=lib_id, document_id=doc.id)

    doc = client.beta.libraries.documents.upload(
        library_id=lib_id,
        file={"file_name": name, "content": text.encode("utf-8")},
    )
    return {"name": name, "document_id": doc.id}
