"""Activities that trigger the book domain's Studio agents.

Follows the pattern from ``crm/classify.py``: the agent is **triggered** through
the conversations API, never rebuilt via ``Agent(id=…)`` + ``Runner`` — that
would overwrite the definition in Studio with the fields passed in.

All functions here are activities (that is, I/O) and must be imported in
workflow modules through ``workflow.unsafe.imports_passed_through()``. They
return plain ``dict``s so that Temporal's data converter carries them cleanly
across the sandbox boundary.

The payloads are German: they are prompts for agents that work on German prose.
"""

from __future__ import annotations

import json
from datetime import timedelta
import mistralai.workflows as workflows
from mistralai.client import models as mistralai_models
from mistralai.workflows.plugins.mistralai.activities import (
    ConversationAppendRequest,
    mistralai_append_conversation,
    mistralai_start_conversation,
)
from pydantic import BaseModel

from . import config
from .models import (
    ContentReview,
    Corrections,
    ProfileCheck,
    RawVoiceProfile,
    SecondRead,
    StyleSecondRead,
    StyleSuggestions,
    VoiceSample,
)


def _extract_text(response: mistralai_models.ConversationResponse) -> str:
    """Join the text of a ConversationResponse.

    Depending on the answer, ``content`` is either a string or a list of chunks
    — both occur.
    """
    parts: list[str] = []
    for output in response.outputs:
        content = getattr(output, "content", None)
        if content is None:
            continue
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for chunk in content:
                text = getattr(chunk, "text", None)
                if text:
                    parts.append(text)
    return "\n".join(parts).strip()


def _parse[T: BaseModel](model: type[T], text: str) -> T:
    """Read the agent's answer into its Pydantic model.

    The agents have a JSON schema as ``response_format``, so the text is JSON.
    Defensive anyway: if there is prose around it, we cut out the outermost
    ``{…}`` block.
    """
    try:
        return model.model_validate_json(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return model.model_validate(json.loads(text[start : end + 1]))
        raise


async def _trigger[T: BaseModel](agent_id: str, payload: str, model: type[T]) -> T:
    answer = await mistralai_start_conversation(
        mistralai_models.ConversationRequest(
            agent_id=agent_id,
            inputs=payload,
            store=False,  # analysis runs need not linger in Studio
        )
    )
    return _parse(model, _extract_text(answer))


async def _trigger_open[T: BaseModel](
    agent_id: str, payload: str, model: type[T]
) -> tuple[T, str]:
    """Like :func:`_trigger`, but keeps the conversation open for follow-ups.

    ``store=True`` is mandatory for that: an ``append`` on an unstored
    conversation answers with HTTP 404 ("Conversation … was not found", checked
    live). The price is that these runs stay in Studio — in exchange every round
    of the review loop is traceable there.
    """
    answer = await mistralai_start_conversation(
        mistralai_models.ConversationRequest(agent_id=agent_id, inputs=payload, store=True)
    )
    return _parse(model, _extract_text(answer)), answer.conversation_id


async def _continue[T: BaseModel](conversation_id: str, payload: str, model: type[T]) -> T:
    """Continue an open conversation — the agent keeps its context.

    Hence ``append`` rather than a new call: the agent sees what it proposed
    itself and relates the verdict to it. A restart would have to repeat the
    whole context and would lose the reference.
    """
    answer = await mistralai_append_conversation(
        ConversationAppendRequest(conversation_id=conversation_id, inputs=payload, store=True)
    )
    return _parse(model, _extract_text(answer))


# ---------------------------------------------------------------------------
# Voice profile — map and reduce
# ---------------------------------------------------------------------------


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=120),
)
async def sample_voice(section: dict) -> dict:
    """Map step: observes the voice on ONE section.

    Takes a single ``dict`` because ``execute_activities_in_parallel`` passes
    exactly one argument per element. It uses ``title``, ``text`` and ``path`` —
    deliberately NOT ``synopsis`` (see below).
    """
    head = [f"ABSCHNITT: {section['title']}"]
    if section.get("path"):
        head.append(f"GLIEDERUNG: {' / '.join(section['path'])}")
    # Deliberately WITHOUT synopsis: it describes what the section is meant to
    # achieve, not how the author writes. For the voice it is noise; it belongs
    # to the content level (book-content).
    payload = "\n".join(head) + "\n\n--- TEXT ---\n" + section["text"]

    sample = await _trigger(config.AGENTS["voice_sample"], payload, VoiceSample)
    return {"uuid": section.get("uuid"), "title": section["title"], **sample.model_dump(mode="json")}


def _comparable(text: str) -> str:
    """Comparison form for the catalogue match: whitespace and quotes ignored."""
    uniform = " ".join(str(text).split())
    for a, b in (("„", '"'), ("“", '"'), ("”", '"'), ("‚", "'"), ("‘", "'"), ("’", "'")):
        uniform = uniform.replace(a, b)
    return uniform.strip(" \"'.,;:!?").lower()


def _sentence_catalogue(samples: list[dict]) -> list[str]:
    """All verbatim sentences from the samples, de-duplicated and stably ordered.

    The sources are ``sample_sentences`` and the ``evidence`` fields of the
    observations — the map step pulled both straight from the section text.
    """
    seen: dict[str, None] = {}
    for s in samples:
        for sentence in s.get("sample_sentences") or []:
            if isinstance(sentence, str) and len(sentence.strip()) > 20:
                seen.setdefault(sentence.strip(), None)
        for o in s.get("observations") or []:
            evidence = (o or {}).get("evidence")
            if isinstance(evidence, str) and len(evidence.strip()) > 20:
                seen.setdefault(evidence.strip(), None)
    return list(seen)


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=300),
)
async def distil_voice(
    samples: list[dict], metrics_text: str, max_rules: int
) -> dict:
    """Reduce step: condense all observations into at most ``max_rules`` rules.

    The agent gets a **numbered sentence catalogue** and points at it with
    numbers instead of retyping quotes. It used to do the latter — and
    paraphrased while doing so: in one measured run ten of twelve rules failed
    the evidence check because their "verbatim" evidence did not appear in the
    manuscript that way. A number cannot be paraphrased.
    """
    catalogue = _sentence_catalogue(samples)
    parts = [
        f"HÖCHSTENS {max_rules} REGELN.",
        "",
        "=== GEMESSENE KENNZAHLEN (Fakten, nicht umdeuten) ===",
        metrics_text,
        "",
    ]
    parts += [
        "=== SATZKATALOG — nur aus diesen Nummern darfst du Fundstellen wählen ===",
        "\n".join(f"[{n}] {sentence}" for n, sentence in enumerate(catalogue)),
        "",
        "=== BEOBACHTUNGEN AUS DEN ABSCHNITTEN ===",
    ]
    for i, s in enumerate(samples, start=1):
        parts.append(f"\n--- Abschnitt {i} ---")
        parts.append(json.dumps(s, ensure_ascii=False, indent=1))

    profile = await _trigger(
        config.AGENTS["voice_profile"], "\n".join(parts), RawVoiceProfile
    )
    raw = profile.model_dump(mode="json")
    # Resolve against the catalogue — numbers OR wording.
    #
    # The intent was: numbers only, because a number cannot be paraphrased.
    # Measured: the model writes sentences anyway, even with ``strict: true`` in
    # the schema — strict enforces enums, but not numeric types. A ``list[int]``
    # made validation fail three times and left the run hanging.
    #
    # So accept both and resolve in Python. The guarantee is unchanged: whatever
    # is not in the catalogue is dropped. Only the route there is now tolerant
    # instead of rigid.
    by_wording = {_comparable(s): s for s in catalogue}
    for rule in raw.get("rules", []):
        resolved: list[str] = []
        for entry in rule.get("evidence", []):
            text = str(entry).strip().strip("[]")
            if text.isdigit() and 0 <= int(text) < len(catalogue):
                resolved.append(catalogue[int(text)])
                continue
            hit = by_wording.get(_comparable(text))
            if hit:
                resolved.append(hit)
        rule["evidence"] = resolved
    return raw


# ---------------------------------------------------------------------------
# Editing — levels 1 and 2
# ---------------------------------------------------------------------------


def _paragraph_block(paragraphs: list[str]) -> str:
    """Paragraphs with their index — the agent addresses findings by ``paragraph_index``."""
    return "\n\n".join(f"[{i}] {p}" for i, p in enumerate(paragraphs))


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def copyedit(title: str, paragraphs: list[str]) -> dict:
    """Level 1: spelling, punctuation, grammar, tense, typography."""
    payload = f"ABSCHNITT: {title}\n\n--- ABSÄTZE ---\n{_paragraph_block(paragraphs)}"
    result = await _trigger(config.AGENTS["copyedit"], payload, Corrections)
    return result.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def check_style(
    title: str, paragraphs: list[str], voice_profile_text: str, max_findings: int
) -> dict:
    """Level 2: makes the text more like the author, not smoother."""
    payload = (
        f"HÖCHSTENS {max_findings} VORSCHLÄGE.\n\n"
        f"=== STIMMPROFIL DES AUTORS ===\n{voice_profile_text}\n\n"
        f"=== ABSCHNITT: {title} ===\n{_paragraph_block(paragraphs)}"
    )
    result = await _trigger(config.AGENTS["style"], payload, StyleSuggestions)
    return result.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=300),
)
async def review_content(
    chapter: dict, rubric: dict, touchstones: dict, synopsis: str = ""
) -> dict:
    """Level 3: a whole chapter against the author's rubric.

    Three yardsticks, in this order of authority: the chapter's **rubric** (what
    it has to carry), the work's **touchstones** (the two questions) and the
    **exposé** (what the book as a whole is meant to be). The exposé comes last
    on purpose and is explicitly marked as intent — it describes the book as it
    is offered to publishers, not as the manuscript is. Confuse the two and
    every deviation looks like an error.
    """
    parts: list[str] = []
    if synopsis:
        parts += [
            "=== EXPOSÉ — was das Buch werden SOLL (Absicht, nicht Ist-Zustand) ===",
            synopsis.strip(),
            "",
        ]
    parts += ["=== PRÜFSTEINE DES WERKS — die zwei Fragen an jedes Kapitel ==="]
    for key in ("first_question", "second_question"):
        question = touchstones.get(key) or {}
        if question.get("rule"):
            parts.append(f"- {question['rule']}")
            if question.get("explanation"):
                parts.append(f"  {question['explanation']}")
    parts.append("")

    parts += [f"=== RUBRIK FÜR DIESES KAPITEL: {rubric.get('title', '')} ==="]
    if rubric.get("subtitle"):
        parts.append(f"Untertitel: {rubric['subtitle']}")
    for field, heading in (
        ("proves", "Beweist"),
        ("must_carry", "Muss tragen"),
        ("need_not_carry", "Muss NICHT tragen"),
        ("open_work", "Offene Arbeit laut Plan"),
    ):
        values = rubric.get(field) or []
        if values:
            parts.append(f"{heading}:")
            parts += [f"  - {v}" for v in values]
    for field, heading in (("register", "Register"), ("season", "Zeit"), ("aboard", "An Bord")):
        if rubric.get(field):
            parts.append(f"{heading}: {rubric[field]}")
    if rubric.get("history_budget") is not None:
        parts.append(f"Historie-Budget: {rubric['history_budget']} Stellen")
    parts.append("")

    parts.append(f"=== DAS KAPITEL: {chapter['chapter']} ({chapter['words']} Wörter) ===")
    for s in chapter["sections"]:
        parts.append(f"\n## {s['title']}  ({s['words']} Wörter, {s['status'] or 'ohne Status'})")
        if s.get("synopsis"):
            parts.append(f"> Absicht laut Scrivener: {s['synopsis']}")
        parts.append(s["text"])

    result = await _trigger(config.AGENTS["content"], "\n".join(parts), ContentReview)
    return result.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=2,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def check_profile(rules: list[dict]) -> dict:
    """Hold every profile rule against its own evidence.

    The evidence check in ``voice.py`` makes sure a sentence **exists** in the
    manuscript — not that it **demonstrates** the rule. Measured on the first
    usable profile: "Umgangssprache in Sachzusammenhängen" was evidenced with a
    sentence containing no colloquialism at all. For the style agent that is
    worse than one rule fewer, because it learns from the evidence what the rule
    looks like.
    """
    parts = []
    for r in rules:
        parts += [
            f"REGEL {r['id']}: {r.get('title', '')}",
            f"  Beschreibung: {r.get('rule', '')}",
            f"  Erkennbar an: {r.get('testable_as', '—')}",
            f"  Fundstelle:   {(r.get('evidence') or ['—'])[0]}",
            "",
        ]
    result = await _trigger(config.AGENTS["profile_check"], "\n".join(parts), ProfileCheck)
    return result.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def second_read_style(
    title: str, paragraphs: list[str], voice_profile_text: str, suggestions: list[dict]
) -> dict:
    """The second pair of eyes over level 2 — one question per suggestion.

    Not the same as for the copyedit level: there it also looks for what is
    MISSING. Here it does not. A missed style lapse costs nothing; an imposed
    suggestion costs the author his voice. So this stage checks in one direction
    only — does the suggestion deliver what its rule promises?
    """
    listing = "\n".join(
        f"{i}. „{s.get('search')}“ → „{s.get('replace')}“  [{s.get('rule_id')}] — "
        f"{s.get('why', '')}"
        for i, s in enumerate(suggestions, start=1)
    )
    payload = (
        f"=== STIMMPROFIL DES AUTORS ===\n{voice_profile_text}\n\n"
        f"=== ABSCHNITT: {title} ===\n{_paragraph_block(paragraphs)}\n\n"
        f"--- VORSCHLAEGE DER ERSTEN STUFE ---\n{listing}"
    )
    result = await _trigger(config.AGENTS["style_second_read"], payload, StyleSecondRead)
    return result.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def second_read(
    title: str, paragraphs: list[str], findings: list[dict], context: str = ""
) -> dict:
    """The second pair of eyes over an edit.

    Receives THE SAME section as the first stage, plus its findings. The earlier
    judge received only ``search`` and ``replace`` — a snippet without the
    sentence it sits in — and for that reason alone could not judge whether an
    error was being fixed. And because it ran per finding, it never ran at zero
    findings: a missed error was invisible.
    """
    listing = "\n".join(
        f"{i}. Absatz {f.get('paragraph_index')}: „{f.get('search')}“ → „{f.get('replace')}“"
        f" ({f.get('kind', '')}) — {f.get('why', '')}"
        for i, f in enumerate(findings, start=1)
    ) or "(keine)"
    payload = (
        f"ABSCHNITT: {title}\n\n--- ABSÄTZE ---\n{_paragraph_block(paragraphs)}\n\n"
        f"--- BEFUNDE DER ERSTEN STUFE ---\n{listing}"
    )
    if context:
        payload += f"\n\n=== KONTEXT ===\n{context}"
    result = await _trigger(config.AGENTS["second_read"], payload, SecondRead)
    return result.model_dump(mode="json")


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def copyedit_open(title: str, paragraphs: list[str]) -> dict:
    """Like :func:`copyedit`, but also returns the ``conversation_id``.

    Only needed when a review loop follows — without a loop ``store=False``
    stays right, because then nothing has to linger in Studio.
    """
    payload = f"ABSCHNITT: {title}\n\n--- ABSÄTZE ---\n{_paragraph_block(paragraphs)}"
    result, cid = await _trigger_open(config.AGENTS["copyedit"], payload, Corrections)
    return {"conversation_id": cid, **result.model_dump(mode="json")}


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=180),
)
async def revise(conversation_id: str, feedback: str, level: str) -> dict:
    """Hand the verdict back to the agent and let it improve."""
    model = Corrections if level == "copyedit" else StyleSuggestions
    result = await _continue(conversation_id, feedback, model)
    return result.model_dump(mode="json")


# ---------------------------------------------------------------------------
# Helper activities
# ---------------------------------------------------------------------------


@workflows.activity(start_to_close_timeout=timedelta(seconds=10))
async def today() -> str:
    """Read the clock through an activity — workflow code has to stay deterministic."""
    from datetime import date

    return date.today().isoformat()


def agent_available(key: str) -> bool:
    """Whether an agent ID is recorded for this purpose."""
    return bool(config.AGENTS.get(key))


def missing_agents() -> list[str]:
    """Agents without an ID — after ``make sync-agents`` the IDs go into shared/book.json."""
    return [k for k, v in config.AGENTS.items() if not v]
