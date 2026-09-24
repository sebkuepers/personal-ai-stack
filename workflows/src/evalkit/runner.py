"""Run agent configurations against test cases — domain-independent.

What is tested is the **real agent** with its real instructions: ``model`` and
``completion_args`` can be overridden per call without touching the definition
in Studio. So what is measured is what later runs.

Deliberately without a domain's downstream filters — otherwise one measures the
filters, not the agent, and never learns whether a model change helped.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .models import Case, Result, Tally, evaluate, tally

API = "https://api.mistral.ai/v1/chat/completions"


@dataclass(frozen=True)
class Config:
    """One setting to compare."""

    name: str
    model: str
    reasoning: str | None = None
    temperature: float = 0.1

    @property
    def max_tokens(self) -> int:
        # Reasoning easily burns 2000+ tokens before the actual answer starts.
        # Budgeted too tightly, a truncated answer comes back — and that looks
        # like a model failure while being a budget failure.
        #
        # Measured on GLM: 4000 were not enough, the answers broke off mid-JSON
        # and counted as model errors. Mistral models stop earlier by
        # themselves, so the higher limit costs them nothing. Whoever compares
        # models has to give them the same room.
        return 16000 if self.reasoning else 12000


# Both models accept only 'none' or 'high' per the API;
# 'minimal'/'low'/'medium'/'xhigh' are rejected with HTTP 400.
DEFAULT_CONFIGS = [
    Config("small/none", "mistral-small-latest"),
    Config("small/high", "mistral-small-latest", "high"),
    Config("medium/none", "mistral-medium-latest"),
    Config("medium/high", "mistral-medium-latest", "high"),
]


def agent_definition(repo: Path, name: str) -> tuple[str, dict]:
    """An agent's instructions and answer schema from its repo definition.

    The file is the source of truth (see ``agents/README.md``), so this
    measures exactly what is in Studio too.
    """
    d = json.loads((repo / "agents" / f"{name}.json").read_text(encoding="utf-8"))
    return d["instructions"], d["completion_args"]["response_format"]


def _answer_text(msg: dict) -> str:
    """Get the answer text; with reasoning active, thinking chunks come first."""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    return "".join(
        t.get("text", "")
        for t in (content or [])
        if isinstance(t, dict) and t.get("type") == "text"
    )


def run_once(
    case: Case,
    config: Config,
    instructions: str,
    schema: dict,
    *,
    count_path: str | None = None,
) -> Result:
    """Run one case under one configuration."""
    body: dict = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": instructions},
            {"role": "user", "content": case.input},
        ],
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "response_format": schema,
    }
    if config.reasoning:
        body["reasoning_effort"] = config.reasoning

    request = urllib.request.Request(
        API,
        method="POST",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    started = time.time()
    try:
        with urllib.request.urlopen(request) as resp:
            payload = json.loads(resp.read())
        answer = json.loads(_answer_text(payload["choices"][0]["message"]))
        result = evaluate(case, answer, count_path=count_path)
        result.seconds = time.time() - started
        result.tokens = payload.get("usage", {}).get("completion_tokens", 0)
        return result
    except Exception as exc:  # noqa: BLE001 — every failure is a data point
        return Result(
            case_id=case.id, seconds=time.time() - started, error=f"{type(exc).__name__}: {exc}"
        )


def compare(
    cases: list[Case],
    configs: list[Config],
    instructions: str,
    schema: dict,
    *,
    runs: int = 1,
    count_path: str | None = None,
    progress=None,  # noqa: ANN001 — optional callback(config_name, case_id)
) -> list[tuple[Tally, list[Result]]]:
    """Run all cases against all configurations and tally them."""
    out: list[tuple[Tally, list[Result]]] = []
    for config in configs:
        results: list[Result] = []
        for _ in range(runs):
            for case in cases:
                if progress:
                    progress(config.name, case.id)
                results.append(
                    run_once(case, config, instructions, schema, count_path=count_path)
                )
        out.append((tally(config.name, cases * runs, results), results))
    return out
