"""Bewertung von Lektoratsvorschlägen — mit Weiche zwischen zwei Backends.

Studio-Observability (``client.beta.observability.judges``) ist auf dem Pro-Plan
nicht erreichbar: ``GET /v1/observability/judges`` antwortet mit HTTP 404. Das
Muster ist trotzdem richtig, also bauen wir es selbst — ein Judge-Agent mit
striktem Schema, aufgerufen wie jeder andere Agent.

Die Weiche in ``shared/buch.json`` (``judges.backend``) hält den späteren
Umstieg lokal: Sollte Mistral Observability für Pro öffnen, sind die Kriterien
bereits als versionierte Texte da und müssten nur registriert werden.

**Nur ein Kriterium darf sperren.** „Treue" entscheidet, ob ein Vorschlag dem
Autor überhaupt angezeigt wird, denn er ist das Einzige, was den Weg zum
automatischen Schreiben absichert. Die übrigen Kriterien bewerten, ohne zu
blockieren — falsche Härte kostet einen Vorschlag, falsche Milde kostet
Vertrauen in jeden folgenden.

Rein: keine I/O. Die Aktivität, die den Judge-Agent auslöst, steht in
``agenten.py``.
"""

from __future__ import annotations

import re
import unicodedata

from . import config
from .models import BefundMitUrteil


def kriterium_text(name: str) -> str:
    """Die Frage, die der Judge-Agent beantworten soll."""
    k = config.JUDGE_KRITERIEN.get(name) or {}
    return k.get("frage", name)


def sperrt_unter(name: str) -> int | None:
    """Ab welchem Score ein Kriterium einen Vorschlag zurückhält (None = nie)."""
    k = config.JUDGE_KRITERIEN.get(name) or {}
    return k.get("sperrt_unter")


def aktive_kriterien() -> list[str]:
    return config.AKTIVE_JUDGES


def wende_urteil_an(befund: BefundMitUrteil, kriterium: str, score: int) -> BefundMitUrteil:
    """Trägt einen Score ein und sperrt den Befund, falls das Kriterium das vorsieht."""
    befund.judge[kriterium] = score
    grenze = sperrt_unter(kriterium)
    if grenze is not None and score < grenze:
        befund.gesperrt = True
        befund.sperrgrund = f"{kriterium} {score}/5 (Grenze {grenze})"
    return befund


def teile_auf(
    befunde: list[BefundMitUrteil],
) -> tuple[list[BefundMitUrteil], list[BefundMitUrteil]]:
    """Trennt anzuzeigende von gesperrten Befunden."""
    return (
        [b for b in befunde if not b.gesperrt],
        [b for b in befunde if b.gesperrt],
    )


def filtere_ohne_regelbezug(
    befunde: list[BefundMitUrteil], bekannte_regeln: set[str]
) -> tuple[list[BefundMitUrteil], list[str]]:
    """Verwirft Stilvorschläge, die sich auf keine Stimmprofil-Regel berufen.

    Das ist der Durchsetzungshaken hinter ``regel_id``: Ohne ihn zitiert der
    Agent das Profil bestenfalls dekorativ. Ausnahme sind Befunde mit Schwere
    „hoch" — wenn etwas wirklich schiefliegt, soll eine fehlende Regel es nicht
    verschlucken.

    Gibt ``(behalten, hinweise)`` zurück; die Hinweise nennen, was warum wegfiel.
    """
    behalten: list[BefundMitUrteil] = []
    hinweise: list[str] = []
    for b in befunde:
        if b.regel_id and b.regel_id in bekannte_regeln:
            behalten.append(b)
        elif b.schwere == "hoch":
            behalten.append(b)
            if b.regel_id and b.regel_id != "kein-bezug":
                hinweise.append(
                    f"Befund beruft sich auf unbekannte Regel {b.regel_id!r} — "
                    f"wegen Schwere 'hoch' trotzdem angezeigt."
                )
        else:
            hinweise.append(
                f"verworfen (ohne Regelbezug, Schwere {b.schwere}): {b.search[:60]!r}"
            )
    return behalten, hinweise


def _gleich(a: str, b: str) -> bool:
    """Ob zwei Textstellen sich nur in Unicode-Normalform unterscheiden."""
    n = lambda s: unicodedata.normalize("NFC", s).strip()  # noqa: E731
    return n(a) == n(b)


def verwerfe_nichtbefunde(
    befunde: list[BefundMitUrteil],
) -> tuple[list[BefundMitUrteil], list[str]]:
    """Filtert Befunde, die gar keine Änderung enthalten.

    Im ersten echten Lauf meldete das Korrektorat eine „Typografie-Korrektur“,
    deren ``search`` und ``replace`` zeichengleich waren — das Modell hatte eine
    Regel erkannt, die bereits erfüllt war. So etwas kostet Vertrauen in jeden
    anderen Befund und ist billig deterministisch abzufangen.
    """
    behalten, hinweise = [], []
    for b in befunde:
        if _gleich(b.search, b.replace):
            hinweise.append(f"Nicht-Befund verworfen (unverändert): {b.search[:60]!r}")
        else:
            behalten.append(b)
    return behalten, hinweise


# Direkte Rede in diesem Manuskript: „…“
_REDE = re.compile(r"„[^“]*“")


def _ueberlappt(absatz: str, suchtext: str, stelle: re.Match[str]) -> bool:
    """Ob ein Suchtext eine Redestelle berührt."""
    i = absatz.find(suchtext)
    if i < 0:
        return False
    return i < stelle.end() and stelle.start() < i + len(suchtext)


def verwerfe_eingriffe_in_rede(
    befunde: list[BefundMitUrteil], absaetze: list[str]
) -> tuple[list[BefundMitUrteil], list[str]]:
    """Hält das Korrektorat aus der direkten Rede heraus.

    Figuren dürfen umgangssprachlich sprechen — „Ne“ statt „Nein“ ist Figurenrede,
    kein Rechtschreibfehler. Die Agent-Instruktion sagt das bereits; dieser Filter
    setzt es durch, statt darauf zu vertrauen. Echte Tippfehler in der Rede gehen
    dabei mit verloren, das ist der bewusste Preis.
    """
    behalten, hinweise = [], []
    for b in befunde:
        absatz = absaetze[b.absatz_index] if 0 <= b.absatz_index < len(absaetze) else ""
        # Überlappung, nicht Enthaltensein: Ein Suchtext wie 'zu sagen: „Ne'
        # ragt über die Redegrenze hinaus und wäre sonst nicht erkannt worden.
        in_rede = any(
            _ueberlappt(absatz, b.search, stelle) for stelle in _REDE.finditer(absatz)
        )
        if in_rede and b.art in ("rechtschreibung", "grammatik"):
            hinweise.append(
                f"In direkter Rede belassen ({b.art}): {b.search[:50]!r}"
            )
        else:
            behalten.append(b)
    return behalten, hinweise


def _geaenderte_woerter(vorher: str, nachher: str) -> list[tuple[str, str]]:
    """Die Wortpaare, in denen sich zwei Textstellen unterscheiden.

    Wortweise statt Exakt-Vergleich: Der Agent liefert ``search`` mal als bloßes
    Wort („runter"), mal eingebettet („ziehen mich noch tiefer runter"). Ein
    Filter, der nur auf das nackte Wort passt, greift dann nicht.

    Gibt eine leere Liste zurück, wenn sich die Wortzahl unterscheidet — dann ist
    es keine reine Wortersetzung und der Fall gehört nicht hierher.
    """
    a, b = vorher.split(), nachher.split()
    if len(a) != len(b):
        return []
    entkleiden = lambda w: w.strip('.,;:!?„“"\'()').lower()  # noqa: E731
    return [
        (entkleiden(x), entkleiden(y))
        for x, y in zip(a, b, strict=True)
        if entkleiden(x) != entkleiden(y)
    ]


def verwerfe_gewollte_umgangssprache(
    befunde: list[BefundMitUrteil],
) -> tuple[list[BefundMitUrteil], list[str]]:
    """Schützt die Umgangssprache des Autors vor „Standardisierung“.

    Der Agent kennt die Regel und begründet in ``warum`` sogar selbst, warum der
    Befund hinfällig ist — meldet ihn aber, weil sein Schema kein Feld dafür hat.
    Eine Liste im Code ist zuverlässiger als die Hoffnung, dass ein Modell
    schweigt. Die Paare stehen in ``shared/buch.json`` und können dort wachsen.
    """
    behalten, hinweise = [], []
    for b in befunde:
        geaendert = _geaenderte_woerter(b.search, b.replace)
        # Nur wenn die EINZIGE Änderung ein geschütztes Paar ist. Ein Befund, der
        # nebenbei noch etwas anderes korrigiert, bleibt erhalten.
        if geaendert and all(
            config.GEWOLLTE_UMGANGSSPRACHE.get(v) == n for v, n in geaendert
        ):
            paare = ", ".join(f"{v}→{n}" for v, n in geaendert)
            hinweise.append(f"Umgangssprache geschützt ({paare}): {b.search[:50]!r} bleibt")
        else:
            behalten.append(b)
    return behalten, hinweise


def korrigiere_absatz_index(
    befunde: list[BefundMitUrteil], absaetze: list[str]
) -> tuple[list[BefundMitUrteil], list[str]]:
    """Prüft und repariert den ``absatz_index`` jedes Befunds.

    Der Agent zählt nicht zuverlässig: Im ersten Lauf meldete er einen Befund für
    Absatz 3, dessen Suchtext ausschließlich in Absatz 4 steht. Für die Anzeige
    ist das ärgerlich — für den späteren Write-back wäre es gefährlich, weil der
    Anker genau darauf aufsetzt.

    Deshalb wird hier verifiziert statt vertraut:

    * Steht ``search`` genau einmal im angegebenen Absatz → alles gut.
    * Steht es dort nicht, aber genau einmal in **einem** anderen Absatz → Index
      wird korrigiert und der Fall gemeldet.
    * Steht es nirgends, mehrfach im selben Absatz oder in mehreren Absätzen →
      Befund wird verworfen. Mehrdeutigkeit ist kein Fall für Raten.
    """
    behalten, hinweise = [], []
    for b in befunde:
        passend = [i for i, p in enumerate(absaetze) if p.count(b.search) == 1]

        if b.absatz_index in passend:
            behalten.append(b)
        elif len(passend) == 1:
            hinweise.append(
                f"Absatz-Index korrigiert: {b.absatz_index} → {passend[0]} "
                f"für {b.search[:40]!r}"
            )
            b.absatz_index = passend[0]
            behalten.append(b)
        else:
            gesamt = sum(p.count(b.search) for p in absaetze)
            grund = "nicht gefunden" if gesamt == 0 else f"{gesamt}-mal im Abschnitt, nicht eindeutig"
            hinweise.append(f"verworfen ({grund}): {b.search[:50]!r}")
    return behalten, hinweise
