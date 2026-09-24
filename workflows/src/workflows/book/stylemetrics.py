"""Deterministic style metrics — measure before a model interprets.

The reason for this module: ask a language model to "describe this author's
voice" and you get *"warm, humorous, concrete images, short sentences"*. That is
true, useless and above all **not violable** — a rule you cannot break cannot
detect a breach either.

These numbers turn it into something checkable: not "short sentences" but
"median 11 words, 18 % of sentences at most 5 words long, the longest in the
book has 46". A style agent can actually measure against that, and a reviewer
can contradict it.

Everything here is pure: no model, no network, no randomness. That makes the
values reproducible and puts them in the deterministic part of a workflow.

The regexes and the word lists are German because the manuscript is; and
:meth:`StyleMetrics.as_text` stays German because its output goes straight into
a German agent prompt.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

# Sentence end: . ! ? … followed by whitespace. Abbreviations containing a full
# stop (z. B., d. h.) are protected beforehand, otherwise sentences fall apart
# at them.
_ABBREVIATIONS = [
    "z. B.", "z.B.", "d. h.", "d.h.", "u. a.", "u.a.", "bzw.", "ca.", "vgl.",
    "Nr.", "Dr.", "Prof.", "St.", "ggf.", "inkl.", "evtl.", "usw.", "etc.",
]
_SENTINEL = ""

_SENTENCE_END = re.compile(r"(?<=[.!?…])[\s]+(?=[„\"»'(\[]?[A-ZÄÖÜ0-9])")
_WORD = re.compile(r"[\wÄÖÜäöüß-]+", re.UNICODE)

# German quotation: „…“ — the marker for direct speech in this manuscript.
_SPEECH = re.compile(r"„[^“]{2,}“")

_NOMINAL_STYLE = re.compile(r"\b\w{4,}(ung|heit|keit|nis|tum|schaft)(en)?\b", re.IGNORECASE)
_PASSIVE = re.compile(r"\b(wurde|wurden|wird|werden)\b\s+(?:\w+\s+){0,3}?ge\w+t?\b", re.IGNORECASE)
_FILLER_WORDS = [
    "eigentlich", "irgendwie", "quasi", "sozusagen", "halt", "eben", "ja",
    "wohl", "durchaus", "relativ", "ziemlich", "recht", "etwas", "einfach",
    "natürlich", "tatsächlich", "vielleicht", "offensichtlich", "mittlerweile",
]


def sentences(text: str) -> list[str]:
    """Split text into sentences, protecting common German abbreviations."""
    protected = text
    for a in _ABBREVIATIONS:
        protected = protected.replace(a, a.replace(".", _SENTINEL))
    parts = _SENTENCE_END.split(protected)
    return [p.replace(_SENTINEL, ".").strip() for p in parts if p.strip()]


def words(text: str) -> list[str]:
    return _WORD.findall(text)


@dataclass
class StyleMetrics:
    """Measurable properties of a text corpus."""

    sections: int = 0
    paragraphs: int = 0
    sentences: int = 0
    words: int = 0

    sentence_median: float = 0.0
    sentence_mean: float = 0.0
    sentence_shortest: int = 0
    sentence_longest: int = 0
    sentence_longest_text: str = ""
    share_short_sentences: float = 0.0  # <= 5 words
    share_long_sentences: float = 0.0  # >= 25 words
    sentence_length_histogram: dict[str, int] = field(default_factory=dict)

    paragraph_median_sentences: float = 0.0
    paragraph_median_words: float = 0.0

    share_i_openings: float = 0.0
    share_conjunction_openings: float = 0.0
    dialogue_share: float = 0.0

    nominal_style_per_1000: float = 0.0
    passive_per_1000: float = 0.0
    filler_words_per_1000: float = 0.0
    type_token_ratio: float = 0.0

    punctuation: dict[str, int] = field(default_factory=dict)
    most_frequent_trigrams: list[tuple[str, int]] = field(default_factory=list)
    most_frequent_openings: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def as_text(self) -> str:
        """Compact rendering for an agent's prompt — German, because the prompt is."""
        return "\n".join(
            [
                f"Korpus: {self.sections} Abschnitte, {self.paragraphs} Absätze, "
                f"{self.sentences} Sätze, {self.words} Wörter.",
                f"Satzlänge: Median {self.sentence_median:.0f} Wörter, "
                f"Mittel {self.sentence_mean:.1f}, "
                f"kürzester {self.sentence_shortest}, längster {self.sentence_longest}.",
                f"Kurze Sätze (≤5 Wörter): {self.share_short_sentences:.0%}. "
                f"Lange Sätze (≥25 Wörter): {self.share_long_sentences:.0%}.",
                f"Absatz: Median {self.paragraph_median_sentences:.0f} Sätze / "
                f"{self.paragraph_median_words:.0f} Wörter.",
                f"Sätze, die mit „Ich“ beginnen: {self.share_i_openings:.0%}; "
                f"mit „Und“/„Aber“: {self.share_conjunction_openings:.0%}.",
                f"Anteil direkter Rede an allen Sätzen: {self.dialogue_share:.0%}.",
                f"Nominalstil: {self.nominal_style_per_1000:.1f}/1000 Wörter. "
                f"Passiv: {self.passive_per_1000:.1f}/1000. "
                f"Füllwörter: {self.filler_words_per_1000:.1f}/1000.",
                f"Type-Token-Ratio: {self.type_token_ratio:.3f}.",
                f"Längster Satz: „{self.sentence_longest_text[:200]}“",
            ]
        )


def _histogram(lengths: list[int]) -> dict[str, int]:
    buckets = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 35), (36, 999)]
    out: dict[str, int] = {}
    for lo, hi in buckets:
        name = f"{lo}-{hi}" if hi < 999 else f"{lo}+"
        out[name] = sum(1 for x in lengths if lo <= x <= hi)
    return out


def measure(paragraphs: list[str], *, sections: int = 0) -> StyleMetrics:
    """Compute all metrics over a list of paragraphs."""
    m = StyleMetrics(sections=sections, paragraphs=len(paragraphs))
    if not paragraphs:
        return m

    full_text = "\n\n".join(paragraphs)
    all_sentences: list[str] = []
    per_paragraph_sentences: list[int] = []
    per_paragraph_words: list[int] = []

    for paragraph in paragraphs:
        s = sentences(paragraph)
        all_sentences.extend(s)
        per_paragraph_sentences.append(len(s))
        per_paragraph_words.append(len(words(paragraph)))

    all_words = words(full_text)
    lengths = [len(words(s)) for s in all_sentences]
    lengths = [x for x in lengths if x > 0]

    m.sentences = len(all_sentences)
    m.words = len(all_words)

    if lengths:
        m.sentence_median = statistics.median(lengths)
        m.sentence_mean = statistics.fmean(lengths)
        m.sentence_shortest = min(lengths)
        m.sentence_longest = max(lengths)
        m.sentence_longest_text = max(all_sentences, key=lambda s: len(words(s)))
        m.share_short_sentences = sum(1 for x in lengths if x <= 5) / len(lengths)
        m.share_long_sentences = sum(1 for x in lengths if x >= 25) / len(lengths)
        m.sentence_length_histogram = _histogram(lengths)

    if per_paragraph_sentences:
        m.paragraph_median_sentences = statistics.median(per_paragraph_sentences)
        m.paragraph_median_words = statistics.median(per_paragraph_words)

    if all_sentences:
        m.share_i_openings = sum(
            1 for s in all_sentences if s.startswith("Ich")
        ) / len(all_sentences)
        m.share_conjunction_openings = sum(
            1 for s in all_sentences if s.startswith(("Und ", "Aber ", "Dann ", "Doch "))
        ) / len(all_sentences)
        m.dialogue_share = sum(
            1 for s in all_sentences if _SPEECH.search(s)
        ) / len(all_sentences)

    if all_words:
        per_1000 = 1000 / len(all_words)
        m.nominal_style_per_1000 = len(_NOMINAL_STYLE.findall(full_text)) * per_1000
        m.passive_per_1000 = len(_PASSIVE.findall(full_text)) * per_1000
        lowered = [w.lower() for w in all_words]
        m.filler_words_per_1000 = sum(lowered.count(f) for f in _FILLER_WORDS) * per_1000
        m.type_token_ratio = len(set(lowered)) / len(lowered)

    m.punctuation = {
        "em_dash": full_text.count("—") + full_text.count(" – "),
        "ellipsis": full_text.count("…") + full_text.count("..."),
        "question_mark": full_text.count("?"),
        "exclamation_mark": full_text.count("!"),
        "colon": full_text.count(":"),
        "semicolon": full_text.count(";"),
        "parenthesis": full_text.count("("),
        "direct_speech": len(_SPEECH.findall(full_text)),
    }

    lowered = [w.lower() for w in all_words]
    trigrams = Counter(
        " ".join(lowered[i : i + 3]) for i in range(len(lowered) - 2)
    )
    m.most_frequent_trigrams = [
        (t, n) for t, n in trigrams.most_common(25) if n >= 3
    ][:15]

    openings = Counter(
        " ".join(words(s)[:2]).lower() for s in all_sentences if words(s)
    )
    m.most_frequent_openings = openings.most_common(12)

    return m


def measure_manuscript(manuscript) -> StyleMetrics:  # noqa: ANN001 — Manuscript, avoids a cycle
    """Metrics over a work's entire draft."""
    with_text = [s for s in manuscript.sections if s.has_text]
    return measure(
        [p for s in with_text for p in s.paragraphs],
        sections=len(with_text),
    )
