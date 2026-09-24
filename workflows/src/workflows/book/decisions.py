"""The decision log — one line per finding, in the author's own words.

This is the capital of the whole system. An accepted finding says little; a
rejected one with a reason says where the voice profile is wrong. And a finding
the author accepts but **rewords himself** is a pair no model produced.

Until this existed none of it was stored: ``EditingSession`` returned the
decisions together with their reasons, and closing the chat threw them away.
The most valuable output of the system was decoration.

**Format:** JSONL, one file per month, under
``workflows/data/book/<slug>/decisions/`` — gitignored, because manuscript text
lives here. One line per finding, not per session, so that it can later be
counted per rule.

**Written in exactly one place** — from the conversational workflow, as soon as
a level is approved, not at the very end. If the session is aborted or times
out, the decisions made up to that point are still there.

Pure: no models, no agents. Reading and writing happen in the activities in
``local.py``; this module holds the formats and the analysis.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Decision


def log_dir(data_root: Path, work: str) -> Path:
    return data_root / "book" / work / "decisions"


def log_file(data_root: Path, work: str, when: datetime | None = None) -> Path:
    """The current month's file — monthly files stay manageable and diffable."""
    when = when or datetime.now(UTC)
    return log_dir(data_root, work) / f"{when:%Y-%m}.jsonl"


def line(
    d: Decision,
    *,
    work: str,
    section_uuid: str,
    section_title: str,
    path: list[str],
    session_id: str,
    when: datetime | None = None,
) -> dict[str, Any]:
    """One log line — flat, so it stays countable with any tool."""
    when = when or datetime.now(UTC)
    return {
        "ts": when.isoformat(timespec="seconds"),
        "session": session_id,
        "work": work,
        "section_uuid": section_uuid,
        "section": section_title,
        "path": path,
        "level": d.level,
        "paragraph_index": d.paragraph_index,
        "paragraph_hash": d.paragraph_hash,
        "kind": d.kind,
        "rule_id": d.rule_id,
        "search": d.search,
        "replace": d.replace,
        "why": d.why,
        "decision": d.decision,
        "reason": d.reason,
        # When the author reworded it himself, his version goes here —
        # the gold-standard pair that no model produced.
        "own_version": d.own_version,
    }


def write(file: Path, lines: list[dict[str, Any]]) -> int:
    """Append lines; create directory and file if needed. Returns the count."""
    if not lines:
        return 0
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("a", encoding="utf-8") as fh:
        for entry in lines:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return len(lines)


def read_all(data_root: Path, work: str) -> list[dict[str, Any]]:
    """All lines of all months, in write order. Broken lines are skipped."""
    directory = log_dir(data_root, work)
    if not directory.is_dir():
        return []
    lines: list[dict[str, Any]] = []
    for file in sorted(directory.glob("*.jsonl")):
        for raw in file.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return lines


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


@dataclass
class RuleTally:
    """How a voice-profile rule lands with the author."""

    rule_id: str
    proposals: int = 0
    accepted: int = 0
    rejected: int = 0
    deferred: int = 0
    reasons: dict[str, int] | None = None

    @property
    def acceptance_rate(self) -> float | None:
        """Share of accepted among decided proposals — None while nothing is decided."""
        decided = self.accepted + self.rejected
        return self.accepted / decided if decided else None


def tally_per_rule(lines: list[dict[str, Any]], *, level: str = "style") -> list[RuleTally]:
    """Count how often each rule was proposed and how often it was accepted.

    This is the number that turns into ``status="beobachtung"`` in the voice
    profile: a rule whose suggestions the author mostly rejects does not
    describe his voice — no matter how convincing a model found it. **Counted
    in Python, not estimated by a model**, which was the plan from the start.
    """
    per_rule: dict[str, RuleTally] = {}
    reasons: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for entry in lines:
        if entry.get("level") != level:
            continue
        rid = entry.get("rule_id") or "kein-bezug"
        tally = per_rule.setdefault(rid, RuleTally(rule_id=rid))
        tally.proposals += 1
        state = entry.get("decision")
        if state == "angenommen":
            tally.accepted += 1
        elif state == "abgelehnt":
            tally.rejected += 1
            if entry.get("reason"):
                reasons[rid][entry["reason"]] += 1
        elif state == "zurueckgestellt":
            tally.deferred += 1
    for rid, tally in per_rule.items():
        tally.reasons = dict(reasons.get(rid, {}))
    return sorted(per_rule.values(), key=lambda t: -t.proposals)


def as_text(tallies: list[RuleTally]) -> str:
    lines = [f"{'Rule':44} {'proposed':>8} {'yes':>4} {'no':>5} {'open':>5}  accepted"]
    for t in tallies:
        rate = f"{t.acceptance_rate:4.0%}" if t.acceptance_rate is not None else "   —"
        lines.append(
            f"{t.rule_id:44} {t.proposals:8} {t.accepted:4} {t.rejected:5} "
            f"{t.deferred:5}  {rate}"
        )
        for reason, n in sorted((t.reasons or {}).items(), key=lambda x: -x[1])[:3]:
            lines.append(f"{'':44} {'':8} {'':4} {'':5} {'':5}  · {n}× {reason}")
    return "\n".join(lines)
