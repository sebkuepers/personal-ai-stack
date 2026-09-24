"""Check, build and render the voice profile.

The reduce agent delivers rules together with evidence. Before any of them is
ever allowed to justify a style suggestion it passes two gates here — **in
Python, not in the prompt**:

1. **Evidence count.** At least two verbatim pieces of evidence per rule.
2. **Evidence authenticity.** Every piece must actually occur in the manuscript.

Point 2 is the more important one. A model that wants to formulate a pretty rule
will invent a fitting quote for it if it has to — and a rule standing on
invented evidence is worse than no rule, because it looks convincing. Discarded
rules do not vanish silently; they land in the profile under
``discarded_rules`` with a reason.

Pure: no I/O, no model. Therefore runnable in the workflow thread, and testable.

The rendered output stays German: one rendering goes into a German prompt, the
other is read by the author.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from .models import Corpus, RawVoiceProfile, VoiceProfile, VoiceRule


def _norm(text: str) -> str:
    """Comparison form for evidence: NFC, uniform whitespace, uniform characters.

    Typographic variants (quotation marks, apostrophes, dashes) are unified — a
    piece of evidence should not fail because the agent wrote a straight quote
    instead of a typographic one.
    """
    t = unicodedata.normalize("NFC", text)
    for char, replacement in (
        ("„", '"'), ("“", '"'), ("”", '"'), ("»", '"'), ("«", '"'),
        ("’", "'"), ("‘", "'"), ("‚", "'"),
        ("—", "-"), ("–", "-"), ("…", "..."),
        (" ", " "),
    ):
        t = t.replace(char, replacement)
    return re.sub(r"\s+", " ", t).strip().lower()


def normalise_id(raw: str) -> str:
    """Turn a model-assigned rule ID into a stable ASCII identifier.

    The model assigns IDs freely and produces umlauts (``R-bürosprache``) and
    the occasional typo (``R-prospektsrache``) while doing so. The style agent
    later has to cite these IDs verbatim and the workflow has to compare them —
    both get error-prone as soon as special characters are involved.
    """
    s = raw.strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")
    if not s.startswith("r-"):
        s = f"r-{s}"
    return "R-" + s[2:]


def evidence_found(evidence: str, corpus_norm: str, *, min_length: int = 20) -> bool:
    """Whether a piece of evidence occurs verbatim in the manuscript.

    Very short "evidence" is rejected: a three-word quote is found in 27,000
    words almost always and therefore evidences nothing.
    """
    e = _norm(evidence)
    if len(e) < min_length:
        return False
    return e in corpus_norm


def check_rules(
    raw: RawVoiceProfile,
    corpus_text: str,
    *,
    min_evidence: int,
    max_rules: int,
) -> tuple[list[VoiceRule], list[dict]]:
    """Filter the proposed rules down to the evidenced ones.

    Returns ``(accepted, discarded)``; every discarded rule carries a reason, so
    that one can see where the profile failed.
    """
    corpus_norm = _norm(corpus_text)
    accepted: list[VoiceRule] = []
    discarded: list[dict] = []

    for rule in raw.rules:
        real = [e for e in rule.evidence if evidence_found(e, corpus_norm)]
        invented = [e for e in rule.evidence if e not in real]

        if len(real) < min_evidence:
            discarded.append(
                {
                    "id": rule.id,
                    "title": rule.title,
                    "reason": (
                        f"only {len(real)} of {len(rule.evidence)} pieces of evidence found "
                        f"in the manuscript, {min_evidence} required"
                    ),
                    "not_found": invented[:3],
                }
            )
            continue

        if len(accepted) >= max_rules:
            discarded.append(
                {"id": rule.id, "title": rule.title, "reason": f"beyond the limit of {max_rules} rules"}
            )
            continue

        accepted.append(
            VoiceRule(
                **{**rule.model_dump(), "id": normalise_id(rule.id), "evidence": real}
            )
        )

    return accepted, discarded


def build_profile(
    raw: RawVoiceProfile,
    *,
    work: str,
    corpus_text: str,
    corpus: Corpus,
    metrics: dict,
    created_at: date,
    min_evidence: int,
    max_rules: int,
    version: int = 1,
) -> VoiceProfile:
    """Assemble the checked profile."""
    rules, discarded = check_rules(
        raw, corpus_text, min_evidence=min_evidence, max_rules=max_rules
    )
    return VoiceProfile(
        version=version,
        work=work,
        created_at=created_at,
        corpus=corpus,
        metrics=metrics,
        narrative_stance=raw.narrative_stance,
        tense=raw.tense,
        person=raw.person,
        rules=rules,
        recurring_motifs=raw.recurring_motifs,
        avoidances=raw.avoidances,
        open_questions=raw.open_questions,
        discarded_rules=discarded,
    )


# ---------------------------------------------------------------------------
# Renderings
# ---------------------------------------------------------------------------


def render_for_agent(profile: VoiceProfile) -> str:
    """Compact form handed to the style agent at runtime.

    Deliberately **not** baked into the agent instructions: otherwise the agent
    would have to be re-synced on every profile change, and profile and agent
    would drift apart.
    """
    lines = [
        f"Erzählhaltung: {profile.narrative_stance}",
        f"Tempus: {profile.tense} · Person: {profile.person}",
        "",
        "REGELN (jeder Vorschlag muss sich auf eine davon berufen):",
    ]
    for r in profile.active_rules:
        lines += [
            f"\n[{r.id}] {r.title}",
            f"  {r.rule}",
            f"  Erkennbar an: {r.testable_as}",
            # Labelling, third attempt. First the evidence was called „Beleg"
            # and held a violation; then „Verstoß" and held a model case. Now
            # the thing itself is settled: rules describe what the author DOES,
            # the evidence shows it, and ``violation_example`` is the contrast.
            f"  So macht er es: „{r.evidence[0]}“",
            f"  So klänge es von jemand anderem: „{r.violation_example}“",
        ]
    if profile.avoidances:
        lines += ["", "DAS TUT DER AUTOR NIE:"]
        lines += [f"  - {a}" for a in profile.avoidances]
    return "\n".join(lines)


def render_markdown(profile: VoiceProfile) -> str:
    """Readable form for the skill and the library."""
    lines = [
        f"# Stimmprofil — {profile.work}",
        "",
        f"Version {profile.version}, erstellt am {profile.created_at.isoformat()} aus "
        f"{profile.corpus.sections} Abschnitten / {profile.corpus.words} Wörtern.",
        "",
        f"**Erzählhaltung:** {profile.narrative_stance}",
        f"**Tempus:** {profile.tense} · **Person:** {profile.person}",
        "",
        "## Regeln",
        "",
    ]
    for i, r in enumerate(profile.active_rules, start=1):
        lines += [
            f"### {i}. {r.title}",
            "",
            f"`{r.id}` · Quelle: {r.source}",
            "",
            f"**Regel:** {r.rule}",
            "",
            f"**Warum:** {r.why}",
            "",
            f"**Erkennbar an:** {r.testable_as}",
            "",
            "**So macht er es — Stellen aus dem Manuskript:**",
            "",
        ]
        lines += [f"> {e}" for e in r.evidence]
        lines += ["", f"**So klänge dieselbe Stelle von jemand anderem:** {r.violation_example}", ""]

    if profile.avoidances:
        lines += ["## Was der Autor nie tut", ""]
        lines += [f"- {a}" for a in profile.avoidances]
        lines.append("")
    if profile.recurring_motifs:
        lines += ["## Wiederkehrende Motive", ""]
        lines += [f"- {m}" for m in profile.recurring_motifs]
        lines.append("")
    if profile.open_questions:
        lines += ["## Offene Fragen", ""]
        lines += [f"- {q}" for q in profile.open_questions]
        lines.append("")
    if profile.discarded_rules:
        lines += [
            "## Verworfen (Belegprüfung nicht bestanden)",
            "",
            "Diese Regeln hat das Modell vorgeschlagen, aber ihre Belege standen so nicht "
            "im Manuskript:",
            "",
        ]
        lines += [f"- **{d['title']}** — {d['reason']}" for d in profile.discarded_rules]
        lines.append("")

    return "\n".join(lines)
