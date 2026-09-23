"""Pydantic-Modelle der Buch-Domäne.

Zwei Schichten, wie in ``crm/models.py``:

* **Schicht 1** — exakte Spiegel dessen, was die Studio-Agents laut ihrem
  ``response_format.json_schema`` zurückgeben. ``extra="forbid"`` entspricht
  ``additionalProperties: false`` im Schema; weicht eine Agent-Antwort ab, fällt
  es hier auf und nicht erst drei Schritte später.
* **Schicht 2** — die geprüften Objekte, mit denen der Rest arbeitet: das
  validierte Stimmprofil, Befunde, Entscheidungen.

Rein und importierbar in Workflow-Code (keine I/O, kein Client).
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ===========================================================================
# Schicht 1 — Spiegel der Agent-Schemata
# ===========================================================================


class Beobachtung(BaseModel):
    """Eine einzelne Auffälligkeit mit Beleg — die Währung des Map-Schritts."""

    model_config = ConfigDict(extra="forbid")

    beobachtung: str = Field(description="Was auffällt, in einem Satz")
    beleg: str = Field(description="Wörtliches Zitat aus dem Abschnitt")
    art: Literal["staerke", "schwaeche", "eigenart"] = Field(
        description="Stärke = trägt die Stimme, Schwäche = schadet ihr, Eigenart = fällt auf, ist aber neutral"
    )


class StimmProbe(BaseModel):
    """Ausgabe von ``buch-stimme-probe`` — die Beobachtung zu EINEM Abschnitt."""

    model_config = ConfigDict(extra="forbid")

    beispielsaetze: list[str] = Field(
        description="3-5 wörtliche Sätze, die für die Stimme des Autors typisch sind"
    )
    erzaehlhaltung: str
    tempus: str
    person: str
    beobachtungen: list[Beobachtung]
    wiederkehrende_konstruktionen: list[str] = Field(
        description="Satzmuster, die mehrfach vorkommen"
    )
    vermeidungen: list[str] = Field(
        description="Was der Autor erkennbar NICHT tut — oft aussagekräftiger als das, was er tut"
    )


class StimmregelRoh(BaseModel):
    """Eine Regel, wie der Reduce-Agent sie vorschlägt (noch ungeprüft)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Kurzer Bezeichner, z. B. R-behauptung-statt-bild")
    titel: str
    regel: str = Field(description="Die Regel als Anweisung, die man befolgen oder verletzen kann")
    warum: str
    beweis: list[str] = Field(description="Mindestens zwei wörtliche Sätze aus dem Manuskript")
    gegenbeispiel: str = Field(description="Wie ein Verstoß gegen die Regel klänge")
    pruefbar_als: str = Field(description="Woran ein Lektor oder Agent den Verstoß erkennt")
    quelle: Literal["manuskript", "notizen"]


class StimmProfilRoh(BaseModel):
    """Ausgabe von ``buch-stimme-profil`` — das aggregierte Profil, noch ungeprüft."""

    model_config = ConfigDict(extra="forbid")

    erzaehlhaltung: str
    tempus: str
    person: str
    regeln: list[StimmregelRoh]
    wiederkehrende_motive: list[str]
    vermeidungen: list[str]
    offene_fragen: list[str] = Field(
        description="Wo die Belege widersprüchlich waren oder die Datenlage zu dünn"
    )


# ===========================================================================
# Schicht 2 — das geprüfte Profil
# ===========================================================================


class Stimmregel(StimmregelRoh):
    """Eine Regel, die die Belegprüfung überstanden hat.

    ``annahmequote`` wird später **in Python** aus dem Entscheidungslog berechnet,
    nicht von einem Modell geschätzt: eine Regel, deren Vorschläge der Autor
    überwiegend ablehnt, wird automatisch auf ``beobachtung`` gesetzt — unabhängig
    davon, für wie überzeugend ein Modell sie hält.
    """

    model_config = ConfigDict(extra="forbid")

    status: Literal["aktiv", "beobachtung", "verworfen"] = "aktiv"
    annahmequote: float | None = None
    vorschlaege_gesamt: int = 0


class Korpus(BaseModel):
    """Woraus das Profil gebaut wurde — damit man später weiß, ob es noch passt."""

    model_config = ConfigDict(extra="forbid")

    abschnitte: int
    woerter: int
    kapitel: list[str]


class Stimmprofil(BaseModel):
    """Das Ergebnis von ``buch-stimmprofil`` — versioniert in ``shared/buch/<slug>-stimme.json``."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    werk: str
    erstellt_am: date
    korpus: Korpus
    metrik: dict = Field(default_factory=dict, description="Die deterministischen Kennzahlen")
    erzaehlhaltung: str
    tempus: str
    person: str
    regeln: list[Stimmregel]
    wiederkehrende_motive: list[str] = Field(default_factory=list)
    vermeidungen: list[str] = Field(default_factory=list)
    offene_fragen: list[str] = Field(default_factory=list)
    verworfene_regeln: list[dict] = Field(
        default_factory=list,
        description="Vom Modell vorgeschlagen, aber an der Belegprüfung gescheitert — mit Grund",
    )

    @property
    def aktive_regeln(self) -> list[Stimmregel]:
        return [r for r in self.regeln if r.status == "aktiv"]


# ===========================================================================
# Workflow-Eingaben
# ===========================================================================


class AbschnittEingabe(BaseModel):
    """Ein Abschnitt, wie ihn ein Workflow als Eingabe bekommt.

    Bewusst ohne Dateipfad: Workflows lesen kein Dateisystem (der produktive
    Worker läuft im Container). ``buchcli`` liest Scrivener und übergibt den Text.
    """

    uuid: str
    titel: str
    text: str
    pfad: list[str] = Field(default_factory=list)
    synopsis: str | None = None


class StimmprofilInput(BaseModel):
    """Eingabe von ``buch-stimmprofil``.

    Kennzahlen und Autorennotizen kommen fertig aufbereitet herein — sie zu
    berechnen ist reine, deterministische Arbeit und gehört nicht in einen
    Agent-Aufruf.
    """

    werk: str
    abschnitte: list[AbschnittEingabe]
    korpus_text: str = Field(
        description="Der gesamte Manuskripttext — Grundlage der Belegprüfung"
    )
    metrik_text: str = Field(description="Die gemessenen Kennzahlen als Fließtext")
    metrik: dict = Field(default_factory=dict)
    notizregeln: str = Field(
        default="", description="Die selbst formulierten Lektoratsregeln des Autors"
    )
    woerter: int = 0
    kapitel: list[str] = Field(default_factory=list)
    version: int = 1
    parallel: int = Field(
        default=6, description="Wie viele Abschnitte gleichzeitig analysiert werden"
    )


# ===========================================================================
# Schicht 1 — Lektoratsbefunde (Ebene 1 und 2)
# ===========================================================================


class Korrektur(BaseModel):
    """Ein Befund von ``buch-korrektorat``."""

    model_config = ConfigDict(extra="forbid")

    absatz_index: int
    search: str = Field(description="Der zu ersetzende Text — muss GENAU EINMAL im Absatz vorkommen")
    replace: str
    art: Literal[
        "rechtschreibung", "komma", "grammatik", "tempus", "typografie", "formatierung"
    ]
    konfidenz: float = Field(ge=0, le=1)
    warum: str


class Korrekturen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    korrekturen: list[Korrektur]


class Stilvorschlag(BaseModel):
    """Ein Befund von ``buch-stil``.

    ``regel_id`` ist der Durchsetzungshaken: Jeder Vorschlag muss eine Regel des
    Stimmprofils zitieren oder ``kein-bezug`` sagen. Vorschläge mit
    ``kein-bezug`` werden in Workflow-Code verworfen, außer bei Schwere „hoch" —
    sonst bleibt das Profil Dekoration.
    """

    model_config = ConfigDict(extra="forbid")

    absatz_index: int
    search: str
    replace: str
    problem: Literal[
        "wiederholung", "satzlaenge", "rhythmus", "fuellwort", "klischee",
        "passiv", "nominalstil", "erklaert_statt_gezeigt", "perspektivbruch", "stimmbruch",
    ]
    schwere: Literal["hoch", "mittel", "niedrig"]
    warum: str
    regel_id: str = Field(description="ID einer Stimmprofil-Regel oder 'kein-bezug'")


class Stilvorschlaege(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vorschlaege: list[Stilvorschlag]


class LektoratInput(BaseModel):
    """Eingabe der Lektorats-Workflows — ein Abschnitt, fertig gelesen.

    Wie bei :class:`StimmprofilInput` kommt der Text herein, statt gelesen zu
    werden: Workflows fassen kein Dateisystem an.
    """

    werk: str
    abschnitt: AbschnittEingabe
    absaetze: list[str] = Field(
        default_factory=list,
        description="Absätze einzeln — Befunde adressieren sie über absatz_index",
    )
    stimmprofil_text: str = Field(
        default="", description="Gerendertes Stimmprofil; nur die Stilebene braucht es"
    )
    max_befunde: int = 12
    mit_judge: bool = Field(
        default=True, description="Bewertung vor der Anzeige (empfohlen)"
    )
    max_runden: int = Field(
        default=1,
        description=(
            "Wie oft ein abgelehnter Befund an den Agent zurückgeht. "
            "1 = kein Loop, nur sperren — das ist der gemessene Standard. "
            "Ein A/B-Lauf am selben Abschnitt ergab: ohne Loop 0 Befunde (alles sauber "
            "gefiltert), mit Loop 6 Befunde, alle unsinnig. Der Agent nimmt die "
            "Aufforderung 'enger fassen' wörtlich und minimiert seinen Vorschlag bis zur "
            "Sinnlosigkeit ('runter.' → 'runter'). Erst wieder erhöhen, wenn ein Eval "
            "mit annotierten Erwartungen zeigt, dass es hilft."
        ),
    )


class BefundMitUrteil(BaseModel):
    """Ein Befund samt Bewertung — und der Entscheidung, ob er angezeigt wird."""

    model_config = ConfigDict(extra="forbid")

    ebene: Literal["korrektorat", "stil"]
    absatz_index: int
    search: str
    replace: str
    art: str = Field(description="Korrekturart bzw. Stilproblem")
    schwere: str | None = None
    warum: str = ""
    regel_id: str | None = None
    konfidenz: float | None = None
    judge: dict[str, int] = Field(default_factory=dict)
    gesperrt: bool = False
    sperrgrund: str | None = None


class LektoratErgebnis(BaseModel):
    """Ausgabe eines Lektorats-Workflows."""

    model_config = ConfigDict(extra="forbid")

    werk: str
    abschnitt_uuid: str
    abschnitt_titel: str
    ebene: Literal["korrektorat", "stil"]
    befunde: list[BefundMitUrteil] = Field(default_factory=list)
    gesperrt: list[BefundMitUrteil] = Field(
        default_factory=list, description="Vom Treue-Judge verworfen, vor der Anzeige"
    )
    hinweise: list[str] = Field(default_factory=list)

    @property
    def nach_art(self) -> dict[str, int]:
        """Befunde gruppiert — die Grundlage für 'alle übernehmen' je Art."""
        z: dict[str, int] = {}
        for b in self.befunde:
            z[b.art] = z.get(b.art, 0) + 1
        return z


class UebersehenerFehler(BaseModel):
    """Ein Fehler, den die erste Stufe nicht gemeldet hat."""

    model_config = ConfigDict(extra="forbid")

    absatz_index: int
    search: str
    replace: str
    art: str
    warum: str


class UnberechtigterBefund(BaseModel):
    """Ein gemeldeter Befund, der keiner ist."""

    model_config = ConfigDict(extra="forbid")

    nummer: int = Field(description="Position in der vorgelegten Liste, ab 1")
    warum: str


class Gegenlesung(BaseModel):
    """Ausgabe von ``buch-gegenlesen`` — das zweite Augenpaar.

    Anders als der frühere Judge sieht dieser Agent **denselben Text** wie die
    erste Stufe, nicht nur deren Vorschläge. Nur so kann er die Frage
    beantworten, auf die es beim Vier-Augen-Prinzip ankommt: Hat der Erste das
    richtig erfasst? Ein Prüfer, der nur Vorschläge sieht, kann gar nicht
    bemerken, dass einer fehlt — und läuft bei null Vorschlägen nie an.
    """

    model_config = ConfigDict(extra="forbid")

    uebersehen: list[UebersehenerFehler] = Field(default_factory=list)
    unberechtigt: list[UnberechtigterBefund] = Field(default_factory=list)
    urteil: str
