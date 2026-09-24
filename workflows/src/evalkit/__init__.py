"""Agent evaluation for the whole stack — domain-independent.

Born during the book edit, but deliberately not housed there: every agent in
the repo raises the same question — does it deliver the right thing, and how
would one notice a regression?

    from evalkit import Case, Config, agent_definition, compare

Layout:
  models.py    Case, Check, Result, Tally — what is measured
  runner.py    runs cases against configurations — how it is measured
  __main__.py  generic CLI: python -m evalkit --agent <name> --cases <file>

A domain contributes only two things: the test cases (which inputs, which
assertions) and optionally a generator for them. Everything else lives here.
"""

from .models import Case, Check, Result, Tally, evaluate, pick, tally
from .runner import (
    DEFAULT_CONFIGS,
    Config,
    agent_definition,
    compare,
    run_once,
)

__all__ = [
    "DEFAULT_CONFIGS",
    "Case",
    "Check",
    "Config",
    "Result",
    "Tally",
    "agent_definition",
    "compare",
    "evaluate",
    "pick",
    "run_once",
    "tally",
]
