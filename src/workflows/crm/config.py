"""Single source of truth for the personal-CRM workflows.

All IDs, model names, and Notion select-option vocabularies live here so that
a change to your Studio setup is a one-line edit, not a hunt across files.

NOTE on the Notion IDs: these are the data-source (collection) UUIDs confirmed
on 2026-06-05 with the full database schemas.  An earlier screenshot showed a
*different* set — if writes ever land in the wrong database, re-confirm these
in Studio (Context › Connectors / the Notion database "..." menu › Copy link).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Studio agent
# ---------------------------------------------------------------------------
# The CRM Classification Agent created in the Studio Playground.  Used by the
# *alternative* classifier path (classify_via_studio_agent) so Studio stays the
# single source of truth for the prompt.  The default classifier is self-
# contained (see prompts.py) and does not require this.
CRM_CLASSIFICATION_AGENT_ID = "ag_019e98ece5ab7083898098f84895ae79"  # "CRM - Classification Agent"

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
# Names that refer to you — filtered out of people_mentioned so you never end up
# as a contact in your own CRM. Lower-cased; matched case-insensitively.
USER_ALIASES = {"sebastian", "seb", "sebastian kuepers", "s. kuepers", "sebastian küpers"}

CLASSIFY_MODEL = "mistral-medium-latest"   # matches the Studio agent's model
AGENT_MODEL = "mistral-medium-latest"      # durable agents (Notion writer, triage)
DIGEST_MODEL = "mistral-medium-latest"

# ---------------------------------------------------------------------------
# Notion CRM data-source (collection) IDs
# ---------------------------------------------------------------------------
NOTION_DB = {
    "organizations": "0e98f520-be59-4c01-a493-4e0cf731d91f",
    "contacts": "3a0b4200-0c34-491d-86dc-86de07c4916c",
    "interactions": "a4c60162-2aa2-47de-8f7c-a1b57b669a26",
    # "projects":  re-confirm before use
}

# Human-readable Notion page URLs (handy for logs / digests).
NOTION_URL = {
    "organizations": "https://app.notion.com/p/905001b6311543e485a45e6a69074f74",
    "contacts": "https://app.notion.com/p/191604fb680a4c98b4fe1f82c94414cf",
    "interactions": "https://app.notion.com/p/d51513cd0fbf43c98f8e03d65603a120",
}

# Connector IDENTIFIERS — these are the lowercase API slugs, NOT the display
# names shown in the Studio UI ("Notion"/"Gmail"). Confirmed via
# client.beta.connectors.list_async() on 2026-06-05. connector() resolves
# against these. (IDs given for reference; the slug name resolves fine.)
CONNECTOR_NOTION = "notion"   # id 0198f11d-493e-76a8-9c90-913b7462e7de
CONNECTOR_GMAIL = "gmail"     # id 019df75b-9673-72be-ba4f-033723c972ea

# Exact connector tool names (from connectors.list_tools). Used by the direct
# ToolCallClient path and to brief the durable agents.
NOTION_TOOLS = {
    "search": "notion-search",          # find existing pages (find-or-create step 1)
    "fetch": "notion-fetch",            # read a page/database/data-source
    "create_pages": "notion-create-pages",
    "update_page": "notion-update-page",
}
GMAIL_TOOLS = {
    "search": "search_gmail",
    "open": "open_gmail_email",
    "draft": "draft_gmail_email",       # NOTE: Gmail connector can DRAFT only, not send.
}

# ---------------------------------------------------------------------------
# Controlled vocabularies — must stay in sync with the Notion select options.
# These drive both classification validation and the agent instructions.
# ---------------------------------------------------------------------------
CATEGORIES = [
    "job_application", "business_opportunity", "personal", "networking",
    "support", "collaboration", "sales", "follow_up", "unknown",
]
# NOTE: Notion's Interactions "Category" select has NO "unknown" option.
# When the model returns "unknown" we leave the Notion property empty.
SUB_CATEGORIES = [
    "job_application_ongiini", "job_application_foundation", "business_partnership",
    "sales_lead", "investor_pitch", "friend_catchup", "family_update",
    "project_discussion", "support_request", "unknown",
]
INTERACTION_TYPES = [
    "Email", "Meeting", "Call", "Message", "Application", "Interview", "Other",
]
SENTIMENTS = ["Positive", "Neutral", "Negative", "Urgent"]
PRIORITIES = ["High", "Medium", "Low"]

# Contacts "Auto-Tags" multi-select vocabulary (separate from categories).
AUTO_TAGS = [
    "job_application_ongiini", "job_application_foundation", "business_opportunity",
    "high_priority", "urgent", "personal", "networking", "support",
]
