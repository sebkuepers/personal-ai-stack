"""Direct Gmail tool calls as activities — no reading agent (pattern A).

workflows/CLAUDE.md section 6, pattern A: deterministic calls with known
inputs instead of an agent that discovers the tools itself. Reading is
arithmetic — a reading agent would pay a model to pull numbers that Python
delivers exactly.

Verified live (2026-09-23, measured against the account):
- ``resultCountEstimate`` is useless as a planning figure (constant 201 on
  every non-final page) — paginate until ``nextPageToken`` is missing.
- Without a pause between pages an empty answer eventually comes back (rate
  limit). 1.2 s per page ran through (70 pages in one go).
- ``search_threads`` takes ``query``, ``pageSize`` (max 50), ``pageToken``;
  ``get_thread`` takes ``threadId`` and ``messageFormat``.
- ``list_labels`` returns ``labelId``, not ``id``, and ``create_label``
  requires ``displayName``, not ``name``. Both cost a day.
- A label name may not START with one of Gmail's system labels: ``inbox`` and
  ``inbox/processed`` are both rejected with HTTP 400 "Invalid label name"
  (2026-09-24). See ``RESERVED_LABEL_SEGMENTS``.

Messages that reach the author stay German.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any

import mistralai.workflows as workflows
from mistralai.workflows import Depends
from mistralai.workflows.plugins.mistralai.connectors import ToolCallClient

from . import config
from .connectors import gmail_connector

class GmailToolError(RuntimeError):
    """The connector refused a tool call — it answers as plain text, not as an error field.

    Two different causes have worn this mask, and neither was the code:
    a stale OAuth grant (every write tool refused; re-authorising fixed it),
    and a label name Gmail reserves (see ``RESERVED_LABEL_SEGMENTS``).
    """


# Gmail refuses a user label whose first path segment is one of its system
# labels — ``inbox/processed`` fails with HTTP 400 "Invalid label name", and so
# do ``inbox`` and ``Inbox/processed``. Verified live on 2026-09-24; the error
# names no field, which is why it reads like a broken connector.
RESERVED_LABEL_SEGMENTS = frozenset(
    {
        "inbox",
        "sent",
        "draft",
        "drafts",
        "spam",
        "trash",
        "starred",
        "important",
        "unread",
        "read",
        "chat",
        "chats",
        "category",
    }
)


_PAUSE_SECONDS = 1.2  # without it: empty pages (rate limit) — verified live
_MAX_PAGES = 200  # 200 × 50 = 10,000 threads, a cap against endless loops


def _tool_json(result: Any) -> dict:
    """Extract the JSON from a tool answer (``content[0].text``), in both shapes.

    Depending on the SDK path, ``ToolCallClient.call_tool`` returns the response
    model or its dict — both are accepted here.
    """
    content = getattr(result, "content", None)
    if content is None and isinstance(result, dict):
        content = result.get("content")
    if not content:
        raise RuntimeError(f"Tool answer without content: {str(result)[:200]}")
    first = content[0]
    text = first.get("text") if isinstance(first, dict) else getattr(first, "text", None)
    if not text:
        raise RuntimeError("Tool answer without text in content[0]")
    # The connector reports a failed tool as PLAIN TEXT, not as an error field:
    # "Error calling tool 'create_label'". Without this check json.loads raises a
    # JSONDecodeError, the activity fails, and all Le Chat shows is "Activity
    # task failed" — with no hint which tool and why.
    if text.startswith("Error calling tool"):
        raise GmailToolError(text.strip())
    return json.loads(text)


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(minutes=15),
)
async def gmail_search_threads(
    query: str,
    max_threads: int,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> dict:
    """Paginated ``search_threads`` → ``{"threads": [...], "pages": n, "has_more": bool}``.

    Spam and trash are excluded by Gmail by default; whoever wants them says so
    in the query (``in:anywhere``).

    ``has_more`` says whether ``max_threads`` CUT the result. It used to not:
    the function fetched, sliced to the limit and said nothing, so "7 days, 50
    mails" silently threw away 272 of 322 threads. A cap that cannot report
    that it bit is not a limit, it is a lie.
    """
    threads: list[dict] = []
    token: str | None = None
    pages = 0
    while len(threads) < max_threads and pages < _MAX_PAGES:
        arguments: dict[str, Any] = {"query": query, "pageSize": 50}
        if token:
            arguments["pageToken"] = token
        payload = _tool_json(
            await gmail.call_tool(
                tool_name=config.GMAIL_TOOLS["search"], arguments=arguments
            )
        )
        threads.extend(payload.get("threads") or [])
        token = payload.get("nextPageToken")
        pages += 1
        if not token:
            break
        await asyncio.sleep(_PAUSE_SECONDS)
    # Either a page token is still open (the cap stopped us) or we fetched more
    # than the cap on the last page and are about to slice it away.
    has_more = bool(token) or len(threads) > max_threads
    return {"threads": threads[:max_threads], "pages": pages, "has_more": has_more}


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=90),
)
async def gmail_thread_body(
    thread_id: str,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> str:
    """A thread's last message as text (HTML preferred) — for unsubscribe links.

    Bodies exist only through ``get_thread``; one single promotional mail had
    132,689 characters of HTML. So this is fetched one at a time, never in bulk.
    """
    payload = _tool_json(
        await gmail.call_tool(
            tool_name=config.GMAIL_TOOLS["get"],
            arguments={"threadId": thread_id, "messageFormat": "FULL_CONTENT"},
        )
    )
    thread = payload.get("thread") or payload
    msgs = thread.get("messages") or []
    if not msgs:
        return ""
    m = msgs[-1]
    return m.get("htmlBody") or m.get("plaintextBody") or ""


# --------------------------------------------------------------------------- #
# Writing tools — level 2/3 of the safety ladder. They run ONLY through the
# approved cleanup steps of the conversation, never in the silent run.
# --------------------------------------------------------------------------- #


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=60),
)
async def gmail_ensure_label(
    name: str,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> str:
    """Get the label ID by name — or create the label when it is missing.

    The label names come from ``shared/inbox.json`` (``labels``), never from a
    free source. ``list_labels`` returns user labels only; system labels
    (UNREAD, INBOX, SPAM …) need no IDs.
    """
    first = name.split("/", 1)[0].strip().lower()
    if first in RESERVED_LABEL_SEGMENTS:
        raise GmailToolError(
            f"Gmail reserviert den Namen {first!r} — das Label {name!r} lässt sich nicht "
            "anlegen. Erste Ebene in shared/inbox.json umbenennen."
        )
    # Both field names are verified live and NOT what one would expect:
    # list_labels returns "labelId" (not "id"), and create_label requires
    # "displayName" (not "name"). With the expected names the lookup never
    # found an existing label, and creating one failed schema validation — the
    # whole cleanup step was dead.
    payload = _tool_json(
        await gmail.call_tool(tool_name=config.GMAIL_TOOLS["list_labels"],
                              arguments={"pageSize": "200"})
    )
    for label in payload.get("labels") or []:
        if label.get("name") == name and label.get("labelId"):
            return str(label["labelId"])
    created = _tool_json(
        await gmail.call_tool(
            tool_name=config.GMAIL_TOOLS["create_label"], arguments={"displayName": name}
        )
    )
    label = created.get("label") or created
    label_id = label.get("labelId") or label.get("id") or ""
    if not label_id:
        raise RuntimeError(f"Label {name!r} angelegt, aber keine ID in der Antwort: {created}")
    return str(label_id)


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=60),
)
async def gmail_process_thread(
    thread_id: str,
    label_id: str,
    archive: bool,
    mark_read: bool,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> dict:
    """Set the processed label; optionally mark read (drop UNREAD) and archive (drop INBOX).

    "Mark as read" in Gmail is removing the UNREAD system label, "archive" is
    removing the INBOX label — the label_thread docs name system label IDs
    explicitly. Both are reversible; nothing is ever sent.
    """
    await gmail.call_tool(
        tool_name=config.GMAIL_TOOLS["label_thread"],
        arguments={"threadId": thread_id, "labelIds": [label_id]},
    )
    remove: list[str] = []
    if mark_read:
        remove.append("UNREAD")
    if archive:
        remove.append("INBOX")
    if remove:
        await gmail.call_tool(
            tool_name=config.GMAIL_TOOLS["unlabel_thread"],
            arguments={"threadId": thread_id, "labelIds": remove},
        )
    return {"thread_id": thread_id}


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=60),
)
async def gmail_draft(
    to: str,
    subject: str,
    body: str,
    reply_to_message_id: str | None = None,
    gmail: ToolCallClient = Depends(gmail_connector),
) -> dict:
    """Create a draft — the connector CANNOT send (gotcha 7).

    For mailto unsubscribe links (a human confirms the send) and later for
    pre-written replies (reply_to_message_id).
    """
    arguments: dict[str, Any] = {"to": to, "subject": subject, "body": body}
    if reply_to_message_id:
        arguments["replyToMessageId"] = reply_to_message_id
    payload = _tool_json(
        await gmail.call_tool(tool_name=config.GMAIL_TOOLS["draft"], arguments=arguments)
    )
    return {"draft": payload.get("id") or payload.get("draft", {}).get("id", "")}
