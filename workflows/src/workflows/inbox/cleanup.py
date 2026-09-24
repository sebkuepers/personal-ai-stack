"""Der Aufräum-Plan — aus der Sichtung folgt, was in Gmail passiert.

Deterministisch und damit testbar: Der Plan ist reine Mathematik über den
Sichtungen, keine Modell-Entscheidung zur Laufzeit. Die gefährliche Richtung
ist das OVER-archivieren: Eine Mail, die Antwort oder Geld verlangt, darf nie
im Lärm landen — deshalb prüft die Regel ``needs_reply`` und
``finance_type`` VOR der Typ-Zugehörigkeit. Der Plan läuft ausschließlich
hinter einer Freigabe pro Sitzung; er wird nie still angewendet.
"""

from __future__ import annotations

from workflows.inbox.models import CleanupAction, ReviewItem

# Diese Typen sind Lärm — NUR solange keine Antwort und kein Geld im Spiel ist.
NOISE_TYPES = {"newsletter", "notification", "transaction"}

NOISE = "laerm"           # archivieren + gelesen + verarbeitet-Label
FINANCE = "finanzen"      # Label labels.finance, bleibt ungelesen im Posteingang
NEEDS_REPLY = "antwort"        # Label labels.needs_reply, bleibt ungelesen
KEEP = "behalten"      # keine Aktion — der unsichere Rest bleibt, wo er ist


def cleanup_plan(reviews: list[ReviewItem]) -> list[CleanupAction]:
    """Eine Sichtung → eine Aktion pro Thread."""
    plan: list[CleanupAction] = []
    for r in reviews:
        if r.review.needs_reply:
            aktion = NEEDS_REPLY
        elif r.review.finance_type != "none" or r.review.type == "invoice_payment":
            # Der Typ selbst zählt als Signal: Eine Mail, die der Erstblick für
            # Geldfluss hielt, wird nie nach Lärm-Logik behandelt — auch wenn
            # das finance_type-Feld leer blieb (widersprüchliche Sichtung).
            aktion = FINANCE
        elif r.review.type in NOISE_TYPES:
            aktion = NOISE
        elif r.review.type == "correspondence":
            aktion = NEEDS_REPLY  # ein Mensch hat geschrieben — nie Lärm, auch ohne Frist
        else:
            aktion = KEEP
        plan.append(
            CleanupAction(
                thread_id=r.thread_id,
                aktion=aktion,
                sender=r.sender,
                subject=r.subject,
            )
        )
    return plan


def cleanup_summary(plan: list[CleanupAction]) -> str:
    """Der Plan als ein Satz — für die Bestätigung vor dem Aufräumen."""
    laerm = [a for a in plan if a.aktion == NOISE]
    finanzen = [a for a in plan if a.aktion == FINANCE]
    antwort = [a for a in plan if a.aktion == NEEDS_REPLY]
    behalten = [a for a in plan if a.aktion == KEEP]
    teile = []
    if laerm:
        teile.append(f"{len(laerm)} archivieren + gelesen setzen")
    if finanzen:
        teile.append(f"{len(finanzen)} behalten (label inbox/finance)")
    if antwort:
        teile.append(f"{len(antwort)} behalten (label inbox/needs-reply)")
    if behalten:
        teile.append(f"{len(behalten)} unangetastet")
    return ", ".join(teile) if teile else "nichts zu tun"
