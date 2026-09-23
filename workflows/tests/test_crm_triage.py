"""Das Mapping classification → triage ist die Stelle, die in Notion schreibt.

``classification_to_triage`` übersetzt die Agent-Antwort in die „intended
writes" — ein Fehler hier landet zweimal täglich unbemerkt in der echten
Datenbank. Die drei dokumentierten Mapping-Entscheidungen (unknown → leeres
Select, Priority auf den Contact, action_items in die AI Analysis) haben hier
ihren Vertrag; getestet wird gegen die **echte** Konfiguration aus
``shared/crm.json``, nicht gegen kopierte Konstanten — dieselbe Regel wie beim
Scrivener-Test: Ein Instrument, das dieselben Annahmen enthält wie der Code,
misst nichts.

Alle Funktionen sind rein — jedes Datum kommt als Argument, kein Clock-Read.
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


def test_unknown_category_laesst_notion_select_leer() -> None:
    triage = classification_to_triage(
        klasse(category="unknown", sub_category="unknown"), eingabe(), TODAY
    )
    assert triage.interaction.category is None
    assert triage.interaction.sub_category is None
    assert "unknown" in triage.notes[0]


def test_kein_selbstkontakt_in_eigener_crm() -> None:
    # Ein Alias aus der echten Config, in Original­schreibung — gefiltert wird
    # case-insensitiv, und „Seb" als Anrede darf keinen Halbkontakt erzeugen.
    alias = next(iter(USER_ALIASES))
    triage = classification_to_triage(
        klasse(people=[alias.upper(), "Anna Meier"]), eingabe(), TODAY
    )
    assert [c.name for c in triage.contacts] == ["Anna Meier"]
    assert triage.interaction.contact_names == ["Anna Meier"]
    assert any("filtered self" in n for n in triage.notes)


def test_priority_liegt_auf_contact_nicht_auf_interaction() -> None:
    triage = classification_to_triage(
        klasse(priority="High", people=["Anna Meier"]), eingabe(), TODAY
    )
    assert triage.contacts[0].priority == "High"
    # Das Interactions-Modell hat das Feld bewusst gar nicht.
    assert "priority" not in type(triage.interaction).model_fields


def test_action_items_werden_in_die_ai_analysis_gefaltet() -> None:
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
# Priorität und Follow-up — deterministische Regeln
# ---------------------------------------------------------------------------


def test_leere_prioritaet_faellt_auf_die_regel_zurueck() -> None:
    # Der Agent muss priority liefern; leer fällt es auf die Regel zurück.
    triage = classification_to_triage(
        klasse(priority="", category="sales", sentiment="Positive", people=["Anna Meier"]),
        eingabe(),
        TODAY,
    )
    assert triage.contacts[0].priority == "Medium"


def test_suggest_priority_regeln() -> None:
    assert suggest_priority("networking", "Urgent") == "High"
    assert suggest_priority("job_application", "Positive") == "High"
    assert suggest_priority("follow_up", "Positive") == "Medium"
    assert suggest_priority("personal", "Positive") == "Low"


def test_geschaetztes_follow_up_datum_gewinnt() -> None:
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


def test_follow_up_rechnet_ab_dem_ereignis_nicht_ab_heute() -> None:
    triage = classification_to_triage(
        klasse(category="follow_up"),  # Regel: base+5
        eingabe(occurred_on=date(2026, 1, 1)),
        TODAY,
    )
    assert triage.interaction.follow_up_date == date(2026, 1, 6)
    assert triage.interaction.occurred_on == date(2026, 1, 1)


def test_ohne_ereignisdatum_gilt_heute() -> None:
    triage = classification_to_triage(
        klasse(category="networking"), eingabe(occurred_on=None), TODAY
    )
    assert triage.interaction.occurred_on == TODAY


def test_kein_follow_up_gibt_kein_datum() -> None:
    # Der Langweilfall: personal ohne Dringlichkeit — kein Datum, keine Flagge.
    triage = classification_to_triage(
        klasse(category="personal", sentiment="Positive"), eingabe(), TODAY
    )
    assert triage.interaction.follow_up_date is None
    assert triage.interaction.follow_up_needed is False


def test_compute_follow_up_date_offsettabelle() -> None:
    base = date(2026, 9, 23)
    assert compute_follow_up_date("job_application", "Positive", base) == date(2026, 9, 26)
    assert compute_follow_up_date("networking", "Positive", base) == date(2026, 10, 7)
    assert compute_follow_up_date("support", "Positive", base) is None
    assert compute_follow_up_date("personal", "Urgent", base) == date(2026, 9, 24)


# ---------------------------------------------------------------------------
# Titel, Typ-Fallback, Organisationen
# ---------------------------------------------------------------------------


def test_titel_nennt_datum_person_und_betreff() -> None:
    triage = classification_to_triage(
        klasse(people=["Anna Meier"]),
        eingabe(subject="Kaffeenext Woche?"),
        TODAY,
    )
    assert triage.interaction.title == "2026-09-23 · Anna Meier · Kaffeenext Woche?"


def test_titel_ohne_betreff_faellt_auf_die_kategorie_zurueck() -> None:
    triage = classification_to_triage(
        klasse(category="business_opportunity"), eingabe(subject=None), TODAY
    )
    assert triage.interaction.title.startswith("2026-09-23 · Unknown · Business Opportunity")


def test_titel_ist_auf_120_zeichen_gedeckelt() -> None:
    triage = classification_to_triage(
        klasse(people=["Anna Meier"]), eingabe(subject="x" * 300), TODAY
    )
    assert len(triage.interaction.title) <= 120


def test_leerer_interaction_type_faellt_auf_die_eingabe_zurueck() -> None:
    triage = classification_to_triage(
        klasse(interaction_type=""), eingabe(interaction_type="Call"), TODAY
    )
    assert triage.interaction.interaction_type == "Call"


def test_organisationen_werden_durchgereicht() -> None:
    triage = classification_to_triage(
        klasse(organizations=["Ongiini e.V.", "Mistral AI"]), eingabe(), TODAY
    )
    assert triage.interaction.organization_names == ["Ongiini e.V.", "Mistral AI"]
    assert [o.name for o in triage.organizations] == ["Ongiini e.V.", "Mistral AI"]
    assert all(o.status == "Potential" for o in triage.organizations)


# ---------------------------------------------------------------------------
# Auto-Tags — Invariante gegen die echte Config
# ---------------------------------------------------------------------------


def test_auto_tags_bleiben_immer_im_vokabular() -> None:
    # Nicht pro Fall raten, sondern die ganze Fläche abdecken: Jede Kombination
    # aus Kategorie, Sub-Kategorie und Priorität darf nur Tags erzeugen, die
    # im Notion-Vokabular existieren — sonst lehnt Notion den Schreibzugriff ab.
    for category in CATEGORIES:
        for sub_category in SUB_CATEGORIES:
            for priority in ("High", "Medium", "Low"):
                tags = derive_auto_tags(category, sub_category, priority)
                assert set(tags) <= set(AUTO_TAGS), (category, sub_category, priority)


def test_auto_tags_sind_ohne_duplikate() -> None:
    tags = derive_auto_tags("business_opportunity", "business_partnership", "High")
    assert len(tags) == len(set(tags))
    assert "high_priority" in tags


def test_auto_tag_nur_bei_passender_sub_kategorie() -> None:
    # job_application_ongiini ist ein Auto-Tag nur, wenn es auch Sub-Kategorie ist.
    assert "job_application_ongiini" in derive_auto_tags(
        "job_application", "job_application_ongiini", "Low"
    )
    assert "job_application_ongiini" not in derive_auto_tags(
        "job_application", "job_application_foundation", "Low"
    )
