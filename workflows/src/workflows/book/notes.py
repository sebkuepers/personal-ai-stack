"""Read the author's editing notes — the most valuable raw material in the project.

The ``notes.rtf`` files of the Scrivener project already contain fully worded
editing, written by the author himself, in his own language. The format grew
organically and is remarkably consistent:

    DREIMAL DASSELBE SAGEN          ← the rule, in capitals
    VORHER
    Ich starre auf das tiefblaue und komplett ruhige Meer. …
    NACHHER
    Ich starre auf das Meer. …
    WARUM
    Vier Sätze, und drei davon behaupten dieselbe Stille. …

Alongside them are blocks without a change — ``NICHT ANFASSEN`` (what works),
``ENTSCHEIDUNG: …`` (what was cut and why), ``WAS BLEIBT``. Those are just as
valuable: a style rule that says what must *not* be touched is often more useful
to an editing agent than one that improves something.

The payoff: the voice profile does not start from zero, and not from a writing
guide, but from dozens of real decisions by the author. And the decision log has
labelled examples from day one.

The markers are German because the author's notes are — they are parsed, not
authored, here.

Pure — no model, no network. Testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

# A block heading: its own line, mostly capitals, no sentence ending.
# Allows colon suffixes such as "ENTSCHEIDUNG: DER LOTSENEXKURS GEHT RAUS".
_HEADING = re.compile(r"^(?=.*[A-ZÄÖÜ])[A-ZÄÖÜ0-9ẞß .,:()–—/&'\"-]{4,80}$")

# The markers within a block.
_MARKERS = ("VORHER", "NACHHER", "WARUM")

Kind = Literal["aenderung", "hinweis"]


@dataclass
class EditingNote:
    """A named observation by the author about one section."""

    section_uuid: str
    section_title: str
    rule: str
    kind: Kind
    before: str | None = None
    after: str | None = None
    why: str | None = None
    text: str | None = None  # for hints, the full running text

    @property
    def rule_id(self) -> str:
        """Stable identifier, as the voice profile uses it."""
        s = self.rule.lower()
        for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
            s = s.replace(a, b)
        s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
        return f"N-{s[:48]}"


def _is_heading(line: str) -> bool:
    text = line.strip()
    if not text or text in _MARKERS:
        return False
    if not _HEADING.match(text):
        return False
    # At least most letters upper-case — filters quotes near capitalised text.
    letters = [ch for ch in text if ch.isalpha()]
    return bool(letters) and sum(ch.isupper() for ch in letters) / len(letters) > 0.8


def _split_blocks(note: str) -> list[tuple[str, list[str]]]:
    """Break the note text into (heading, lines) blocks."""
    blocks: list[tuple[str, list[str]]] = []
    current: tuple[str, list[str]] | None = None
    for line in note.splitlines():
        if _is_heading(line):
            if current:
                blocks.append(current)
            current = (line.strip(), [])
        elif current:
            current[1].append(line)
    if current:
        blocks.append(current)
    return blocks


def _split_markers(lines: list[str]) -> dict[str, str]:
    """Split a block at VORHER / NACHHER / WARUM."""
    parts: dict[str, list[str]] = {}
    current: str | None = None
    for line in lines:
        text = line.strip()
        if text in _MARKERS:
            current = text
            parts[current] = []
        elif current:
            parts[current].append(line)
    return {k: "\n".join(v).strip() for k, v in parts.items()}


def read_notes(uuid: str, title: str, note: str | None) -> list[EditingNote]:
    """Parse one section's notes."""
    if not note:
        return []

    result: list[EditingNote] = []
    for heading, lines in _split_blocks(note):
        parts = _split_markers(lines)
        if parts.get("VORHER") and parts.get("NACHHER"):
            result.append(
                EditingNote(
                    section_uuid=uuid,
                    section_title=title,
                    rule=heading,
                    kind="aenderung",
                    before=parts["VORHER"],
                    after=parts["NACHHER"],
                    why=parts.get("WARUM"),
                )
            )
        else:
            body = "\n".join(lines).strip()
            if body:
                result.append(
                    EditingNote(
                        section_uuid=uuid,
                        section_title=title,
                        rule=heading,
                        kind="hinweis",
                        text=body,
                    )
                )
    return result


def all_notes(manuscript) -> list[EditingNote]:  # noqa: ANN001 — Manuscript, avoids a cycle
    """Collect the notes of the whole work."""
    return [
        n
        for s in manuscript.sections
        for n in read_notes(s.uuid, s.title, s.notes)
    ]


def frequent_rules(notes: list[EditingNote], at_least: int = 2) -> list[tuple[str, int]]:
    """Rule names the author assigned more than once — the candidates for the profile.

    A rule he named three times independently carries more weight than anything
    a model distils from the text.
    """
    counts: dict[str, int] = {}
    for n in notes:
        key = n.rule.split(":")[0].strip()
        counts[key] = counts.get(key, 0) + 1
    return sorted(
        ((k, v) for k, v in counts.items() if v >= at_least),
        key=lambda kv: (-kv[1], kv[0]),
    )
