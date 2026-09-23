"""Prüfungen ohne Ermessen — und der Werkkontext für die, die Ermessen brauchen.

Was hier steht, entscheidet **Tatsachen**: Kommt ein Suchtext im Absatz vor?
Ändert ein Befund überhaupt etwas? Greift er in direkte Rede ein? Nennt er eine
Regel, die es gibt? Das sind Prüfungen, die kein Modell braucht, nie unsicher
sind und nichts kosten — sie laufen vor jedem Modellaufruf.

**Urteile stehen nicht hier.** Ob ein Befund berechtigt ist oder ob einer fehlt,
beantwortet ``buch-gegenlesen`` — ein zweites Augenpaar, das denselben Abschnitt
sieht wie die erste Stufe. Die Vorgängerfassung dieser Datei hieß ``judge.py``
und enthielt beides: die Invarianten und einen bewertenden Judge, der je Befund
lief und nur ``search`` und ``replace`` bekam. Dass er den Satz nicht sah, zu dem
er urteilen sollte, ist mir erst aufgefallen, als der Name der Datei nicht mehr
verriet, was darin liegt. Deshalb heißt sie jetzt nach dem, was sie tut.

``werk_kontext`` bleibt hier, weil es dieselbe Quelle liest wie die Filter: die
Eigenheiten dieses Werks aus ``shared/buch.json``.
"""

from __future__ import annotations

import re
import unicodedata

from . import config
from .models import BefundMitUrteil


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


def werk_kontext(kriterium: str, stimmprofil_text: str = "") -> str:
    """Der Kontext, den ein Kriterium zum Urteilen braucht.

    "Ist das überhaupt ein Fehler?" laesst sich nicht allgemein beantworten -- es
    haengt vom Werk ab. Ohne diesen Kontext hielt der Judge messbar
    ``runter`` -> ``hinunter`` fuer berechtigt, weil es standardsprachlich richtig
    ist. Fuer dieses Werk ist es falsch: In allen vier gemessenen Konfigurationen
    fiel er bei genau diesen Faellen durch.
    """
    if kriterium == "stimmtreue":
        return stimmprofil_text
    if kriterium != "berechtigung":
        return ""
    formen = ", ".join(sorted(config.GEWOLLTE_UMGANGSSPRACHE))
    return (
        "GEWOLLTE EIGENHEITEN DIESES WERKS - ihre Korrektur ist KEIN berechtigter Befund:\n"
        f"- Umgangssprachliche Formen im Erzaehltext: {formen}\n"
        "- Umgangssprache in direkter Rede: Figuren sprechen, wie sie sprechen.\n"
        "- Kurze, unvollstaendige Saetze als Stilmittel.\n"
        "- Wiederholung, wenn sie erkennbar Absicht ist.\n"
        "Berechtigt sind nur Verstoesse gegen Rechtschreibung, Zeichensetzung oder "
        "Grammatik, die auch in einem Diktat angestrichen wuerden."
    )
