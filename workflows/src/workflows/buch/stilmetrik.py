"""Deterministische Stilkennzahlen — messen, bevor ein Modell interpretiert.

Der Grund für dieses Modul: Fragt man ein Sprachmodell „beschreibe die Stimme
dieses Autors", bekommt man *„warm, humorvoll, konkrete Bilder, kurze Sätze"*.
Das ist wahr, nutzlos und vor allem **nicht verletzbar** — eine Regel, gegen die
man nicht verstoßen kann, kann auch keinen Verstoß erkennen.

Diese Zahlen machen daraus etwas Prüfbares: nicht „kurze Sätze", sondern „Median
11 Wörter, 18 % der Sätze höchstens 5 Wörter lang, der längste im Buch hat 46".
Gegen so etwas kann ein Stil-Agent tatsächlich messen, und ein Judge kann
widersprechen.

Alles hier ist rein: kein Modell, kein Netz, kein Zufall. Damit sind die Werte
reproduzierbar und gehören in den deterministischen Teil eines Workflows.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

# Satzende: . ! ? … — gefolgt von Leerraum. Abkürzungen mit Punkt (z. B., d. h.)
# werden vorher geschützt, sonst zerfallen Sätze an ihnen.
_ABKUERZUNGEN = [
    "z. B.", "z.B.", "d. h.", "d.h.", "u. a.", "u.a.", "bzw.", "ca.", "vgl.",
    "Nr.", "Dr.", "Prof.", "St.", "ggf.", "inkl.", "evtl.", "usw.", "etc.",
]
_SCHUTZ = ""

_SATZENDE = re.compile(r"(?<=[.!?…])[\s]+(?=[„\"»'(\[]?[A-ZÄÖÜ0-9])")
_WORT = re.compile(r"[\wÄÖÜäöüß-]+", re.UNICODE)

# Deutsche Anführung: „…“ — der Marker für direkte Rede in diesem Manuskript.
_REDE = re.compile(r"„[^“]{2,}“")

_NOMINALSTIL = re.compile(r"\b\w{4,}(ung|heit|keit|nis|tum|schaft)(en)?\b", re.IGNORECASE)
_PASSIV = re.compile(r"\b(wurde|wurden|wird|werden)\b\s+(?:\w+\s+){0,3}?ge\w+t?\b", re.IGNORECASE)
_FUELLWOERTER = [
    "eigentlich", "irgendwie", "quasi", "sozusagen", "halt", "eben", "ja",
    "wohl", "durchaus", "relativ", "ziemlich", "recht", "etwas", "einfach",
    "natürlich", "tatsächlich", "vielleicht", "offensichtlich", "mittlerweile",
]


def saetze(text: str) -> list[str]:
    """Zerlegt Text in Sätze, mit Schutz für gängige deutsche Abkürzungen."""
    geschuetzt = text
    for a in _ABKUERZUNGEN:
        geschuetzt = geschuetzt.replace(a, a.replace(".", _SCHUTZ))
    teile = _SATZENDE.split(geschuetzt)
    return [t.replace(_SCHUTZ, ".").strip() for t in teile if t.strip()]


def woerter(text: str) -> list[str]:
    return _WORT.findall(text)


@dataclass
class StilMetrik:
    """Messbare Eigenschaften eines Textkorpus."""

    abschnitte: int = 0
    absaetze: int = 0
    saetze: int = 0
    woerter: int = 0

    satz_median: float = 0.0
    satz_mittel: float = 0.0
    satz_kuerzester: int = 0
    satz_laengster: int = 0
    satz_laengster_text: str = ""
    anteil_kurzsaetze: float = 0.0  # <= 5 Wörter
    anteil_langsaetze: float = 0.0  # >= 25 Wörter
    satzlaengen_histogramm: dict[str, int] = field(default_factory=dict)

    absatz_median_saetze: float = 0.0
    absatz_median_woerter: float = 0.0

    anteil_ich_anfang: float = 0.0
    anteil_und_aber_anfang: float = 0.0
    dialoganteil: float = 0.0

    nominalstil_pro_1000: float = 0.0
    passiv_pro_1000: float = 0.0
    fuellwoerter_pro_1000: float = 0.0
    type_token_ratio: float = 0.0

    interpunktion: dict[str, int] = field(default_factory=dict)
    haeufigste_trigramme: list[tuple[str, int]] = field(default_factory=list)
    haeufigste_satzanfaenge: list[tuple[str, int]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def als_text(self) -> str:
        """Kompakte Fassung für den Prompt eines Agents."""
        return "\n".join(
            [
                f"Korpus: {self.abschnitte} Abschnitte, {self.absaetze} Absätze, "
                f"{self.saetze} Sätze, {self.woerter} Wörter.",
                f"Satzlänge: Median {self.satz_median:.0f} Wörter, Mittel {self.satz_mittel:.1f}, "
                f"kürzester {self.satz_kuerzester}, längster {self.satz_laengster}.",
                f"Kurze Sätze (≤5 Wörter): {self.anteil_kurzsaetze:.0%}. "
                f"Lange Sätze (≥25 Wörter): {self.anteil_langsaetze:.0%}.",
                f"Absatz: Median {self.absatz_median_saetze:.0f} Sätze / "
                f"{self.absatz_median_woerter:.0f} Wörter.",
                f"Sätze, die mit „Ich“ beginnen: {self.anteil_ich_anfang:.0%}; "
                f"mit „Und“/„Aber“: {self.anteil_und_aber_anfang:.0%}.",
                f"Anteil direkter Rede an allen Sätzen: {self.dialoganteil:.0%}.",
                f"Nominalstil: {self.nominalstil_pro_1000:.1f}/1000 Wörter. "
                f"Passiv: {self.passiv_pro_1000:.1f}/1000. "
                f"Füllwörter: {self.fuellwoerter_pro_1000:.1f}/1000.",
                f"Type-Token-Ratio: {self.type_token_ratio:.3f}.",
                f"Längster Satz: „{self.satz_laengster_text[:200]}“",
            ]
        )


def _histogramm(laengen: list[int]) -> dict[str, int]:
    grenzen = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 35), (36, 999)]
    out: dict[str, int] = {}
    for lo, hi in grenzen:
        name = f"{lo}-{hi}" if hi < 999 else f"{lo}+"
        out[name] = sum(1 for x in laengen if lo <= x <= hi)
    return out


def messe(absaetze: list[str], *, abschnitte: int = 0) -> StilMetrik:
    """Berechnet alle Kennzahlen über eine Liste von Absätzen."""
    m = StilMetrik(abschnitte=abschnitte, absaetze=len(absaetze))
    if not absaetze:
        return m

    volltext = "\n\n".join(absaetze)
    alle_saetze: list[str] = []
    absatz_saetze: list[int] = []
    absatz_woerter: list[int] = []

    for absatz in absaetze:
        s = saetze(absatz)
        alle_saetze.extend(s)
        absatz_saetze.append(len(s))
        absatz_woerter.append(len(woerter(absatz)))

    alle_woerter = woerter(volltext)
    laengen = [len(woerter(s)) for s in alle_saetze]
    laengen = [x for x in laengen if x > 0]

    m.saetze = len(alle_saetze)
    m.woerter = len(alle_woerter)

    if laengen:
        m.satz_median = statistics.median(laengen)
        m.satz_mittel = statistics.fmean(laengen)
        m.satz_kuerzester = min(laengen)
        m.satz_laengster = max(laengen)
        m.satz_laengster_text = max(alle_saetze, key=lambda s: len(woerter(s)))
        m.anteil_kurzsaetze = sum(1 for x in laengen if x <= 5) / len(laengen)
        m.anteil_langsaetze = sum(1 for x in laengen if x >= 25) / len(laengen)
        m.satzlaengen_histogramm = _histogramm(laengen)

    if absatz_saetze:
        m.absatz_median_saetze = statistics.median(absatz_saetze)
        m.absatz_median_woerter = statistics.median(absatz_woerter)

    if alle_saetze:
        m.anteil_ich_anfang = sum(1 for s in alle_saetze if s.startswith("Ich")) / len(alle_saetze)
        m.anteil_und_aber_anfang = sum(
            1 for s in alle_saetze if s.startswith(("Und ", "Aber ", "Dann ", "Doch "))
        ) / len(alle_saetze)
        m.dialoganteil = sum(1 for s in alle_saetze if _REDE.search(s)) / len(alle_saetze)

    if alle_woerter:
        je1000 = 1000 / len(alle_woerter)
        m.nominalstil_pro_1000 = len(_NOMINALSTIL.findall(volltext)) * je1000
        m.passiv_pro_1000 = len(_PASSIV.findall(volltext)) * je1000
        klein = [w.lower() for w in alle_woerter]
        m.fuellwoerter_pro_1000 = sum(klein.count(f) for f in _FUELLWOERTER) * je1000
        m.type_token_ratio = len(set(klein)) / len(klein)

    m.interpunktion = {
        "gedankenstrich": volltext.count("—") + volltext.count(" – "),
        "auslassung": volltext.count("…") + volltext.count("..."),
        "fragezeichen": volltext.count("?"),
        "ausrufezeichen": volltext.count("!"),
        "doppelpunkt": volltext.count(":"),
        "semikolon": volltext.count(";"),
        "klammer": volltext.count("("),
        "direkte_rede": len(_REDE.findall(volltext)),
    }

    klein = [w.lower() for w in alle_woerter]
    trigramme = Counter(
        " ".join(klein[i : i + 3]) for i in range(len(klein) - 2)
    )
    m.haeufigste_trigramme = [
        (t, n) for t, n in trigramme.most_common(25) if n >= 3
    ][:15]

    anfaenge = Counter(
        " ".join(woerter(s)[:2]).lower() for s in alle_saetze if woerter(s)
    )
    m.haeufigste_satzanfaenge = anfaenge.most_common(12)

    return m


def messe_manuskript(manuskript) -> StilMetrik:  # noqa: ANN001 — Manuskript, zirkelfrei
    """Kennzahlen über den gesamten Entwurf eines Werks."""
    mit_text = [a for a in manuskript.abschnitte if a.hat_text]
    return messe(
        [p for a in mit_text for p in a.absaetze],
        abschnitte=len(mit_text),
    )
