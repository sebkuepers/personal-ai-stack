"""BATCH workflow — distil a work's voice profile.

The first milestone of the book domain and the basis for the style level of the
edit.

Flow (map/reduce):

  1. **Map** — one voice sample per section through the agent
     ``book-voice-sample``, in parallel at a limited width. Small context,
     concrete observation, each one with verbatim evidence.
  2. **Reduce** — ``book-voice-profile`` condenses all samples together with the
     measured metrics and the author's own formulated rules into at most twelve
     rules.
  3. **Check** — deterministic, in workflow code: every rule needs enough
     evidence, and every piece of evidence must appear verbatim in the
     manuscript. That catches invented quotes, which would otherwise carry
     convincing-looking rules.

The workflow touches **no file system** — the production worker runs in the
Cloudflare container and could not reach the Scrivener project anyway. Reading
Scrivener, measuring and parsing the notes is done beforehand by ``bookcli``;
here everything arrives ready as input.

Trigger with:
  make book-voiceprofile work=immer-wieder-ruegen
"""

from __future__ import annotations

from datetime import date

import mistralai.workflows as workflows
from mistralai.workflows import workflow

# Across the sandbox boundary: the activities (they talk to the Mistral client)
# AND the configuration. The latter is easy to miss — ``config`` reads
# ``shared/book.json`` at import time and used ``Path(__file__).resolve()`` for
# it, which the Temporal sandbox forbids. The access is deterministic (once at
# import, only constants afterwards), so passthrough is exactly right here.
with workflow.unsafe.imports_passed_through():
    from workflows.book.models import (
        Corpus,
        ProfileCheck,
        RawVoiceProfile,
        VoiceProfile,
        VoiceProfileInput,
    )
    from workflows.book.voice import build_profile
    import workflows.book.config as config
    from workflows.book.agents import (
        check_profile,
        distil_voice,
        sample_voice,
        today,
    )

# Pure modules (models, checking logic) are imported normally.


@workflows.workflow.define(
    name="book-voiceprofile",
    workflow_display_name="Book · Distil the voice profile",
    workflow_description=(
        "Beobachtet die Erzählstimme in allen Abschnitten eines Werks, verdichtet die "
        "Beobachtungen zu höchstens zwölf prüfbaren Regeln und verwirft jede Regel, deren "
        "Belege nicht wörtlich im Manuskript stehen."
    ),
)
class BookVoiceProfileWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: VoiceProfileInput) -> VoiceProfile:
        # Step 1 — map. The width is limited on purpose: 48 concurrent agent
        # calls would achieve nothing but rate-limit errors.
        samples = await workflows.execute_activities_in_parallel(
            sample_voice,
            items=[s.model_dump(mode="json") for s in inp.sections],
            max_concurrent_scheduled_tasks=inp.parallel,
        )
        samples = [s for s in (samples or []) if s]

        # Step 2 — reduce.
        raw_dict = await distil_voice(
            samples=samples,
            metrics_text=inp.metrics_text,
            max_rules=config.MAX_VOICE_RULES,
        )
        raw = RawVoiceProfile.model_validate(raw_dict)

        # Step 3 — evidence check, deterministic in the workflow thread.
        today_iso = await today()
        profile = build_profile(
            raw,
            work=inp.work,
            corpus_text=inp.corpus_text,
            corpus=Corpus(
                sections=len(inp.sections),
                words=inp.words,
                chapters=inp.chapters,
            ),
            metrics=inp.metrics,
            created_at=date.fromisoformat(today_iso),
            min_evidence=config.MIN_EVIDENCE,
            max_rules=config.MAX_VOICE_RULES,
            version=inp.version,
        )

        # Step 4 — hold the evidence against its rules.
        #
        # Step 3 checks whether a piece of evidence EXISTS in the manuscript.
        # Whether it DEMONSTRATES the rule is a judgement and needs a model.
        # Measured on the first usable profile: "Umgangssprache in
        # Sachzusammenhängen" was evidenced with a sentence containing no
        # colloquialism at all.
        #
        # What fails is not discarded but set to `beobachtung`: the rule can be
        # right and only the evidence askew. Through `active_rules` the style
        # agent gets only the confirmed ones — it learns from the evidence what
        # the rule looks like, and askew evidence is worse there than one rule
        # fewer.
        if profile.rules and config.AGENTS.get("profile_check"):
            verdict = ProfileCheck.model_validate(
                await check_profile([r.model_dump(mode="json") for r in profile.rules])
            )
            askew = {c.rule_id: c.why for c in verdict.checks if not c.shows_the_rule}
            for r in profile.rules:
                if r.id in askew:
                    r.status = "beobachtung"
            if askew:
                profile.open_questions.append(
                    f"{len(askew)} Regel(n) auf 'beobachtung', weil die Fundstelle die Regel "
                    "nicht zeigt: " + "; ".join(f"{k} ({v})" for k, v in askew.items())
                )
        return profile
