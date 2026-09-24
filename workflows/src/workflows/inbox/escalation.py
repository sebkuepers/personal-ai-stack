"""Die Eskalationsregel der Inbox-Kaskade — deterministisch, hier getestet.

Small sichtet alles (schnell, günstig — die Masse sind Newsletter und
Notifications). Medium prüft nur nach, wo ein Small-Fehler teuer würde:
Antwortbedarf, Geldfluss, Frist heute — und die beiden kleinen, aber
heiklen Typen (Korrespondenz und „sonstiges", wo ein verpasster
Antwortbedarf unterginge, bevor jemand nachsieht).

Die Regel ist absichtlich Python und nicht Modellgefühl: Sie entscheidet
über Geld, und ihre Fehlrichtungen sind asymmetrisch —
- Small meldet zu viel → medium korrigiert (billig).
- Small verpasst etwas Kritisches → es muss trotzdem eskalieren.
Deshalb eskaliert sie auf TYP-Ebene bei correspondence/other und auf FELD-
Ebene bei needs_reply/finanzen/urgency.
"""

from __future__ import annotations

from workflows.inbox.models import InboxReview

# Typen, die IMMER nachgesehen werden: selten im Volumen, kritisch im Fehler.
ALWAYS_ESCALATE = {"correspondence", "other"}


def needs_second_review(review: InboxReview) -> bool:
    """True, wenn die zweite Stufe (medium) diese Sichtung prüfen muss."""
    return (
        review.needs_reply
        or review.finance_type != "none"
        or review.urgency == "today"
        or review.type in ALWAYS_ESCALATE
    )
