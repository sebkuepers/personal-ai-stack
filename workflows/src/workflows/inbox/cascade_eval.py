"""Ende-zu-Ende-Eval der Inbox-Cascade — nicht der einzelnen Agenten.

Die Stufen einzeln zu messen (``make inbox-eval``) sagt, was small und medium
könnten. Die Cascade ist aber ein eigenes System mit eigenem Fehlerprofil:

- Small liegt richtig, eskaliert trotzdem → medium kann Richtiges
  verschlimmern (medium selbst trifft nur ~91 %).
- Small liegt falsch, OHNE dass die Eskalationsregel greift → der Fehler
  bleibt stehen.
- Die Eskalationsregel selbst ist im Verbund ungetestet.

Dieses Eval fährt den ECHTEN Ablauf je Fall — First stage (small, so wie er in
``agents/inbox-review.json`` konfiguriert ist), Eskalationsentscheidung aus
``escalation.needs_second_review``, Second stage (medium, ``agents/inbox-
zweitblick.json``), Second stage gewinnt — und prüft das Endergebnis gegen
denselben Fallkatalog. Zum Vergleich laufen First stage-allein und
Second stage-allein mit, denn die eigentliche Frage lautet: Was kauft die
Cascade gegenüber „medium auf alles", und was kostet sie an Qualität?

    uv run python -m workflows.inbox.cascade_eval --laeufe 2
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from evalkit.modelle import Fall, bilanziere, pruefe
from evalkit.runner import agent_definition
from workflows.inbox.escalation import needs_second_review
from workflows.inbox.models import InboxReview

REPO = Path(__file__).resolve().parents[4]
API = "https://api.mistral.ai/v1/chat/completions"


def _agent_modus(name: str) -> tuple[str, str, dict]:
    """(model, instructions, response_schema) of an agent from agents/<name>.json."""
    instructions, schema = agent_definition(REPO, name)
    d = json.loads((REPO / "agents" / f"{name}.json").read_text(encoding="utf-8"))
    return d["model"], instructions, schema


@dataclass
class Stage:
    """Ein Aufruf einer Cascadenstufe mit ihrer echten Konfiguration."""

    name: str
    model: str
    instructions: str
    schema: dict


def _rufe(stage: Stage, eingabe: str) -> tuple[dict, int, float]:
    """One chat-completions call of a stage → (answer dict, tokens, seconds)."""
    body = {
        "model": stage.model,
        "messages": [
            {"role": "system", "content": stage.instructions},
            {"role": "user", "content": eingabe},
        ],
        "temperature": 0.2,
        "max_tokens": 4000,
        "response_format": stage.schema,
    }
    req = urllib.request.Request(
        API,
        method="POST",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['MISTRAL_API_KEY']}",
            "Content-Type": "application/json",
        },
    )
    t0 = time.time()
    with urllib.request.urlopen(req) as resp:
        d = json.loads(resp.read())
    text = d["choices"][0]["message"]["content"]
    if isinstance(text, list):  # Thinking-Chunks vor dem Text
        text = "".join(t.get("text", "") for t in text if isinstance(t, dict) and t.get("type") == "text")
    return (
        json.loads(text),
        d.get("usage", {}).get("completion_tokens", 0),
        time.time() - t0,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Die Inbox-Cascade Ende-zu-Ende messen.")
    p.add_argument("--faelle", default="shared/inbox/eval-review.json")
    p.add_argument("--laeufe", type=int, default=1)
    args = p.parse_args(argv)

    load_dotenv(REPO / "workflows" / ".env")

    first = Stage("inbox-review", *_agent_modus("inbox-review"))
    second = Stage("inbox-second-review", *_agent_modus("inbox-second-review"))
    print(f"Cascade: first stage={first.model}, second stage={second.model}")

    faelle = [Fall.from_dict(f) for f in json.loads((REPO / args.faelle).read_text(encoding="utf-8"))]

    cascade_results = []      # Endergebnisse der Cascade
    first_results = []         # First stage allein (Was hat der Second stage repariert/ruiniert?)
    cascade_tokens = 0
    escalations = 0

    for _ in range(args.laeufe):
        for fall in faelle:
            # Stage 1 — the first stage sees every envelope.
            antwort, tokens, dauer = _rufe(first, fall.eingabe)
            review = InboxReview.model_validate(antwort)
            e1 = pruefe(fall, antwort)
            e1.tokens, e1.dauer = tokens, dauer
            first_results.append(e1)
            cascade_tokens += tokens

            # Stage 2 — the second stage only where the escalation rule fires; it wins.
            if needs_second_review(review):
                escalations += 1
                antwort2, tokens2, dauer2 = _rufe(second, fall.eingabe)
                cascade_tokens += tokens2
                e2 = pruefe(fall, antwort2)
                e2.dauer = dauer + dauer2
                cascade_results.append(e2)
            else:
                e = pruefe(fall, antwort)
                e.tokens, e.dauer = tokens, dauer
                cascade_results.append(e)

    # Second stage allein auf ALLE Fälle — die Strategie, gegen die sich die
    # Cascade behaupten muss (medium auf alles: teurer, aber ohne Small-Fehler).
    second_alone = []
    for _ in range(args.laeufe):
        for fall in faelle:
            antwort, tokens, dauer = _rufe(second, fall.eingabe)
            e = pruefe(fall, antwort)
            e.tokens, e.dauer = tokens, dauer
            second_alone.append(e)

    gesamt = len(faelle) * args.laeufe
    print(f"\n{gesamt} Fälle · Eskalationen: {escalations} ({escalations / gesamt:.0%})\n")
    for name, ergebnisse, tokens in (
        ("first review alone (small)", first_results, sum(e.tokens for e in first_results)),
        ("second review alone (medium)", second_alone, sum(e.tokens for e in second_alone)),
        ("CASCADE (final)", cascade_results, cascade_tokens),
    ):
        b = bilanziere(name, faelle * args.laeufe, ergebnisse)
        b.tokens = tokens
        print("  " + b.als_zeile())

    print("\nVerpasst/Getappt der Cascade:")
    for e in cascade_results:
        for v in e.verpasst:
            print(f"  ○ {e.fall_id}: verpasst {v}")
        for f in e.fehltritte:
            print(f"  ✗ {e.fall_id}: Falle {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
