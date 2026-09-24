"""Pydantic models of the book domain.

Two layers, as in ``crm/models.py``:

* **Layer 1** — exact mirrors of what the Studio agents return according to
  their ``response_format.json_schema``. ``extra="forbid"`` corresponds to
  ``additionalProperties: false`` in the schema; when an agent's answer
  deviates it surfaces here and not three steps later.
* **Layer 2** — the validated objects the rest of the code works with: the
  checked voice profile, findings, decisions.

Pure and importable from workflow code (no I/O, no client).

**Which strings are German and why.** Identifiers are English throughout. The
*values* of the six vocabularies declared in ``shared/book.json``
(correction kinds, style problems, severities, decisions, rejection reasons,
rule status) stay German: they are the vocabulary of German copy-editing, they
are written into the decision log, they appear in the eval cases, and the
author reads them on screen. Ad-hoc ``Literal``s that only name a part of this
system are English.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ===========================================================================
# Layer 1 — mirrors of the agent schemas
# ===========================================================================


class Observation(BaseModel):
    """A single notable trait with evidence — the currency of the map step."""

    model_config = ConfigDict(extra="forbid")

    observation: str = Field(description="What stands out, in one sentence")
    evidence: str = Field(description="Verbatim quote from the section")
    kind: Literal["strength", "weakness", "idiosyncrasy"] = Field(
        description="Strength = carries the voice, weakness = harms it, idiosyncrasy = noticeable but neutral"
    )


class VoiceSample(BaseModel):
    """Output of ``book-voice-sample`` — the observation for ONE section."""

    model_config = ConfigDict(extra="forbid")

    sample_sentences: list[str] = Field(
        description="3-5 verbatim sentences typical of the author's voice"
    )
    narrative_stance: str
    tense: str
    person: str
    observations: list[Observation]
    recurring_constructions: list[str] = Field(
        description="Sentence patterns that occur more than once"
    )
    avoidances: list[str] = Field(
        description="What the author demonstrably does NOT do — often more telling than what he does"
    )


class RawVoiceRule(BaseModel):
    """A rule as the reduce agent proposes it (not yet checked)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Short identifier, e.g. R-behauptung-statt-bild")
    title: str
    rule: str = Field(
        description=(
            "What the author DOES, as a checkable statement — never a prohibition. "
            "No prohibition can be evidenced from his finished text, because it "
            "contains no violations."
        )
    )
    why: str
    evidence: list[str] = Field(
        description=(
            "At least two entries from the SENTENCE CATALOGUE — either the number in "
            "square brackets or the sentence verbatim. Python resolves both against the "
            "catalogue; anything not in it is discarded."
        )
    )
    violation_example: str = Field(
        description="The first piece of evidence, rewritten so that it NO LONGER follows the rule"
    )
    testable_as: str = Field(description="How an editor or agent recognises the violation")
    source: Literal["manuskript", "notizen"]


class RawVoiceProfile(BaseModel):
    """Output of ``book-voice-profile`` — the aggregated profile, not yet checked."""

    model_config = ConfigDict(extra="forbid")

    narrative_stance: str
    tense: str
    person: str
    rules: list[RawVoiceRule]
    recurring_motifs: list[str]
    avoidances: list[str]
    open_questions: list[str] = Field(
        description="Where the evidence was contradictory or the data too thin"
    )


# ===========================================================================
# Layer 2 — the validated profile
# ===========================================================================


class VoiceRule(RawVoiceRule):
    """A rule that survived the evidence check.

    ``evidence`` here holds the **wording**, no longer the numbers: the reduce
    agent points at sentences in the sentence catalogue, and the caller resolves
    the numbers afterwards. A stored profile should be readable on its own and
    not depend on a catalogue that no longer exists.

    ``acceptance_rate`` is computed later **in Python** from the decision log,
    not estimated by a model: a rule whose suggestions the author mostly rejects
    is moved to ``beobachtung`` automatically — regardless of how convincing a
    model finds it.
    """

    model_config = ConfigDict(extra="forbid")

    evidence: list[str]  # type: ignore[assignment]  — resolved, no longer numbers
    status: Literal["aktiv", "beobachtung", "verworfen"] = "aktiv"
    acceptance_rate: float | None = None
    proposals_total: int = 0


class Corpus(BaseModel):
    """What the profile was built from — so one can later tell whether it still fits."""

    model_config = ConfigDict(extra="forbid")

    sections: int
    words: int
    chapters: list[str]


class VoiceProfile(BaseModel):
    """Result of ``book-voiceprofile`` — versioned in ``shared/book/<slug>-stimme.json``."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    work: str
    created_at: date
    corpus: Corpus
    metrics: dict = Field(default_factory=dict, description="The deterministic measurements")
    narrative_stance: str
    tense: str
    person: str
    rules: list[VoiceRule]
    recurring_motifs: list[str] = Field(default_factory=list)
    avoidances: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    discarded_rules: list[dict] = Field(
        default_factory=list,
        description="Proposed by the model but failed the evidence check — with the reason",
    )

    @property
    def active_rules(self) -> list[VoiceRule]:
        return [r for r in self.rules if r.status == "aktiv"]


# ===========================================================================
# Workflow inputs
# ===========================================================================


class SectionInput(BaseModel):
    """A section as a workflow receives it.

    Deliberately without a file path: workflows do not read a file system (the
    production worker runs in a container). ``bookcli`` reads Scrivener and
    passes the text in.
    """

    uuid: str
    title: str
    text: str
    path: list[str] = Field(default_factory=list)
    synopsis: str | None = None


class VoiceProfileInput(BaseModel):
    """Input of ``book-voiceprofile``.

    Measurements and author's notes arrive fully prepared — computing them is
    pure, deterministic work and does not belong in an agent call.
    """

    work: str
    sections: list[SectionInput]
    corpus_text: str = Field(
        description="The entire manuscript text — basis of the evidence check"
    )
    metrics_text: str = Field(description="The measured figures as running text")
    metrics: dict = Field(default_factory=dict)
    words: int = 0
    chapters: list[str] = Field(default_factory=list)
    version: int = 1
    parallel: int = Field(
        default=6, description="How many sections are analysed concurrently"
    )


# ===========================================================================
# Layer 1 — editing findings (levels 1 and 2)
# ===========================================================================


class Correction(BaseModel):
    """A finding from ``book-copyedit``."""

    model_config = ConfigDict(extra="forbid")

    paragraph_index: int
    search: str = Field(description="The text to replace — must occur EXACTLY ONCE in the paragraph")
    replace: str
    kind: Literal[
        "rechtschreibung", "komma", "grammatik", "tempus", "typografie", "formatierung"
    ]
    confidence: float = Field(ge=0, le=1)
    why: str


class Corrections(BaseModel):
    model_config = ConfigDict(extra="forbid")

    corrections: list[Correction]


class StyleSuggestion(BaseModel):
    """A finding from ``book-style``.

    ``rule_id`` is the enforcement hook: every suggestion must cite a rule of
    the voice profile or say ``kein-bezug``. Suggestions with ``kein-bezug`` are
    discarded in workflow code unless the severity is „hoch" — otherwise the
    profile stays decorative.
    """

    model_config = ConfigDict(extra="forbid")

    paragraph_index: int
    search: str
    replace: str
    problem: Literal[
        "wiederholung", "satzlaenge", "rhythmus", "fuellwort", "klischee",
        "passiv", "nominalstil", "erklaert_statt_gezeigt", "perspektivbruch", "stimmbruch",
    ]
    severity: Literal["hoch", "mittel", "niedrig"]
    why: str
    rule_id: str = Field(description="ID of a voice-profile rule, or 'kein-bezug'")


class StyleSuggestions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestions: list[StyleSuggestion]


class EditingInput(BaseModel):
    """Input of the editing workflows — one section, already read.

    As with :class:`VoiceProfileInput` the text comes in rather than being read:
    workflows do not touch a file system.
    """

    work: str
    section: SectionInput
    paragraphs: list[str] = Field(
        default_factory=list,
        description="Paragraphs individually — findings address them via paragraph_index",
    )
    voice_profile_text: str = Field(
        default="", description="Rendered voice profile; only the style level needs it"
    )
    max_findings: int = 12
    with_second_read: bool = Field(
        default=True, description="Review before display (recommended)"
    )
    max_rounds: int = Field(
        default=1,
        description=(
            "How often a rejected finding goes back to the agent. "
            "1 = no loop, only blocking — that is the measured default. "
            "An A/B run on the same section gave: without the loop 0 findings (everything "
            "cleanly filtered), with the loop 6 findings, all nonsensical. The agent takes "
            "the instruction 'narrow it down' literally and minimises its suggestion into "
            "meaninglessness ('runter.' → 'runter'). Only raise this again once an eval "
            "with annotated expectations shows that it helps."
        ),
    )


class JudgedFinding(BaseModel):
    """A finding together with its review — and the decision whether it is shown."""

    model_config = ConfigDict(extra="forbid")

    level: Literal["copyedit", "style"]
    paragraph_index: int
    search: str
    replace: str
    kind: str = Field(description="Correction kind or style problem")
    severity: str | None = None
    why: str = ""
    rule_id: str | None = None
    confidence: float | None = None
    review: dict[str, int] = Field(default_factory=dict)
    blocked: bool = False
    block_reason: str | None = None


class EditingResult(BaseModel):
    """Output of an editing workflow."""

    model_config = ConfigDict(extra="forbid")

    work: str
    section_uuid: str
    section_title: str
    level: Literal["copyedit", "style"]
    findings: list[JudgedFinding] = Field(default_factory=list)
    blocked: list[JudgedFinding] = Field(
        default_factory=list, description="Discarded by the fidelity review, before display"
    )
    notes: list[str] = Field(default_factory=list)

    @property
    def by_kind(self) -> dict[str, int]:
        """Findings grouped — the basis for 'accept all' per kind."""
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.kind] = counts.get(f.kind, 0) + 1
        return counts


class MissedError(BaseModel):
    """An error the first stage did not report."""

    model_config = ConfigDict(extra="forbid")

    paragraph_index: int
    search: str
    replace: str
    kind: str
    why: str


class UnfoundedFinding(BaseModel):
    """A reported finding that is not one."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(description="Position in the presented list, starting at 1")
    why: str


class SecondRead(BaseModel):
    """Output of ``book-second-read`` — the second pair of eyes.

    Unlike the earlier judge, this agent sees **the same text** as the first
    stage, not merely its suggestions. Only then can it answer the question the
    four-eyes principle turns on: did the first reader get this right? A
    reviewer who sees only suggestions cannot possibly notice that one is
    missing — and never runs at all when there are zero suggestions.
    """

    model_config = ConfigDict(extra="forbid")

    missed: list[MissedError] = Field(default_factory=list)
    unfounded: list[UnfoundedFinding] = Field(default_factory=list)
    verdict: str


# ---------------------------------------------------------------------------
# Session — the conversational workflow
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """What the author did with ONE finding.

    The real capital of this system. An accepted finding says little; a rejected
    one with a reason says where the voice profile is wrong. That is why the
    reasons are a pick list with a free field rather than free text alone — only
    then can they be counted later.
    """

    model_config = ConfigDict(extra="forbid")

    level: Literal["copyedit", "style"]
    paragraph_index: int
    paragraph_hash: str = Field(
        default="", description="State of the paragraph at analysis time — the lock when applying"
    )
    search: str
    replace: str
    kind: str
    why: str = ""
    rule_id: str | None = None
    decision: Literal["angenommen", "abgelehnt", "zurueckgestellt"]
    reason: str = Field(default="", description="Only on rejection; from the pick list or free")
    own_version: str | None = Field(
        default=None,
        description=(
            "The whole paragraph as the author worded it himself — set when he accepted the "
            "idea but not the phrasing. When applying, this replaces the paragraph instead "
            "of only search→replace."
        ),
    )


class EditingSession(BaseModel):
    """The result of an editing session — and the input for writing back."""

    model_config = ConfigDict(extra="forbid")

    work: str
    section_uuid: str
    section_title: str
    levels: list[str] = Field(default_factory=list)
    decisions: list[Decision] = Field(default_factory=list)
    text_before: str = ""
    text_after: str = ""
    notes: list[str] = Field(default_factory=list)
    aborted: bool = False

    @property
    def accepted(self) -> list[Decision]:
        return [d for d in self.decisions if d.decision == "angenommen"]


# ---------------------------------------------------------------------------
# Level 3 — content
# ---------------------------------------------------------------------------


class TouchstoneVerdict(BaseModel):
    """How a chapter stands against one of the work's two touchstones."""

    model_config = ConfigDict(extra="forbid")

    question: str
    verdict: Literal["holds", "wobbles", "fails"]
    reason: str
    places: list[str] = Field(
        default_factory=list, description="Section titles where it shows"
    )


class CarriedPoint(BaseModel):
    """A point from ``must_carry`` — and whether the chapter delivers it."""

    model_config = ConfigDict(extra="forbid")

    point: str
    carried: Literal["yes", "partly", "no"]
    sections: list[str] = Field(default_factory=list)
    why: str


class CutCandidate(BaseModel):
    """A passage the chapter does not need."""

    model_config = ConfigDict(extra="forbid")

    section: str
    extent: str = Field(description="Whole section, one scene, one paragraph")
    reason: str


class ContentReview(BaseModel):
    """Output of ``book-content`` — level 3, a whole chapter.

    **This level changes nothing.** No ``search``, no ``replace``, anywhere. It
    asks questions and names what is missing — because the answer to that is
    writing, not replacing. A suggestion that rewords a paragraph would be
    presumption here; a note that the pan-pan scene has 800 characters and is
    meant to be the emotional centre is work.
    """

    model_config = ConfigDict(extra="forbid")

    chapter_thesis: str = Field(
        description="What this chapter is about — in one sentence, read from the text"
    )
    # WITHOUT a default, hence under `required` in the JSON schema.
    #
    # With `default_factory=list` both lists stayed empty — twice, even after an
    # explicit instruction in the prompt and with a doubled token budget. The
    # reason is simple: a field with a default is not under `required`, and then
    # the model is allowed to omit it. It does. What is mandatory belongs in the
    # schema, not in the prose.
    touchstones: list[TouchstoneVerdict]
    carries: list[CarriedPoint]
    surplus: list[CutCandidate] = Field(
        default_factory=list, description="What the rubric says need NOT be carried, but is there"
    )
    cut_candidates: list[CutCandidate] = Field(default_factory=list)
    questions_for_the_author: list[str] = Field(
        default_factory=list,
        description="What cannot be decided from outside — five at most",
    )


class StyleCheck(BaseModel):
    """A style suggestion, judged by the second pair of eyes."""

    model_config = ConfigDict(extra="forbid")

    number: int = Field(description="Position in the presented list, starting at 1")
    verdict: Literal["holds", "inverts_the_rule", "no_violation", "overreaches"]
    why: str


class StyleSecondRead(BaseModel):
    """Output of ``book-style-second-read`` — the second pair of eyes over level 2.

    Unlike the copyedit stage this is not about "is something missing". A missed
    style lapse costs nothing; an imposed suggestion costs the author his voice.
    So this stage checks in one direction only: does the suggestion deliver what
    its rule promises?

    The three failure kinds are named after real bad suggestions:

    * ``inverts_the_rule`` — the cited rule says the opposite. The profile
      records past tense FOR flashbacks; the suggestion pulls them into present.
    * ``no_violation`` — the passage already sounds like the author. A
      description is not violated by the fact that one could apply it harder.
    * ``overreaches`` — the core is right, the change goes beyond it: alters
      meaning, touches direct speech, deletes something concrete.
    """

    model_config = ConfigDict(extra="forbid")

    checks: list[StyleCheck]
    verdict: str


class RuleCheck(BaseModel):
    """Whether a piece of evidence actually demonstrates the rule it stands for."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str
    shows_the_rule: bool
    why: str


class ProfileCheck(BaseModel):
    """Output of ``book-profile-check`` — the evidence held against its rules.

    The evidence check in ``voice.py`` makes sure a sentence **exists**. It
    cannot say whether that sentence **demonstrates** the rule — and that is
    exactly what went wrong: a rule "colloquialisms in factual contexts" was
    evidenced with a sentence containing no colloquialism. Formally impeccable,
    substantively worthless, and misleading for the style agent, which learns
    from it what the rule looks like.
    """

    model_config = ConfigDict(extra="forbid")

    checks: list[RuleCheck]
    verdict: str
