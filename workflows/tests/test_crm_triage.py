"""The classification → triage mapping is the place that writes into Notion.

``classification_to_triage`` translates the agent's answer into the "intended
writes" — a mistake here lands in the real database twice a day, unnoticed. The
three documented mapping decisions (unknown → empty select, priority on the
contact, action_items folded into the AI analysis) have their contract here;
and it is tested against the **real** configuration from ``shared/crm.json``,
not against copied constants — the same rule as in the Scrivener test: an
instrument that carries the same assumptions as the code measures nothing.

Every function is pure — each date arrives as an argument, no clock read.
"""

from __future__ import annotations

from datetime import date

from workflows.crm.agent_tools import (
    classification_to_triage,
    compute_follow_up_date,
    derive_auto_tags,
    suggest_priority,
)
from workflows.crm.config import AUTO_TAGS, CATEGORIES, SUB_CATEGORIES, USER_ALIASES
from workflows.crm.models import CRMClassification, InteractionInput

TODAY = date(2026, 9, 23)


def klasse(
    *,
    category: str = "networking",
    interaction_type: str = "Email",
    sub_category: str | None = None,
    sentiment: str = "Positive",
    priority: str = "Medium",
    people: list[str] | None = None,
    organizations: list[str] | None = None,
    **extra: object,
) -> CRMClassification:
    """Eine gültige Agent-Antwort mit übersteuerbaren Feldern."""
    return CRMClassification(
        interaction_type=interaction_type,
        category=category,
        sentiment=sentiment,
        priority=priority,
        people_mentioned=people or [],
        organizations_mentioned=organizations or [],
        sub_category=sub_category,
        **extra,
    )


def eingabe(**extra: object) -> InteractionInput:
    return InteractionInput(text="Hallo, mal wieder von mir.", **extra)


# ---------------------------------------------------------------------------
# Die drei dokumentierten Mapping-Entscheidungen
# ---------------------------------------------------------------------------


def test_unknown_category_leaves_the_notion_select_empty() -> None:
    triage = classification_to_triage(
        klasse(category="unknown", sub_category="unknown"), eingabe(), TODAY
    )
    assert triage.interaction.category is None
    assert triage.interaction.sub_category is None
    assert "unknown" in triage.notes[0]


def test_no_self_contact_in_ones_own_crm() -> None:
    # An alias from the real config, in its original spelling — filtering is
    # case-insensitive, and "Seb" as a salutation must not create a half-contact.
    alias = next(iter(USER_ALIASES))
    triage = classification_to_triage(
        klasse(people=[alias.upper(), "Anna Meier"]), eingabe(), TODAY
    )
    assert [c.name for c in triage.contacts] == ["Anna Meier"]
    assert triage.interaction.contact_names == ["Anna Meier"]
    assert any("filtered self" in n for n in triage.notes)


def test_priority_sits_on_the_contact_not_the_interaction() -> None:
    triage = classification_to_triage(
        klasse(priority="High", people=["Anna Meier"]), eingabe(), TODAY
    )
    assert triage.contacts[0].priority == "High"
    # The interactions model deliberately has no such field at all.
    assert "priority" not in type(triage.interaction).model_fields


def test_action_items_are_folded_into_the_ai_analysis() -> None:
    triage = classification_to_triage(
        klasse(
            analysis="Erstanalyse.",
            action_items=["Termin vorschlagen", "Unterlagen senden"],
        ),
        eingabe(),
        TODAY,
    )
    analysis = triage.interaction.ai_analysis
    assert analysis is not None
    assert analysis.startswith("Erstanalyse.")
    assert "- Termin vorschlagen" in analysis
    assert "- Unterlagen senden" in analysis
    assert any("action_items" in n for n in triage.notes)


# ---------------------------------------------------------------------------
# Priority and follow-up — deterministic rules
# ---------------------------------------------------------------------------


def test_an_empty_priority_falls_back_to_the_rule() -> None:
    # The agent has to deliver a priority; empty falls back to the rule.
    triage = classification_to_triage(
        klasse(priority="", category="sales", sentiment="Positive", people=["Anna Meier"]),
        eingabe(),
        TODAY,
    )
    assert triage.contacts[0].priority == "Medium"


def test_suggest_priority_rules() -> None:
    assert suggest_priority("networking", "Urgent") == "High"
    assert suggest_priority("job_application", "Positive") == "High"
    assert suggest_priority("follow_up", "Positive") == "Medium"
    assert suggest_priority("personal", "Positive") == "Low"


def test_a_suggested_follow_up_date_wins() -> None:
    triage = classification_to_triage(
        klasse(
            category="job_application",  # Regel würde base+3 vorschlagen
            suggested_follow_up_date=date(2026, 10, 1),
        ),
        eingabe(),
        TODAY,
    )
    assert triage.interaction.follow_up_date == date(2026, 10, 1)
    assert triage.interaction.follow_up_needed is True


def test_follow_up_counts_from_the_event_not_from_today() -> None:
    triage = classification_to_triage(
        klasse(category="follow_up"),  # Regel: base+5
        eingabe(occurred_on=date(2026, 1, 1)),
        TODAY,
    )
    assert triage.interaction.follow_up_date == date(2026, 1, 6)
    assert triage.interaction.occurred_on == date(2026, 1, 1)


def test_without_an_event_date_today_applies() -> None:
    triage = classification_to_triage(
        klasse(category="networking"), eingabe(occurred_on=None), TODAY
    )
    assert triage.interaction.occurred_on == TODAY


def test_no_follow_up_yields_no_date() -> None:
    # Der Langweilfall: personal ohne Dringlichkeit — kein Datum, keine Flagge.
    triage = classification_to_triage(
        klasse(category="personal", sentiment="Positive"), eingabe(), TODAY
    )
    assert triage.interaction.follow_up_date is None
    assert triage.interaction.follow_up_needed is False


def test_compute_follow_up_date_offset_table() -> None:
    base = date(2026, 9, 23)
    assert compute_follow_up_date("job_application", "Positive", base) == date(2026, 9, 26)
    assert compute_follow_up_date("networking", "Positive", base) == date(2026, 10, 7)
    assert compute_follow_up_date("support", "Positive", base) is None
    assert compute_follow_up_date("personal", "Urgent", base) == date(2026, 9, 24)


# ---------------------------------------------------------------------------
# Titel, Typ-Fallback, Organisationen
# ---------------------------------------------------------------------------


def test_the_title_names_date_person_and_subject() -> None:
    triage = classification_to_triage(
        klasse(people=["Anna Meier"]),
        eingabe(subject="Kaffeenext Woche?"),
        TODAY,
    )
    assert triage.interaction.title == "2026-09-23 · Anna Meier · Kaffeenext Woche?"


def test_a_title_without_a_subject_falls_back_to_the_category() -> None:
    triage = classification_to_triage(
        klasse(category="business_opportunity"), eingabe(subject=None), TODAY
    )
    assert triage.interaction.title.startswith("2026-09-23 · Unknown · Business Opportunity")


def test_the_title_is_capped_at_120_characters() -> None:
    triage = classification_to_triage(
        klasse(people=["Anna Meier"]), eingabe(subject="x" * 300), TODAY
    )
    assert len(triage.interaction.title) <= 120


def test_an_empty_interaction_type_falls_back_to_the_input() -> None:
    triage = classification_to_triage(
        klasse(interaction_type=""), eingabe(interaction_type="Call"), TODAY
    )
    assert triage.interaction.interaction_type == "Call"


def test_organisations_are_passed_through() -> None:
    triage = classification_to_triage(
        klasse(organizations=["Ongiini e.V.", "Mistral AI"]), eingabe(), TODAY
    )
    assert triage.interaction.organization_names == ["Ongiini e.V.", "Mistral AI"]
    assert [o.name for o in triage.organizations] == ["Ongiini e.V.", "Mistral AI"]
    assert all(o.status == "Potential" for o in triage.organizations)


# ---------------------------------------------------------------------------
# Auto tags — an invariant against the real config
# ---------------------------------------------------------------------------


def test_auto_tags_always_stay_in_the_vocabulary() -> None:
    # Do not guess case by case, cover the whole surface: every combination of
    # category, sub-category and priority may only produce tags that
    # im Notion-Vokabular existieren — sonst lehnt Notion den Schreibzugriff ab.
    for category in CATEGORIES:
        for sub_category in SUB_CATEGORIES:
            for priority in ("High", "Medium", "Low"):
                tags = derive_auto_tags(category, sub_category, priority)
                assert set(tags) <= set(AUTO_TAGS), (category, sub_category, priority)


def test_auto_tags_have_no_duplicates() -> None:
    tags = derive_auto_tags("business_opportunity", "business_partnership", "High")
    assert len(tags) == len(set(tags))
    assert "high_priority" in tags


def test_an_auto_tag_only_on_a_matching_sub_category() -> None:
    # job_application_ongiini ist ein Auto-Tag nur, wenn es auch Sub-Kategorie ist.
    assert "job_application_ongiini" in derive_auto_tags(
        "job_application", "job_application_ongiini", "Low"
    )
    assert "job_application_ongiini" not in derive_auto_tags(
        "job_application", "job_application_foundation", "Low"
    )
