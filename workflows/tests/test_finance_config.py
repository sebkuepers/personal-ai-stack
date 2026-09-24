"""The finance domain's configuration carries promises — these hold them.

Two of them matter more than the rest:

* The category vocabulary was **derived from the author's own planning
  workbook**, not invented. If someone adds a category later, it has to say
  whether it exists as a row in his sheet or is a deliberate cross-cut.
  Otherwise the claim in the docstring quietly becomes false.
* ``paths.json`` is gitignored, so **nothing importable may need it at import
  time**. On a fresh checkout, and in CI, the file does not exist.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflows.finance import config as c

REPO = Path(__file__).resolve().parents[2]


class TestCategories:
    def test_every_category_declares_where_it_comes_from(self) -> None:
        for key, entry in c.CATEGORIES.items():
            assert entry.get("source") in {"project55", "cross_cut"}, (
                f"Kategorie {key!r} sagt nicht, woher sie stammt — "
                "'project55' (eine Zeile seiner Mappe) oder 'cross_cut' (bewusster Zusatzschnitt)."
            )

    def test_a_project55_category_names_the_rows_it_stands_for(self) -> None:
        # Without the rows the derivation is unverifiable, and "derived from his
        # workbook" becomes a claim nobody can check.
        for key, entry in c.CATEGORIES.items():
            if entry["source"] == "project55" and key != "income":
                assert entry.get("rows"), f"{key!r} behauptet project55, nennt aber keine Zeile"

    def test_a_cross_cut_says_why_it_exists(self) -> None:
        for key, entry in c.CATEGORIES.items():
            if entry["source"] == "cross_cut":
                assert entry.get("note"), f"Zusatzschnitt {key!r} ohne Begründung"

    def test_keys_are_ascii_and_english(self) -> None:
        for key in c.CATEGORY_KEYS:
            assert key.isascii() and key.islower(), key

    def test_comment_keys_never_reach_a_caller(self) -> None:
        # A "_comment" in the category table would otherwise become a category
        # and show up as a line in the report.
        for mapping in (c.CATEGORIES, c.MODELS, c.LIMITS, c.TIDY, c.LIBRARY_DOCUMENTS):
            assert not [k for k in mapping if k.startswith("_")]


class TestLibrary:
    def test_the_summaries_are_on_by_default(self) -> None:
        # They are a goal of the domain, not a by-product: without them Vibe has
        # no context and the conversation is worthless.
        assert c.LIBRARY_ENABLED is True

    def test_three_documents_and_no_more(self) -> None:
        assert set(c.LIBRARY_DOCUMENTS) == {"overview", "month", "subscriptions"}


class TestPathsStayOutOfTheRepo:
    def test_the_domain_config_holds_no_personal_path(self) -> None:
        raw = (REPO / "shared" / "finance.json").read_text(encoding="utf-8")
        # ~/Downloads and ~/Desktop are platform conventions, not personal
        # structure — those may stay. Anything below ~/Documents is his.
        for needle in ("/Users/", "~/Documents", "DE60", "NL65"):
            assert needle not in raw, (
                f"{needle!r} steht in shared/finance.json — die Datei ist eingecheckt. "
                "Persönliche Pfade und Kontonummern gehören nach shared/finance/paths.json."
            )

    def test_the_template_is_released_and_the_real_file_is_not(self) -> None:
        ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        assert "shared/finance/*.json" in ignore
        assert "!shared/finance/paths.example.json" in ignore

    def test_the_template_parses_and_names_the_read_only_workbooks(self) -> None:
        template = json.loads(
            (REPO / "shared" / "finance" / "paths.example.json").read_text(encoding="utf-8")
        )
        for key in c.READ_ONLY_KEYS:
            assert key in template, f"{key} fehlt in paths.example.json"

    def test_a_missing_paths_file_is_named_not_a_stack_trace(self, monkeypatch) -> None:
        # On a fresh checkout this is the expected state, not a bug.
        monkeypatch.setattr(c, "paths", c.paths.__wrapped__)
        monkeypatch.setattr("workflows.finance.config.load_shared", _raise_missing)
        with pytest.raises(FileNotFoundError, match="paths.example.json"):
            c.paths()


def _raise_missing(_relpath: str):
    raise FileNotFoundError("nope")
