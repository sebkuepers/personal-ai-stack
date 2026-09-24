"""Pydantic-Modelle für die inbox-Domäne.

Zwei Schichten wie bei CRM: ``InboxReview`` spiegelt das JSON-Schema des
Studio-Agents ``Inbox · Review`` exakt (``extra="forbid"``), und der Report
ist die deterministische Verdichtung einer Sichtungs-Runde.

Die Umschlag-Modelle sind bewusst body-los: ``search_threads`` liefert Bodies
IMMER null (live verifiziert, 644 Messages in zwei Läufen) — der Umschlag
(Absender, Betreff, Snippet, Labels) trägt die Klassifizierung, Bodies werden
nur einzeln über ``get_thread`` geholt, wo ein Abmeldelink gebraucht wird.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Umschläge — was die Gmail-Suche liefert
# --------------------------------------------------------------------------- #


class InboxEnvelope(BaseModel):
    """Umschlag einer empfangenen Mail. Der Body fehlt immer — siehe Modul-Docstring."""

    thread_id: str = ""
    message_id: str = ""
    sender: str = ""
    subject: str = ""
    snippet: str = ""
    labels: list[str] = Field(default_factory=list)
    category: str = ""  # CATEGORY_* ohne Präfix, z.B. "UPDATES"; "" wenn ohne Kategorie
    unread: bool = False
    received_on: date | None = None


class SentEnvelope(BaseModel):
    """Gesendete Mail — Empfänger und Betreff tragen Kontext und Antwort-Zustand."""

    thread_id: str = ""
    message_id: str = ""
    sender: str = ""  # die eigene Adresse (steht im Umschlag der gesendeten Mail)
    to: list[str] = Field(default_factory=list)
    subject: str = ""
    received_on: date | None = None


# --------------------------------------------------------------------------- #
# Eingaben
# --------------------------------------------------------------------------- #


class InboxScanInput(BaseModel):
    """Eingabe des Sichtungs-Workflows. Fenster in Tagen — Gmail-Suche kennt keine Stunden."""

    window_days: int = Field(
        default=1, description="Zeitfenster in Tagen für beide Pässe (Inbox und Sent)."
    )
    max_threads: int = Field(default=50, description="Höchstens so viele Inbox-Threads sichten.")
    max_unsub: int = Field(
        default=15, description="Höchstens so viele Bodies für Abmeldelinks holen."
    )
    second_review: bool = Field(
        default=True,
        description=(
            "Second review stage (medium) for critical cases. False = "
            "first stage (small) only — faster and cheaper, unverified."
        ),
    )


class SenderStatsInput(BaseModel):
    """Eingabe der Absender-Statistik — reine Arithmetik, kein Modell."""

    window_days: int = Field(default=90, description="Zeitfenster in Tagen.")
    query: str | None = Field(
        default=None,
        description=(
            "Gmail-Suchausdruck. Default: '-in:sent newer_than:<n>d' — alles Empfangene, "
            "das dich erreicht. Achtung: Spam und Trash sind von der Suche "
            "standardmäßig AUSGESCHLOSSEN (live verifiziert); 'in:anywhere' holt sie."
        ),
    )
    max_threads: int = Field(default=4000, description="Obergrenze der Durchsicht.")


# --------------------------------------------------------------------------- #
# Sichtung — Spiegel des Studio-Agent-Schemas
# --------------------------------------------------------------------------- #


class InboxReview(BaseModel):
    """Spiegelt das Antwortschema des Studio-Agents ``Inbox · Review`` exakt."""

    model_config = ConfigDict(extra="forbid")

    type: str                      # newsletter|notification|transaction|invoice_payment|correspondence|other
    needs_reply: bool
    urgency: str            # today|this_week|whenever
    subscription_group: str = ""          # sender cluster, "" if not applicable
    finance_type: str = "none"   # invoice|reminder|direct_debit|confirmation|none
    betrag: str = ""
    due_date: str = ""         # YYYY-MM-DD oder ""
    context_for_vibe: str = ""
    reasoning: str = ""


# --------------------------------------------------------------------------- #
# Report-Bausteine
# --------------------------------------------------------------------------- #


class ReplyItem(BaseModel):
    """Eine Mail, die eine Antwort von Sebastian erwartet — inklusive Antwort-Zustand."""

    sender: str
    subject: str
    urgency: str
    reasoning: str
    beantwortet: bool  # Empfänger steht im Sent-Fenster — er hat wohl schon geantwortet


class FinanceItem(BaseModel):
    """Eine Mail mit Geldfluss — erkannt, nicht verbucht."""

    sender: str
    subject: str
    art: str
    betrag: str
    due_date: str


class UnsubCandidate(BaseModel):
    """Ein Abmeldelink, deterministisch aus dem HTML gezogen — kein Modell."""

    sender: str
    subject: str
    thread_id: str
    url: str  # https-Link oder mailto:


class ReviewItem(BaseModel):
    """Eine gesichtete Mail mit ihrer Einordnung — der volle Per-Mail-Befund."""

    thread_id: str = ""  # Gmail-Thread-ID — der Aufräum-Plan greift darüber zu
    sender: str
    subject: str
    received_on: date | None
    second_review: bool = False  # the second stage re-checked this review
    review: InboxReview


class InboxScanReport(BaseModel):
    """Ergebnis eines Sichtungs-Laufs — reine Daten, nichts wurde verändert."""

    window_days: int
    inbox_found: int
    skipped_no_messages: int  # Threads, die ohne Umschlag kamen — schwankt pro Lauf (26–57)
    own_replies: int    # Threads im Posteingang, in denen er das letzte Wort hatte
    pages: int
    second_review_count: int = 0  # wie viele Sichtungen die zweite Stufe geprüft hat
    second_review_changed: int = 0  # wie oft sie das Ergebnis TATSÄCHLICH geändert hat (Kill-Switch)
    type_counts: dict[str, int] = Field(default_factory=dict)
    subscription_groups: dict[str, int] = Field(default_factory=dict)
    needs_reply: list[ReplyItem] = Field(default_factory=list)
    finanzen: list[FinanceItem] = Field(default_factory=list)
    kontext: list[str] = Field(default_factory=list)
    unsub_links: list[UnsubCandidate] = Field(default_factory=list)
    sent: list[SentEnvelope] = Field(default_factory=list)
    reviews: list[ReviewItem] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Absender-Statistik — die falsifizierbare Abbestell-Grundlage
# --------------------------------------------------------------------------- #


class SenderItem(BaseModel):
    """Ein Absender mit Mails und ungelesenen im Fenster — Arithmetik, keine Meinung."""

    sender: str
    mails: int
    unread: int


class SenderStats(BaseModel):
    """Ergebnis des Absender-Durchlaufs: Rangfolge nach Lärm, nicht nach Gefühl."""

    window_days: int
    query: str
    threads: int
    skipped_no_messages: int
    senders: list[SenderItem] = Field(default_factory=list)
    unread_total: int = 0


# --------------------------------------------------------------------------- #
# Aufräumen — Stufe 2/3 der Sicherheitsleiter, nur mit Freigabe pro Lauf
# --------------------------------------------------------------------------- #


class CleanupAction(BaseModel):
    """Was mit EINEM Thread passieren soll, aus seiner Sichtung abgeleitet."""

    thread_id: str
    aktion: str  # laerm | finanzen | antwort | behalten
    sender: str
    subject: str


class CleanupResult(BaseModel):
    """Was der Lauf tatsächlich getan hat — die Quittung pro Aktion."""

    archiviert: int = 0
    gelesen: int = 0
    gelabelt_finanzen: int = 0
    gelabelt_antwort: int = 0
    mailto_drafts: int = 0
    fehler: list[str] = Field(default_factory=list)
    skipped: int = 0
