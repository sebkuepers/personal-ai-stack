"""The Gmail layer had no tests, and two of the six bugs lived there.

What is testable without the network is the part that decides: how a tool
answer is unwrapped, and which field names the label handling reads and writes.
Both were wrong, both were invisible, and both killed the whole cleanup step.

The field names are pinned against the values measured live on 2026-09-23, so
that a future rewrite cannot quietly guess them again.
"""

from __future__ import annotations

import json

import pytest

from workflows.inbox import config
from workflows.inbox.gmail import _tool_json


# ---------------------------------------------------------------------------
# Unwrapping a tool answer
# ---------------------------------------------------------------------------


class _Chunk:
    """A response object with ``.text`` — the shape the SDK returns."""

    def __init__(self, text: str) -> None:
        self.text = text


class _Response:
    def __init__(self, content: list) -> None:
        self.content = content


def test_tool_json_reads_the_object_form():
    payload = {"threads": [{"id": "t1"}]}
    assert _tool_json(_Response([_Chunk(json.dumps(payload))])) == payload


def test_tool_json_reads_the_dict_form():
    """Depending on the SDK path the same answer arrives as a plain dict."""
    payload = {"threads": []}
    assert _tool_json({"content": [{"text": json.dumps(payload)}]}) == payload


def test_tool_json_names_the_answer_when_content_is_missing():
    """A tool error arrives as an answer without content — it must not pass silently."""
    with pytest.raises(RuntimeError, match="without content"):
        _tool_json({"something": "else"})


def test_tool_json_names_the_answer_when_text_is_missing():
    with pytest.raises(RuntimeError, match="without text"):
        _tool_json({"content": [{"no_text": 1}]})


# ---------------------------------------------------------------------------
# The label field names — the bug that killed the cleanup step
# ---------------------------------------------------------------------------


def test_list_labels_is_read_as_labelId():
    """``list_labels`` returns ``labelId``, not ``id`` — measured live.

    Reading ``id`` returns None for every label, so the lookup never finds an
    existing one and always tries to create it.
    """
    label = {"labelId": "Label_3", "name": "inbox/processed"}
    assert label.get("id") is None
    assert label.get("labelId") == "Label_3"

    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src" / "workflows" / "inbox" / "gmail.py"
    ).read_text(encoding="utf-8")
    assert 'label.get("labelId")' in source, "gmail_ensure_label has to read labelId"
    assert 'label.get("id") == name' not in source


def test_create_label_is_called_with_displayName():
    """``create_label`` requires ``displayName``; ``name`` fails schema validation."""
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "src" / "workflows" / "inbox" / "gmail.py"
    ).read_text(encoding="utf-8")
    assert '"displayName": name' in source
    assert 'arguments={"name": name}' not in source


# ---------------------------------------------------------------------------
# Tool names come from the configuration, never from a literal
# ---------------------------------------------------------------------------


def test_every_gmail_tool_used_is_configured():
    """The module addresses tools only through ``config.GMAIL_TOOLS``.

    A literal tool name in the code is how ``search_gmail`` survived in
    shared/crm.json for weeks without existing.
    """
    needed = {"search", "get", "draft", "list_labels", "create_label",
              "label_thread", "unlabel_thread"}
    assert needed <= set(config.GMAIL_TOOLS), (
        f"missing in shared/inbox.json: {sorted(needed - set(config.GMAIL_TOOLS))}"
    )


def test_configured_tool_names_are_the_live_ones():
    """Pinned against ``connectors.list_tools`` of 2026-09-23.

    Not a style question: the predecessors (``search_gmail``,
    ``open_gmail_email``, ``draft_gmail_email``) do not exist on the account.
    """
    assert config.GMAIL_TOOLS["search"] == "search_threads"
    assert config.GMAIL_TOOLS["get"] == "get_thread"
    assert config.GMAIL_TOOLS["draft"] == "create_draft"
    assert config.GMAIL_TOOLS["list_labels"] == "list_labels"
    assert config.GMAIL_TOOLS["create_label"] == "create_label"
