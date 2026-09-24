"""Checks without discretion — and the work context for those that need it.

What lives here decides **facts**: does a search text occur in the paragraph?
Does a finding change anything at all? Does it reach into direct speech? Does it
cite a rule that exists? These are checks no model is needed for, that are never
uncertain and that cost nothing — they run before every model call.

**Judgements do not live here.** Whether a finding is warranted, or whether one
is missing, is answered by ``book-second-read`` — a second pair of eyes that
sees the same section as the first stage. The predecessor of this file was
called ``judge.py`` and contained both: the invariants and a scoring judge that
ran per finding and received only ``search`` and ``replace``. That it never saw
the sentence it was meant to judge only struck me once the file name stopped
revealing what was inside. So it is now named after what it does.

``work_context`` stays here because it reads the same source as the filters: the
particularities of this work from ``shared/book.json``.
"""

from __future__ import annotations

import re
import unicodedata

from . import config
from .models import JudgedFinding


def split_blocked(
    findings: list[JudgedFinding],
) -> tuple[list[JudgedFinding], list[JudgedFinding]]:
    """Separate findings to display from blocked ones."""
    return (
        [f for f in findings if not f.blocked],
        [f for f in findings if f.blocked],
    )


def drop_without_rule(
    findings: list[JudgedFinding], known_rules: set[str]
) -> tuple[list[JudgedFinding], list[str]]:
    """Discard style suggestions that cite no voice-profile rule.

    This is the enforcement hook behind ``rule_id``: without it the agent cites
    the profile decoratively at best. The exception is findings with severity
    „hoch" — when something is genuinely wrong, a missing rule should not
    swallow it.

    Returns ``(kept, notes)``; the notes say what was dropped and why.
    """
    kept: list[JudgedFinding] = []
    notes: list[str] = []
    for f in findings:
        if f.rule_id and f.rule_id in known_rules:
            kept.append(f)
        elif f.severity == "hoch":
            kept.append(f)
            if f.rule_id and f.rule_id != "kein-bezug":
                notes.append(
                    f"Finding cites unknown rule {f.rule_id!r} — "
                    f"shown anyway because severity is 'hoch'."
                )
        else:
            notes.append(
                f"discarded (no rule reference, severity {f.severity}): {f.search[:60]!r}"
            )
    return kept, notes


def _same(a: str, b: str) -> bool:
    """Whether two passages differ only in Unicode normal form."""
    n = lambda s: unicodedata.normalize("NFC", s).strip()  # noqa: E731
    return n(a) == n(b)


def drop_non_findings(
    findings: list[JudgedFinding],
) -> tuple[list[JudgedFinding], list[str]]:
    """Filter findings that contain no change at all.

    In the first real run the copyedit stage reported a "typography correction"
    whose ``search`` and ``replace`` were character-identical — the model had
    recognised a rule that was already satisfied. That costs trust in every
    other finding and is cheap to catch deterministically.
    """
    kept, notes = [], []
    for f in findings:
        if _same(f.search, f.replace):
            notes.append(f"Non-finding discarded (unchanged): {f.search[:60]!r}")
        else:
            kept.append(f)
    return kept, notes


# Direct speech in this manuscript: „…“
_SPEECH = re.compile(r"„[^“]*“")


def _overlaps(paragraph: str, search: str, match: re.Match[str]) -> bool:
    """Whether a search text touches a speech passage."""
    i = paragraph.find(search)
    if i < 0:
        return False
    return i < match.end() and match.start() < i + len(search)


def drop_edits_in_speech(
    findings: list[JudgedFinding], paragraphs: list[str]
) -> tuple[list[JudgedFinding], list[str]]:
    """Keep the copyedit stage out of direct speech.

    Characters are allowed to speak colloquially — „Ne" instead of „Nein" is
    character speech, not a spelling error. The agent instruction says so
    already; this filter enforces it instead of trusting it. Real typos inside
    speech are lost along with it, and that is the deliberate price.
    """
    kept, notes = [], []
    for f in findings:
        paragraph = paragraphs[f.paragraph_index] if 0 <= f.paragraph_index < len(paragraphs) else ""
        # Overlap, not containment: a search text like 'zu sagen: „Ne' reaches
        # past the speech boundary and would otherwise go undetected.
        in_speech = any(
            _overlaps(paragraph, f.search, match) for match in _SPEECH.finditer(paragraph)
        )
        if in_speech and f.kind in ("rechtschreibung", "grammatik"):
            notes.append(
                f"Left inside direct speech ({f.kind}): {f.search[:50]!r}"
            )
        else:
            kept.append(f)
    return kept, notes


def _changed_words(before: str, after: str) -> list[tuple[str, str]]:
    """The word pairs in which two passages differ.

    Word-wise rather than an exact comparison: the agent delivers ``search``
    sometimes as a bare word („runter"), sometimes embedded („ziehen mich noch
    tiefer runter"). A filter that only matches the bare word then misses.

    Returns an empty list when the word counts differ — then it is not a pure
    word substitution and the case does not belong here.
    """
    a, b = before.split(), after.split()
    if len(a) != len(b):
        return []
    strip = lambda w: w.strip('.,;:!?„“"\'()').lower()  # noqa: E731
    return [
        (strip(x), strip(y))
        for x, y in zip(a, b, strict=True)
        if strip(x) != strip(y)
    ]


def drop_intentional_colloquialisms(
    findings: list[JudgedFinding],
) -> tuple[list[JudgedFinding], list[str]]:
    """Protect the author's colloquialisms from "standardisation".

    The agent knows the rule and even argues in ``why`` why the finding is void
    — but reports it anyway, because its schema has no field for that. A list in
    code is more reliable than the hope that a model stays silent. The pairs
    live in ``shared/book.json`` and can grow there.
    """
    kept, notes = [], []
    for f in findings:
        changed = _changed_words(f.search, f.replace)
        # Only when the ONLY change is a protected pair. A finding that corrects
        # something else on the side is kept.
        if changed and all(
            config.INTENTIONAL_COLLOQUIALISMS.get(old) == new for old, new in changed
        ):
            pairs = ", ".join(f"{old}→{new}" for old, new in changed)
            notes.append(f"Colloquialism protected ({pairs}): {f.search[:50]!r} stays")
        else:
            kept.append(f)
    return kept, notes


# Quotation-mark variants that models silently swap when quoting. The text has
# „…“, the model writes "…" — and an exact comparison then discards a correct
# finding. In the first live run that hit 2 of 4.
_CHARS = str.maketrans({
    "„": '"', "“": '"', "”": '"', "»": '"', "«": '"',
    "‚": "'", "‘": "'", "’": "'", "›": "'", "‹": "'",
    "–": "-", "—": "-", " ": " ",
})


def _flatten(text: str) -> str:
    return text.translate(_CHARS)


def _find_wording(paragraph: str, search: str) -> str | None:
    """The wording in the paragraph that matches the search text but for quotes.

    Returns the ORIGINAL SPELLING from the paragraph, not the model's search
    text — so that everything downstream (display, applying) works exactly on
    the text as it stands. None when not found exactly once.
    """
    flat_paragraph, flat_search = _flatten(paragraph), _flatten(search)
    if len(flat_paragraph) != len(paragraph):
        # translate() substitutes 1:1, so positions stay the same. Should that
        # ever change, better not to normalise at all than to do it wrongly.
        return paragraph if paragraph.count(search) == 1 else None
    if flat_paragraph.count(flat_search) != 1:
        return None
    start = flat_paragraph.index(flat_search)
    return paragraph[start : start + len(search)]


def drop_duplicates(
    findings: list[JudgedFinding],
) -> tuple[list[JudgedFinding], list[str]]:
    """Two findings on the same spot — the second one goes.

    Observed in the log: „Papa warte, ich komme mit" twice, with two
    replacements. When applying, the second would grasp at nothing (the search
    text is gone after the first) — but before that the author has to judge it
    twice. The first wins; that is the one the agent considered important first.
    """
    seen: set[tuple[int, str]] = set()
    kept, notes = [], []
    for f in findings:
        key = (f.paragraph_index, f.search)
        if key in seen:
            notes.append(f"Duplicate discarded: {f.search[:40]!r} (paragraph {f.paragraph_index})")
            continue
        seen.add(key)
        kept.append(f)
    return kept, notes


def fix_paragraph_index(
    findings: list[JudgedFinding], paragraphs: list[str]
) -> tuple[list[JudgedFinding], list[str]]:
    """Verify and repair each finding's ``paragraph_index``.

    The agent does not count reliably: in the first run it reported a finding
    for paragraph 3 whose search text occurs exclusively in paragraph 4. For
    display that is annoying — for the later write-back it would be dangerous,
    because the anchor builds on exactly this.

    So here it is verified instead of trusted:

    * ``search`` occurs exactly once in the stated paragraph → fine.
    * It is not there, but exactly once in **one** other paragraph → the index
      is corrected and the case is reported.
    * It is nowhere, several times in the same paragraph, or in several
      paragraphs → the finding is discarded. Ambiguity is no case for guessing.
    """
    kept, notes = [], []
    for f in findings:
        # Per paragraph: the exact wording, if the search text (but for quotes)
        # occurs in it exactly once.
        hits = {
            i: w for i, p in enumerate(paragraphs) if (w := _find_wording(p, f.search))
        }

        if f.paragraph_index in hits:
            target = f.paragraph_index
        elif len(hits) == 1:
            target = next(iter(hits))
            notes.append(
                f"Paragraph index corrected: {f.paragraph_index} → {target} for {f.search[:40]!r}"
            )
            f.paragraph_index = target
        else:
            total = sum(_flatten(p).count(_flatten(f.search)) for p in paragraphs)
            reason = "not found" if total == 0 else f"{total} times in the section, not unique"
            notes.append(f"discarded ({reason}): {f.search[:50]!r}")
            continue

        wording = hits[target]
        if wording != f.search:
            # From here the finding works with the text as it stands. The
            # replacement gets the same treatment, otherwise a comma finding
            # would swap out the author's quotation marks on the side.
            notes.append(f"Quotation marks aligned: {f.search[:40]!r}")
            f.replace = _align_quotes(f.replace, f.search, wording)
            f.search = wording
        kept.append(f)
    return kept, notes


def _align_quotes(replace: str, old_search: str, wording: str) -> str:
    """Carry the original's quotation marks into the replacement text.

    By ORDER, not via a character table: the model writes the same character "
    for both „ and “, so a table could only ever hit one of them. Instead: at
    which positions does the search text differ from the wording? Those original
    characters are substituted, in order, for the same model characters in the
    replacement. If the replacement has more of them, the rest stays as it is —
    nothing is guessed here.
    """
    if len(old_search) != len(wording):
        return replace
    sequence = [(a, w) for a, w in zip(old_search, wording, strict=True) if a != w]
    if not sequence:
        return replace
    result: list[str] = []
    for char in replace:
        if sequence and char == sequence[0][0]:
            result.append(sequence.pop(0)[1])
        else:
            result.append(char)
    return "".join(result)


def work_context(criterion: str, voice_profile_text: str = "") -> str:
    """The context a criterion needs in order to judge.

    "Is that an error at all?" cannot be answered in general — it depends on the
    work. Without this context the judge measurably considered ``runter`` ->
    ``hinunter`` warranted, because it is standard German. For this work it is
    wrong: in all four measured configurations it failed on exactly these cases.

    The text is German on purpose: it goes into a German prompt about German
    prose.
    """
    if criterion == "stimmtreue":
        return voice_profile_text
    if criterion != "berechtigung":
        return ""
    forms = ", ".join(sorted(config.INTENTIONAL_COLLOQUIALISMS))
    return (
        "GEWOLLTE EIGENHEITEN DIESES WERKS - ihre Korrektur ist KEIN berechtigter Befund:\n"
        f"- Umgangssprachliche Formen im Erzaehltext: {forms}\n"
        "- Umgangssprache in direkter Rede: Figuren sprechen, wie sie sprechen.\n"
        "- Kurze, unvollstaendige Saetze als Stilmittel.\n"
        "- Wiederholung, wenn sie erkennbar Absicht ist.\n"
        "Berechtigt sind nur Verstoesse gegen Rechtschreibung, Zeichensetzung oder "
        "Grammatik, die auch in einem Diktat angestrichen wuerden."
    )
