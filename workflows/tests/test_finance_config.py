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
        # The rows are personal and live in the gitignored vocabulary, so this
        # can only be checked where that file exists — on his machine, where it
        # matters. Without it the derivation is simply unclaimed.
        if not c.vocabulary().get("rows"):
            pytest.skip("shared/finance/vocabulary.json fehlt — nichts zu prüfen")
        for key, entry in c.CATEGORIES.items():
            if entry["source"] == "project55" and key != "income":
                assert c.rows_for(key), f"{key!r} behauptet project55, nennt aber keine Zeile"

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
        # Plus the names that identify a person rather than a domain: his
        # suppliers, his subscriptions, his family. Those live in the gitignored
        # vocabulary — this test is what keeps them there.
        for needle in ("/Users/", "~/Documents", "DE60", "NL65",
                       "im-jaich", "Telsche", "Audible", "Porsche", "Postbank"):
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


# Names that identify a person rather than a domain. They belong in the
# gitignored vocabulary, never in a tracked file — this repo is public.
PERSONAL = (
    "im-jaich", "Telsche", "Oelmann", "Kurella", "Döhnert",
    "Audible", "Asservato", "Geniuslink", "TheVerge", "Lotto24",
    "Porsche", "Renault", "Postbank", "Ing Diba",
    "Max & Paul", "finanzen_privat_project55",
)
# Deliberately NOT on the list: the parser dialect names (commerzbank_giro,
# commerzbank_card, bunq). They name a FILE FORMAT, the way the Gmail tool names
# do — domain knowledge, which is what this repo shares. Which of them anyone
# actually banks with is in the gitignored paths.json.


class TestNothingPersonalIsTracked:
    """The repo is public. The domain is shared, the life is not.

    This scans every file git tracks, because the leak that happened was not in
    the config it was guarded in: it was in the agent generator, in the docs and
    in commit messages. A guard on one file is a guard on one file.
    """

    def _tracked(self) -> list[Path]:
        import subprocess

        out = subprocess.run(
            ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
        ).stdout
        return [REPO / line for line in out.splitlines() if line.strip()]

    def test_no_tracked_file_carries_an_account_identifier(self) -> None:
        """IBANs and card numbers, anywhere in the repo.

        The name list below would not have caught these: the first version of
        the leak-guard test used the real IBAN and the real card number as its
        fixtures — in a test whose entire point is that such things must not end
        up anywhere public. Patterns catch what a list of names cannot.
        """
        import re as _re

        # Real German/Dutch IBANs and 16-digit card numbers. The invented ones
        # in the fixtures use runs of zeros and ones, which these skip.
        iban = _re.compile(r"\b(?:DE|NL|AT|CH)\d{2}[A-Z0-9]{12,28}\b")
        card = _re.compile(r"\b\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}\b")
        offenders: list[str] = []
        for path in self._tracked():
            if path.suffix in {".png", ".jpg", ".webp", ".pdf", ".lock"} or not path.is_file():
                continue
            if path.name == "test_finance_config.py":
                continue  # the patterns themselves live here
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for pattern, what in ((iban, "IBAN"), (card, "Kartennummer")):
                for found in pattern.findall(text):
                    # An invented placeholder is all zeros and ones after the
                    # country code, or a repeated group.
                    body = found.replace(" ", "").replace("-", "")[4:]
                    if set(body) <= set("01X"):
                        continue
                    offenders.append(f"{path.relative_to(REPO)}: {what} {found[:8]}…")
        assert not offenders, "Kontodaten in verfolgten Dateien:\n  " + "\n  ".join(offenders[:20])

    def test_no_tracked_file_carries_a_personal_name(self) -> None:
        offenders: list[str] = []
        for path in self._tracked():
            if path.suffix in {".png", ".jpg", ".webp", ".pdf", ".lock"} or not path.is_file():
                continue
            if path.name == "test_finance_config.py":
                continue  # the list itself lives here
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for needle in PERSONAL:
                if needle in text:
                    offenders.append(f"{path.relative_to(REPO)}: {needle!r}")
        assert not offenders, "Persönliches in verfolgten Dateien:\n  " + "\n  ".join(offenders[:20])
