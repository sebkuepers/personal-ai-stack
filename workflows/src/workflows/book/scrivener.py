"""Read and write Scrivener — the only place that knows the ``.scriv``.

**Purely local.** The production worker runs in the Cloudflare container and has
no access to the author's file system; this module is therefore used only by
``bookcli``, never from inside a workflow.

Two things you have to know about the format before changing anything here —
both measured against the real project, not taken from documentation:

1. **The binder is the truth, not ``Files/Data/``.** The package holds 73 text
   items, but only 54 belong to the draft; the rest sits in *research* and in
   the *trash*. Walking ``Files/Data/*`` exports deleted versions along with the
   rest. Hence: downwards from the ``DraftFolder`` through the binder structure.

2. **The outline depth is irregular.** Chapter 1 has a group level, the other
   chapters do not. A fixed chapter/group/section triple breaks on that. The
   canonical model is therefore a *flat* section list in which every section
   carries its own ``path``.

The RTF is pleasantly plain: the entire draft contains not a single character
style (the few ``\\i``/``\\qc`` sit exclusively in the hand-built document
"Titel"). The decoder therefore only needs to handle escapes, paragraph
boundaries and groups — but those exactly.

Error messages stay German: they surface in ``make book-*`` and are read by the
author, not by a log aggregator.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """A text item of the draft, with its way through the outline."""

    uuid: str
    title: str
    path: list[str]
    paragraphs: list[str] = field(default_factory=list)
    synopsis: str | None = None
    notes: str | None = None
    has_text: bool = False
    chapter_level: int = 0
    label: str = ""
    status: str = ""
    is_folder: bool = False
    """An outline node with children.

    Important for anything reporting "text is still missing here": a chapter
    folder never has text of its own and is therefore structure, not a gap.
    """

    @property
    def chapter(self) -> str | None:
        """The outline level that denotes a chapter in this work.

        Not every project puts chapters directly under the draft: "Immer wieder
        Rügen" does (level 0), the autobiography project pushes a collecting
        folder "Kapitel" in between (level 1). Hence configurable instead of
        guessed.
        """
        return self.path[self.chapter_level] if len(self.path) > self.chapter_level else None

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def words(self) -> int:
        return len(self.text.split())

    def paragraph_hash(self, index: int) -> str:
        """Anchor for the write-back — see :func:`check_anchor`."""
        return hashlib.sha256(self.paragraphs[index].encode("utf-8")).hexdigest()[:16]


@dataclass
class Manuscript:
    """A work's complete draft at one point in time."""

    slug: str
    scrivx: Path
    sections: list[Section]

    @property
    def chapters(self) -> list[str]:
        """Chapter titles in binder order, without duplicates."""
        seen: list[str] = []
        for s in self.sections:
            if s.chapter and s.chapter not in seen:
                seen.append(s.chapter)
        return seen

    @property
    def words(self) -> int:
        return sum(s.words for s in self.sections)

    def by_uuid(self, uuid: str) -> Section | None:
        return next((s for s in self.sections if s.uuid == uuid), None)

    def in_chapter(self, chapter: str) -> list[Section]:
        return [s for s in self.sections if s.chapter == chapter]

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "chapters": self.chapters,
            "words": self.words,
            "sections": [
                {
                    "uuid": s.uuid,
                    "title": s.title,
                    "path": s.path,
                    "words": s.words,
                    "synopsis": s.synopsis,
                    "notes": s.notes,
                    "paragraphs": [
                        {"index": i, "text": t, "sha256": s.paragraph_hash(i)}
                        for i, t in enumerate(s.paragraphs)
                    ],
                }
                for s in self.sections
                if s.has_text
            ],
        }


# ---------------------------------------------------------------------------
# Decode RTF
# ---------------------------------------------------------------------------

# A control word, optionally with a numeric parameter; exactly one following
# space is then swallowed as the delimiter (RTF rule).
_CONTROL_WORD = re.compile(r"\\([a-zA-Z]+)(-?\d+)?[ ]?")
# \'xx — one byte in the document's code page (here cp1252).
_HEX_ESCAPE = re.compile(r"\\'([0-9a-fA-F]{2})")

# Control words whose group content is discarded entirely (tables, metadata).
_DISCARD = {"fonttbl", "colortbl", "expandedcolortbl", "stylesheet", "info", "*"}
# Control words that mean a paragraph break.
_PARAGRAPH = {"par", "line"}


def decode_rtf(raw: bytes) -> list[str]:
    """Turn ``content.rtf`` into a list of paragraphs.

    Handles exactly the constructs that occur in this project: ``\\'xx``
    (cp1252), ``\\uNNNN`` together with the replacement character to skip,
    ``\\par``/``\\line`` as well as ``\\`` at end of line as a paragraph break,
    and curly groups including the tables to be discarded.

    Deliberately conservative: unknown control words are ignored, not guessed.
    """
    s = raw.decode("cp1252", errors="replace")
    paragraphs: list[str] = []
    buffer: list[str] = []
    depth = 0
    # Depth from which we discard (None = we keep everything).
    discard_from: int | None = None
    i = 0
    n = len(s)

    while i < n:
        c = s[i]

        if c == "{":
            depth += 1
            i += 1
            continue

        if c == "}":
            if discard_from is not None and depth <= discard_from:
                discard_from = None
            depth -= 1
            i += 1
            continue

        if c == "\\":
            # Escaped special characters: \\ \{ \}
            if i + 1 < n and s[i + 1] in "\\{}":
                if discard_from is None:
                    buffer.append(s[i + 1])
                i += 2
                continue

            # \* marks an ignorable destination ({\*\expandedcolortbl;;}).
            # The star is not a control word and would otherwise slip through
            # as text.
            if i + 1 < n and s[i + 1] == "*":
                if discard_from is None:
                    discard_from = depth
                i += 2
                continue

            # \ immediately before a line break = paragraph break.
            if i + 1 < n and s[i + 1] in "\r\n":
                if discard_from is None:
                    paragraphs.append("".join(buffer))
                    buffer = []
                i += 2
                if i < n and s[i - 1] == "\r" and s[i] == "\n":
                    i += 1
                continue

            m = _HEX_ESCAPE.match(s, i)
            if m:
                if discard_from is None:
                    buffer.append(bytes([int(m.group(1), 16)]).decode("cp1252", "replace"))
                i = m.end()
                continue

            m = _CONTROL_WORD.match(s, i)
            if not m:
                i += 1
                continue

            word, param = m.group(1), m.group(2)
            i = m.end()

            if word == "u":
                # \uNNNN + exactly one replacement character to skip
                # (Scrivener writes an implicit \uc1, e.g. "\u8222?").
                if discard_from is None and param is not None:
                    code = int(param)
                    if code < 0:  # RTF writes >32767 as a negative number
                        code += 65536
                    buffer.append(chr(code))
                if i < n and s[i] not in "\\{}":
                    i += 1
                continue

            if word in _DISCARD and discard_from is None:
                discard_from = depth
                continue

            if word in _PARAGRAPH and discard_from is None:
                paragraphs.append("".join(buffer))
                buffer = []
                continue

            # All remaining control words (font, indent, colour …) carry no
            # text and are passed over.
            continue

        # Raw line breaks are pure formatting in RTF, not text content.
        if c in "\r\n":
            i += 1
            continue

        if discard_from is None:
            buffer.append(c)
        i += 1

    paragraphs.append("".join(buffer))

    # Tidy up: trim the edges and drop empty paragraphs.
    return [p.strip() for p in paragraphs if p.strip()]


def encode_rtf_text(text: str) -> str:
    """Encode running text back into RTF escapes.

    Counterpart to :func:`decode_rtf` for a single paragraph. Anything that is
    not ASCII is written as ``\\'xx`` (where representable in cp1252) or as
    ``\\uNNNN?`` — with the replacement character the decoder skips again.
    """
    out: list[str] = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            try:
                out.append(f"\\'{ch.encode('cp1252')[0]:02x}")
            except (UnicodeEncodeError, IndexError):
                out.append(f"\\u{ord(ch)}?")
    return "".join(out)


def find_span(raw: bytes, paragraph_index: int, search: str) -> tuple[int, int]:
    """The byte span that ``search`` occupies in paragraph ``paragraph_index``.

    The core of the write-back. Instead of regenerating the file — which would
    lose every piece of formatting this module does not know about — exactly the
    range carrying the search text is replaced. Every other byte stays as it is.

    This is possible because the decoder works on a cp1252-decoded string: one
    character position in it is exactly one byte in the file. The decoder is run
    a second time here, this time keeping a position trace per character.

    :raises ValueError: when the paragraph is missing or the search text does
        not occur there exactly once. No fuzzy matching — an anchor that does
        not sit unambiguously is no anchor.
    """
    paragraphs, traces = _decode_with_trace(raw)
    if not 0 <= paragraph_index < len(paragraphs):
        raise ValueError(f"Absatz {paragraph_index} gibt es nicht (nur {len(paragraphs)}).")

    paragraph, trace = paragraphs[paragraph_index], traces[paragraph_index]
    hits = paragraph.count(search)
    if hits != 1:
        raise ValueError(
            f"Suchtext kommt in Absatz {paragraph_index} {hits}-mal vor — nicht eindeutig."
        )

    start = paragraph.index(search)
    # The trace carries the start AND end byte of every character. Remembering
    # only the start was not enough: if the search text ends on a multi-byte
    # escape (\uNNNN? for a typographic quotation mark), the span cut into the
    # middle of it and left a remnant behind. Found on exactly one of 57
    # inspected paragraphs — the only one whose search text ended on such a
    # character.
    return trace[start][0], trace[start + len(search) - 1][1]


def _decode_with_trace(raw: bytes) -> tuple[list[str], list[list[tuple[int, int]]]]:
    """Like :func:`decode_rtf`, but also returns, per paragraph, the byte span
    ``(from, to)`` of every character.

    Deliberately a second function rather than a flag on the decoder: that one
    is covered by 20 tests, and the write-back is the only place that needs the
    trace. If the decoder changes, this function has to be dragged along — the
    tests for this module check exactly that.
    """
    s = raw.decode("cp1252", errors="replace")
    paragraphs: list[str] = []
    traces: list[list[tuple[int, int]]] = []
    buffer: list[str] = []
    trace: list[tuple[int, int]] = []
    depth = 0
    discard_from: int | None = None
    i, n = 0, len(s)

    def close_paragraph() -> None:
        paragraphs.append("".join(buffer))
        traces.append(list(trace))
        buffer.clear()
        trace.clear()

    while i < n:
        c = s[i]
        if c == "{":
            depth += 1
            i += 1
            continue
        if c == "}":
            if discard_from is not None and depth <= discard_from:
                discard_from = None
            depth -= 1
            i += 1
            continue

        if c == "\\":
            if i + 1 < n and s[i + 1] in "\\{}":
                if discard_from is None:
                    buffer.append(s[i + 1])
                    trace.append((i, i + 2))
                i += 2
                continue
            if i + 1 < n and s[i + 1] == "*":
                if discard_from is None:
                    discard_from = depth
                i += 2
                continue
            if i + 1 < n and s[i + 1] in "\r\n":
                if discard_from is None:
                    close_paragraph()
                i += 2
                if i < n and s[i - 1] == "\r" and s[i] == "\n":
                    i += 1
                continue

            m = _HEX_ESCAPE.match(s, i)
            if m:
                if discard_from is None:
                    buffer.append(bytes([int(m.group(1), 16)]).decode("cp1252", "replace"))
                    trace.append((i, m.end()))
                i = m.end()
                continue

            m = _CONTROL_WORD.match(s, i)
            if not m:
                i += 1
                continue
            word, param = m.group(1), m.group(2)
            start = i
            i = m.end()

            if word == "u":
                keep = discard_from is None and param is not None
                if keep:
                    code = int(param)
                    if code < 0:
                        code += 65536
                    buffer.append(chr(code))
                # The replacement character is part of the encoding of this one
                # character and has to disappear along with it when replacing.
                if i < n and s[i] not in "\\{}":
                    i += 1
                if keep:
                    trace.append((start, i))
                continue
            if word in _DISCARD and discard_from is None:
                discard_from = depth
                continue
            if word in _PARAGRAPH and discard_from is None:
                close_paragraph()
                continue
            continue

        if c in "\r\n":
            i += 1
            continue
        if discard_from is None:
            buffer.append(c)
            trace.append((i, i + 1))
        i += 1

    close_paragraph()

    # The same tidying as decode_rtf — trim edges, drop empty paragraphs. The
    # trace has to move along exactly, otherwise it points at the wrong bytes.
    done_text: list[str] = []
    done_trace: list[list[tuple[int, int]]] = []
    for text, tr in zip(paragraphs, traces, strict=True):
        if not text.strip():
            continue
        lead = len(text) - len(text.lstrip())
        trail = len(text) - len(text.rstrip())
        done_text.append(text[lead : len(text) - trail])
        done_trace.append(tr[lead : len(tr) - trail])
    return done_text, done_trace


def replace_in_rtf(raw: bytes, paragraph_index: int, search: str, replacement: str) -> bytes:
    """Replace a passage in the original bytes and leave everything else alone.

    The result is decoded again by the caller and held against the expectation —
    see ``bookcli.apply``. Only when that matches is the file overwritten.
    """
    start, end = find_span(raw, paragraph_index, search)
    new = encode_rtf_text(replacement).encode("cp1252", errors="replace")
    return raw[:start] + new + raw[end:]


# ---------------------------------------------------------------------------
# Read the binder
# ---------------------------------------------------------------------------


def _data_file(package: Path, uuid: str, name: str) -> Path:
    return package / "Files" / "Data" / uuid / name


def _read_synopsis(package: Path, uuid: str) -> str | None:
    p = _data_file(package, uuid, "synopsis.txt")
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else None


def _read_notes(package: Path, uuid: str) -> str | None:
    p = _data_file(package, uuid, "notes.rtf")
    if not p.is_file():
        return None
    return "\n\n".join(decode_rtf(p.read_bytes())).strip() or None


def _read_complete(file: Path, attempts: int = 4) -> bytes:
    """Read an RTF file, waiting briefly if Scrivener is writing right now.

    Scrivener saves after a typing pause; read in exactly that moment and you
    get half a file — which decodes either to garbage or to a paragraph that
    ends mid-sentence, without an error. An RTF file always ends with ``}``. If
    that is missing the file is not finished: wait briefly, read again. After
    the last attempt it raises instead of guessing.
    """
    import time

    for attempt in range(attempts):
        raw = file.read_bytes()
        if raw.rstrip().endswith(b"}"):
            return raw
        if attempt < attempts - 1:
            time.sleep(0.25 * (attempt + 1))
    raise OSError(
        f"{file.name}: Datei endet nicht mit '}}' — Scrivener schreibt vermutlich gerade. "
        "Kurz warten und erneut versuchen."
    )


def _vocabulary(tree: ET.Element, block: str, entry: str) -> dict[str, str]:
    """A project's label or status list as ``{ID: name}``.

    Scrivener keeps both as freely nameable lists in ``<LabelSettings>`` and
    ``<StatusSettings>``; the items only reference them by ID. They therefore
    live here and not in the config: the author maintains them in Scrivener, and
    a copy in the repo would be stale immediately.
    """
    el = tree.find(".//" + block)
    if el is None:
        return {}
    return {
        e.get("ID", ""): (e.text or "").strip()
        for e in el.iter(entry)
        if e.get("ID") is not None
    }


def read_binder(
    package: Path,
    slug: str,
    *,
    only_with_text: bool = False,
    root: str | None = None,
    chapter_level: int = 0,
) -> Manuscript:
    """Read the draft of a Scrivener project.

    Walks downwards from the ``DraftFolder`` and honours ``IncludeInCompile``;
    folders contribute to the ``path``, text items become a :class:`Section`.
    Items without ``content.rtf`` (pure outline nodes) are kept with
    ``has_text=False`` so that the structure stays fully visible.

    ``root`` narrows to a named folder below the draft. That is needed when the
    draft holds research alongside the manuscript — the autobiography project
    keeps ``Personen``, ``Orte``, ``Unternehmen`` and ``Schlüsselmomente``
    there, which are not manuscript text but all carry ``IncludeInCompile=Yes``
    and would otherwise be counted as chapters.

    ``chapter_level`` says which path level denotes a chapter (see
    :attr:`Section.chapter`).
    """
    scrivx = next(package.glob("*.scrivx"), None)
    if scrivx is None:
        raise FileNotFoundError(f"Keine .scrivx-Datei in {package}")

    tree = ET.parse(scrivx).getroot()
    labels = _vocabulary(tree, "LabelSettings", "Label")
    states = _vocabulary(tree, "StatusSettings", "Status")
    draft = next(
        (b for b in tree.iter("BinderItem") if b.get("Type") == "DraftFolder"), None
    )
    if draft is None:
        raise ValueError(f"Kein DraftFolder im Binder von {scrivx}")

    sections: list[Section] = []

    def walk(node: ET.Element, path: list[str]) -> None:
        children = node.find("Children")
        if children is None:
            return
        for item in children:
            if item.tag != "BinderItem":
                continue
            meta = item.find("MetaData")
            if meta is not None:
                flag = meta.find("IncludeInCompile")
                if flag is not None and (flag.text or "").strip().lower() == "no":
                    continue

            title_el = item.find("Title")
            title = (title_el.text or "").strip() if title_el is not None else ""
            uuid = item.get("UUID") or ""
            rtf = _data_file(package, uuid, "content.rtf")
            # If the ID is missing the author set nothing — Scrivener then shows
            # the first entry of the list, i.e. the default.
            label = labels.get((meta.findtext("LabelID") or "-1") if meta is not None else "-1", "")
            status = states.get((meta.findtext("StatusID") or "-1") if meta is not None else "-1", "")
            children_el = item.find("Children")
            is_folder = children_el is not None and len(children_el) > 0

            if rtf.is_file():
                sections.append(
                    Section(
                        uuid=uuid,
                        title=title,
                        path=list(path),
                        paragraphs=decode_rtf(_read_complete(rtf)),
                        synopsis=_read_synopsis(package, uuid),
                        notes=_read_notes(package, uuid),
                        has_text=True,
                        chapter_level=chapter_level,
                        label=label,
                        status=status,
                        is_folder=is_folder,
                    )
                )
            elif not only_with_text:
                sections.append(
                    Section(
                        uuid=uuid,
                        title=title,
                        path=list(path),
                        synopsis=_read_synopsis(package, uuid),
                        notes=_read_notes(package, uuid),
                        has_text=False,
                        chapter_level=chapter_level,
                        label=label,
                        status=status,
                        is_folder=is_folder,
                    )
                )

            # Folders and group nodes extend the path for their children.
            walk(item, [*path, title] if title else list(path))

    start = draft
    if root:
        found = next(
            (
                b
                for b in draft.iter("BinderItem")
                if (b.find("Title") is not None and (b.find("Title").text or "").strip() == root)
            ),
            None,
        )
        if found is None:
            raise ValueError(f"Ordner {root!r} nicht im Entwurf von {scrivx.name} gefunden")
        start = found

    walk(start, [])
    return Manuscript(slug=slug, scrivx=scrivx, sections=sections)


# ---------------------------------------------------------------------------
# Anchor for the write-back
# ---------------------------------------------------------------------------


def check_anchor(
    section: Section, paragraph_index: int, expected_hash: str, search: str
) -> None:
    """Make sure a change still fits the text it refers to.

    Four conditions, all hard: the paragraph exists, its hash still matches, the
    search text occurs, and it occurs **exactly once**. If one fails it aborts
    instead of guessing — there is deliberately no fuzzy matching here.

    :raises ValueError: with a message that names the section.
    """
    where = f"{section.title!r} ({section.uuid[:8]}), Absatz {paragraph_index}"

    if not 0 <= paragraph_index < len(section.paragraphs):
        raise ValueError(f"{where}: Absatz existiert nicht (nur {len(section.paragraphs)}).")

    actual = section.paragraph_hash(paragraph_index)
    if actual != expected_hash:
        raise ValueError(
            f"{where}: Der Absatz wurde seit der Analyse geändert "
            f"(erwartet {expected_hash}, ist {actual}). Abschnitt neu analysieren."
        )

    hits = section.paragraphs[paragraph_index].count(search)
    if hits == 0:
        raise ValueError(f"{where}: Suchtext kommt im Absatz nicht vor.")
    if hits > 1:
        raise ValueError(f"{where}: Suchtext kommt {hits}-mal vor — nicht eindeutig.")


def normalise(text: str) -> str:
    """Unicode normal form for comparisons between decoders."""
    return unicodedata.normalize("NFC", text)
