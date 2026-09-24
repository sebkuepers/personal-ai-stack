"""Data models for agent evaluation — domain-independent.

The occasion was the book edit, but the pattern holds for every agent in the
stack: an agent returns structured output, and one wants to know whether it
returns the right thing — before starting to build a filter for every single
observed error.

Two kinds of assertion, and the second is the more valuable one:

* **expected** — must hold. Measures the *hit rate*: how much of what is there
  does the agent find?
* **forbidden** — must not hold. Measures the *trap rate*: how often does it
  report something that is not there?

An agent that reports everything has a perfect hit rate and is worthless. One
that reports nothing falls into no trap and is equally worthless. Only both
numbers together say something.

The traps encode judgements that are written down nowhere else: that „runter"
is intended, that a category must not be invented, that a field should stay
empty when the information is missing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


def _norm(x: Any) -> str:
    """For comparisons that should be tolerant: case does not matter."""
    return unicodedata.normalize("NFC", str(x)).strip().lower()


def _literal(x: Any) -> str:
    """For comparisons that have to be literal.

    Invariants must **not** run through ``_norm``: it lower-cases, and that
    makes every capitalisation fix („beim schwimmen" → „beim Schwimmen") read
    as "nothing changed" — of all things the most common German correction. An
    invariant that is more tolerant than the agent has to be precise reports
    the measurer instead of the measured.
    """
    return unicodedata.normalize("NFC", str(x)).strip()


# Path syntax: "field", "field.subfield", "list[].field"
_SEGMENT = re.compile(r"([^.\[\]]+)(\[\])?")


def pick(data: Any, path: str) -> list[Any]:
    """Resolve a path in the agent's answer and return every match.

    ``"category"`` → the value. ``"corrections[].search"`` → all search values
    of the list. Missing intermediate steps yield an empty list rather than an
    error — a place that does not exist is a valid measurement result.
    """
    current: list[Any] = [data]
    for name, is_list in _SEGMENT.findall(path):
        following: list[Any] = []
        for node in current:
            if isinstance(node, dict) and name in node:
                value = node[name]
                following.extend(value if is_list and isinstance(value, list) else [value])
        current = following
    return current


@dataclass
class Check:
    """An assertion about an agent's answer.

    ``operator``:
      * ``contains``   — some value at the path contains ``value`` (or the
        other way round; both directions, so an agent may carry more or less
        context)
      * ``equals``     — some value at the path is exactly ``value``
      * ``exists``     — there is anything non-empty at the path
      * ``less_than`` / ``greater_than`` / ``at_least`` / ``at_most`` — a
        numeric threshold at the path. Meant for reviewers: "score has to be
        below 4".
      * ``unchanged``  — two paths element-wise: a "finding" that changes
        nothing. An invariant, hence checkable without annotation.
      * ``not_in_input`` — the agent quotes something that is not in its input.
      * ``pair``       — two paths at once: ``value`` is ``[from, to]``; holds
        when one element satisfies both halves. Meant for finding lists
        ("reports ``runter`` **and** replaces it with ``hinunter``").
    """

    path: str
    operator: str = "contains"
    value: Any = None
    pair_path: str | None = None
    note: str = ""

    def applies(self, answer: Any, context: str | None = None) -> bool:
        """``context`` is the case's input — only operators that check against
        it (``not_in_input``) need it."""
        values = pick(answer, self.path)

        if self.operator == "exists":
            return any(v not in (None, "", [], {}) for v in values)

        if self.operator == "equals":
            return any(_norm(v) == _norm(self.value) for v in values)

        if self.operator in ("less_than", "greater_than", "at_least", "at_most"):
            # Numeric thresholds — for reviewers and anything that scores.
            numbers = []
            for v in values:
                try:
                    numbers.append(float(v))
                except (TypeError, ValueError):
                    continue
            if not numbers:
                return False
            limit = float(self.value)
            return any(
                {
                    "less_than": n < limit,
                    "greater_than": n > limit,
                    "at_least": n >= limit,
                    "at_most": n <= limit,
                }[self.operator]
                for n in numbers
            )

        if self.operator == "unchanged":
            # Two paths, element-wise: a "finding" that changes nothing. That is
            # an invariant and hence checkable without annotation — exactly the
            # class of error a pure trap measurement overlooks.
            #
            # Compared literally, but for whitespace: an earlier version cut
            # quotation marks and lower-cased — and thereby reported every
            # typographic and every capitalisation fix as a no-op. An
            # invariant's tolerance has to be narrower than what the agent may
            # legitimately change.
            second = pick(answer, self.pair_path or self.path)
            return any(
                _literal(a) == _literal(b)
                for a, b in zip(values, second, strict=False)
            )

        if self.operator == "not_in_input":
            # The agent quotes something that does not occur in its input. The
            # second annotation-free invariant: a `search` that is not in the
            # text cannot be applied — however right the finding may be in
            # substance. Catches exactly the cases where a model silently
            # normalises while quoting.
            text = _literal(context or "")
            return any(v and _literal(v) not in text for v in values)

        if self.operator == "pair":
            before, after = self.value
            second = pick(answer, self.pair_path or self.path)
            return any(
                (_norm(before) in _norm(a) or _norm(a) in _norm(before))
                and _norm(after) in _norm(b)
                for a, b in zip(values, second, strict=False)
            )

        target = _norm(self.value)
        return any(target and (target in _norm(v) or _norm(v) in target) for v in values if v)

    def describe(self) -> str:
        if self.operator == "unchanged":
            return "finding without a change (search == replace)"
        if self.operator == "not_in_input":
            return f"{self.path} does not occur in the input"
        if self.operator == "pair":
            return f"{self.value[0]} → {self.value[1]}"
        return f"{self.path} {self.operator} {self.value!r}"


@dataclass
class Case:
    """A test case: an input plus what has to hold and what must not."""

    id: str
    input: str
    expected: list[Check] = field(default_factory=list)
    forbidden: list[Check] = field(default_factory=list)
    source: str = "manual"
    note: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Case:
        def check(x: dict) -> Check:
            return Check(**{k: v for k, v in x.items() if not k.startswith("_")})

        return cls(
            id=d["id"],
            input=d["input"],
            expected=[check(x) for x in d.get("expected", [])],
            forbidden=[check(x) for x in d.get("forbidden", [])],
            source=d.get("source", "manual"),
            note=d.get("note", ""),
        )


@dataclass
class Result:
    """What one run of a case produced."""

    case_id: str
    hit: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    trapped: list[str] = field(default_factory=list)
    items: int = 0
    seconds: float = 0.0
    tokens: int = 0
    error: str | None = None


def evaluate(case: Case, answer: Any, *, count_path: str | None = None) -> Result:
    """Score an agent's answer against a case.

    ``count_path`` says what counts as "one finding" (e.g. ``"corrections[]"``)
    — for the density figure only. Without it the answer counts as one item.
    """
    r = Result(case_id=case.id)
    r.items = len(pick(answer, count_path)) if count_path else 1

    for check in case.expected:
        (r.hit if check.applies(answer, case.input) else r.missed).append(check.describe())
    for check in case.forbidden:
        if check.applies(answer, case.input):
            r.trapped.append(check.describe())
    return r


@dataclass
class Tally:
    """Summary over all cases of one configuration."""

    config: str
    cases: int = 0
    expected: int = 0
    hit: int = 0
    forbidden: int = 0
    trapped: int = 0
    items: int = 0
    seconds: float = 0.0
    tokens: int = 0
    errors: int = 0

    @property
    def hit_rate(self) -> float:
        return self.hit / self.expected if self.expected else 1.0

    @property
    def trap_rate(self) -> float:
        """Share of traps fallen into. Smaller is better."""
        return self.trapped / self.forbidden if self.forbidden else 0.0

    @property
    def score(self) -> float:
        """Hit rate minus trap rate — one number to sort by.

        Deliberately coarse: it does not replace looking at both values, but it
        makes a comparison between configurations possible at a glance.
        """
        return self.hit_rate - self.trap_rate

    def as_line(self) -> str:
        return (
            f"{self.config:22} "
            f"hits {self.hit:3}/{self.expected:<3} ({self.hit_rate:4.0%})  "
            f"traps {self.trapped:3}/{self.forbidden:<3} ({self.trap_rate:4.0%})  "
            f"score {self.score:+.2f}  "
            f"{self.seconds / max(self.cases, 1):5.1f}s  {self.tokens:6}T"
            + (f"  {self.errors} errors!" if self.errors else "")
        )


def tally(config: str, cases: list[Case], results: list[Result]) -> Tally:
    t = Tally(config=config, cases=len(results))
    by_id = {c.id: c for c in cases}
    for r in results:
        case = by_id.get(r.case_id)
        if case is None:
            continue
        t.expected += len(case.expected)
        t.forbidden += len(case.forbidden)
        t.hit += len(r.hit)
        t.trapped += len(r.trapped)
        t.items += r.items
        t.seconds += r.seconds
        t.tokens += r.tokens
        t.errors += 1 if r.error else 0
    return t
