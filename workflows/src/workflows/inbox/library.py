"""Dossier-Ablage in die Mistral Library — der Zustellweg für Vibe.

Vibe kann lokale Dateien nicht lesen; die Library kann es (document_library).
Das Dossier ist rollierend EIN Dokument pro Tag: Gestanden ist, was heute
drinsteht — die Geschichte steckt in den Studio-Ausführungen, nicht in der
Library. Frühere Fassungen desselben Tages werden ersetzt (wie bookcli.sync:
„die Library enthält nie zwei Stände").
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
    """Legt das Dossier als Dokument in die Inbox-Library; ersetzt Tages-Vorläufer.

    Returns ein dict (JSON mode) mit Name und Dokument-ID — sauber über die
    Sandbox-Grenze. Die Library-ID kommt aus ``shared/inbox.json``; fehlt sie,
    ist das ein Konfigurationsfehler und der Lauf muss rot werden, statt
    heimlich eine neue Library anzulegen (die Quelle der Wahrheit wird von
    Hand gepflegt, wie bei bookcli).
    """
    from mistralai.client import Mistral

    client = Mistral()
    lib_id = config.LIBRARY_ID
    if not lib_id:
        raise RuntimeError(
            "shared/inbox.json: mistral.library_id fehlt — Library 'Inbox' anlegen "
            "und die ID dort eintragen."
        )

    for doc in client.beta.libraries.documents.list(library_id=lib_id).data:
        if doc.name == name:
            client.beta.libraries.documents.delete(library_id=lib_id, document_id=doc.id)

    doc = client.beta.libraries.documents.upload(
        library_id=lib_id,
        file={"file_name": name, "content": text.encode("utf-8")},
    )
    return {"name": name, "document_id": doc.id}
