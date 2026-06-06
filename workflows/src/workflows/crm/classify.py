"""Classification activity — triggers your existing Studio CRM agent.

We do NOT re-implement the classification prompt here. The Studio "CRM -
Classification Agent" (id in ``config.CRM_CLASSIFICATION_AGENT_ID``) already
owns the instructions, the model, and the JSON response schema. This activity
simply *triggers* it via the Conversations API and parses its structured
output into our typed ``CRMClassification`` mirror.

Why the Conversations API and not ``Agent(id=...)`` + ``Runner``?
  The durable-agent ``Agent(id=...)`` path is documented to *update* (overwrite)
  the remote agent's config from the fields you pass. Passing a sparse Agent
  would clobber your carefully-built Studio agent. ``mistralai_start_conversation``
  triggers the agent exactly as configured and changes nothing.

This is an activity (not inline workflow code) so the call gets retries,
distributed scheduling, and per-call observability in Studio.
"""

from __future__ import annotations

import json
from datetime import timedelta

import mistralai.workflows as workflows
from mistralai.client import models as mistralai_models
from mistralai.workflows.plugins.mistralai.activities import mistralai_start_conversation

from . import config
from .models import CRMClassification


def _extract_text(response: mistralai_models.ConversationResponse) -> str:
    """Concatenate the assistant text from a ConversationResponse.

    Each output entry's ``content`` is either a plain string or a list of
    content chunks (each with a ``.text``). We handle both.
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


def _parse_classification(text: str) -> CRMClassification:
    """Parse the agent's JSON output into a CRMClassification.

    The Studio agent is configured with a JSON response schema, so ``text`` is
    expected to be a JSON object. We parse defensively: if there is any
    surrounding prose, we slice out the outermost ``{...}`` block.
    """
    try:
        return CRMClassification.model_validate_json(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return CRMClassification.model_validate(json.loads(text[start : end + 1]))
        raise


@workflows.activity(
    retry_policy_max_attempts=3,
    retry_policy_backoff_coefficient=2.0,
    start_to_close_timeout=timedelta(seconds=90),
)
async def classify_interaction(
    text: str,
    subject: str | None = None,
    interaction_type: str = "Email",
    channel: str = "Email",
) -> dict:
    """Trigger the Studio CRM agent on one interaction; return a CRMClassification dict.

    Returns a plain dict (JSON mode) so Temporal's data converter round-trips it
    cleanly across the workflow sandbox boundary (dates become ISO strings).
    """
    # Give the agent a little structure around the raw content. The agent's own
    # instructions decide how to use it — we are not classifying here.
    header = []
    if subject:
        header.append(f"Subject: {subject}")
    header.append(f"Interaction type: {interaction_type}")
    header.append(f"Channel: {channel}")
    payload = "\n".join(header) + "\n\n--- CONTENT ---\n" + text

    request = mistralai_models.ConversationRequest(
        agent_id=config.CRM_CLASSIFICATION_AGENT_ID,
        inputs=payload,
        store=False,  # we don't need Studio to persist these conversations
    )
    response = await mistralai_start_conversation(request)
    classification = _parse_classification(_extract_text(response))
    return classification.model_dump(mode="json")
