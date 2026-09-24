"""The Scrivener roundtrip is the riskiest place in the book domain.

This is where the author's manuscript gets written to; a decoding bug is silent
text loss. So these tests run against the **real** project and against an
independent third party (Apple's ``textutil``) instead of against fixtures that
carry the same assumptions as the code.

The tests skip themselves when the project is absent — they are not meant to be
red on someone else's machine.

The German strings in ``pytest.raises(match=…)`` are deliberate: the error
messages of ``scrivener.py`` are read by the author, so they stayed German.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata

import pytest

from workflows.book import config as c
from workflows.book.scrivener import (
    Section,
    check_anchor,
    decode_rtf,
    encode_rtf_text,
    read_binder,
)

SLUG = "immer-wieder-ruegen"

# Minimal document header in the shape Scrivener writes.
HEADER = (
    rb"{\rtf1\ansi\ansicpg1252\cocoartf2870"
    rb"{\fonttbl\f0\froman\fcharset0 Palatino-Roman;}"
    rb"{\colortbl;\red255\green255\blue255;}{\*\expandedcolortbl;;}"
    rb"\pard\f0\fs26 \cf0 "
)


def _package(slug: str = SLUG):
    # The work configuration is gitignored — on a fresh clone (CI) it is missing
    # and scrivener_path() raises before a path could be checked. Both cases
    # mean "not present" and skip the test.
    try:
        path = c.scrivener_path(slug)
    except FileNotFoundError as e:
        pytest.skip(f"Werk-Konfiguration nicht vorhanden: {e}")
    if not path.is_dir():
        pytest.skip(f"Scrivener-Projekt nicht vorhanden: {path}")
    return path


def _norm(t: str) -> str:
    """Comparison form: Unicode NFC, non-breaking space and whitespace unified."""
    t = unicodedata.normalize("NFC", t).replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


@pytest.fixture(scope="module")
def manuscript():
    return read_binder(_package(), SLUG)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_binder_finds_all_chapters(manuscript):
    """The old hand-made export knew only three chapters — the binder walk must find four.

    Exactly that bug is the reason the export is rebuilt on every run and never
    maintained by hand.
    """
    assert manuscript.chapters == [
        "Voll zur Oma",
        "Und jetzt?",
        "Ich sehe nix!",
        "Wir bleiben hier",
    ]


def test_draft_only_no_research_no_trash(manuscript):
    """The package holds considerably more text items than belong to the draft."""
    with_text = [s for s in manuscript.sections if s.has_text]
    assert len(with_text) == 48
    assert all(s.chapter in manuscript.chapters for s in with_text)


def test_path_carries_irregular_outline(manuscript):
    """Chapter 1 has a group level, the others do not — both have to be representable."""
    depths = {len(s.path) for s in manuscript.sections if s.has_text}
    assert depths == {1, 2}, f"unerwartete Gliederungstiefen: {depths}"

    deep = next(s for s in manuscript.sections if s.title == "Einführung Strand")
    assert deep.path == ["Voll zur Oma", "Strand Thiessow"]
    assert deep.chapter == "Voll zur Oma"


def test_synopsis_and_notes_are_read_along(manuscript):
    """Both are raw material for voice profile and content level and must not be lost."""
    assert sum(1 for s in manuscript.sections if s.synopsis) >= 39
    assert sum(1 for s in manuscript.sections if s.notes) >= 36


# ---------------------------------------------------------------------------
# Decoding — against an independent third party
# ---------------------------------------------------------------------------


def test_decoder_agrees_with_textutil():
    """Every content.rtf has to decode character-identically to Apple's converter."""
    package = _package()
    deviations = []
    for f in sorted((package / "Files" / "Data").glob("*/content.rtf")):
        mine = _norm("\n".join(decode_rtf(f.read_bytes())))
        reference = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(f)],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", "replace")
        if mine != _norm(reference):
            deviations.append(f.parent.name)
    assert not deviations, f"Abweichungen gegenüber textutil in: {deviations}"


def test_ignorable_destination_is_discarded():
    """``{\\*\\expandedcolortbl;;}`` must not flush a star into the text.

    Exactly this bug was in the first draft: ``\\*`` is not a control word in the
    sense of ``[a-zA-Z]+`` and slipped through as a literal.
    """
    rtf = HEADER + b"Hallo Welt}"
    assert decode_rtf(rtf) == ["Hallo Welt"]
    assert not decode_rtf(rtf)[0].startswith("*")


def test_unicode_escape_skips_replacement_character():
    """Scrivener writes ``\\u8222?`` — the ``?`` is a replacement character, not text."""
    esc = b"\\"  # assembled deliberately, so no \u pattern appears in this source
    assert decode_rtf(HEADER + esc + b"u8222?Zitat" + esc + b"u8220?}") == ["„Zitat“"]


def test_hex_escape_is_cp1252():
    assert decode_rtf(HEADER + rb"F\'fc\'dfe}") == ["Füße"]


def test_paragraph_breaks():
    """Both ``\\par`` and ``\\`` at end of line separate paragraphs."""
    assert decode_rtf(HEADER + b"Eins\\\nZwei}") == ["Eins", "Zwei"]
    assert decode_rtf(HEADER + rb"Eins\par Zwei}") == ["Eins", "Zwei"]


# ---------------------------------------------------------------------------
# Encoding — the identity the write-back rests on
# ---------------------------------------------------------------------------


def test_encode_decode_is_identity(manuscript):
    """Every paragraph of the manuscript has to survive the encoder losslessly."""
    failures = []
    for s in manuscript.sections:
        for i, paragraph in enumerate(s.paragraphs):
            rtf = HEADER + encode_rtf_text(paragraph).encode("cp1252", "replace") + b"}"
            back = decode_rtf(rtf)
            if not back or back[0] != paragraph:
                failures.append(f"{s.title!r} Absatz {i}")
    assert not failures, f"Roundtrip verletzt bei: {failures[:5]}"


def test_characters_outside_cp1252_survive():
    """``č`` occurs in the manuscript and has to run through the ``\\uNNNN`` path."""
    text = "Ein čech und ein Dash — und „Anführung“."
    rtf = HEADER + encode_rtf_text(text).encode("cp1252", "replace") + b"}"
    assert decode_rtf(rtf) == [text]


def test_curly_braces_are_escaped():
    text = "Ein {Wert} und ein \\ Backslash"
    rtf = HEADER + encode_rtf_text(text).encode("cp1252", "replace") + b"}"
    assert decode_rtf(rtf) == [text]


# ---------------------------------------------------------------------------
# Anchor — the lock against writing on a stale state
# ---------------------------------------------------------------------------


def _demo() -> Section:
    return Section(
        uuid="U" * 32,
        title="Probe",
        path=["Kapitel"],
        paragraphs=["Der Hund bellt. Die Katze schläft.", "Zweiter Absatz."],
        has_text=True,
    )


def test_anchor_accepts_unchanged_paragraph():
    s = _demo()
    check_anchor(s, 0, s.paragraph_hash(0), "Der Hund bellt.")


def test_anchor_rejects_changed_paragraph():
    s = _demo()
    with pytest.raises(ValueError, match="geändert"):
        check_anchor(s, 0, "0" * 16, "Der Hund bellt.")


def test_anchor_rejects_ambiguous_search():
    s = _demo()
    s.paragraphs[0] = "Das Boot. Das Boot."
    with pytest.raises(ValueError, match="nicht eindeutig"):
        check_anchor(s, 0, s.paragraph_hash(0), "Das Boot.")


def test_anchor_rejects_missing_search():
    s = _demo()
    with pytest.raises(ValueError, match="kommt im Absatz nicht vor"):
        check_anchor(s, 0, s.paragraph_hash(0), "Der Vogel singt.")


def test_anchor_rejects_invalid_index():
    s = _demo()
    with pytest.raises(ValueError, match="existiert nicht"):
        check_anchor(s, 99, "irgendwas", "egal")


# ---------------------------------------------------------------------------
# Several works — the outline is not the same in every project
# ---------------------------------------------------------------------------


def test_root_narrows_to_the_manuscript_branch():
    """The autobiography project carries research inside the draft.

    ``Personen``, ``Orte``, ``Unternehmen`` and ``Schlüsselmomente`` sit next to
    the manuscript there and all carry ``IncludeInCompile=Yes`` — without
    ``root`` they would be counted as chapters. That is exactly what the first
    run stumbled over.
    """
    path = _package("autobiographie")

    without = read_binder(path, "autobiographie")
    assert "Personen" in without.chapters, "Vorbedingung: Recherche liegt im Entwurf"

    structure = c.load_work("autobiographie")["structure"]
    with_root = read_binder(
        path,
        "autobiographie",
        root=structure["root"],
        chapter_level=structure["chapter_level"],
    )
    assert with_root.chapters == [
        "1. Die unbeschwerten Jahre",
        "2. Der totale Absturz",
        "3. Der Weg nach Oben",
    ]
    assert "Personen" not in with_root.chapters


def test_unknown_root_fails():
    """A clear error beats a silently empty export."""
    path = _package("autobiographie")
    with pytest.raises(ValueError, match="nicht im Entwurf"):
        read_binder(path, "autobiographie", root="Gibtsnicht")


def test_chapter_level_shifts_the_assignment():
    s = Section(uuid="x", title="t", path=["Sammel", "Kapitel 1"], has_text=True)
    assert s.chapter == "Sammel"
    s.chapter_level = 1
    assert s.chapter == "Kapitel 1"
    s.chapter_level = 5
    assert s.chapter is None
