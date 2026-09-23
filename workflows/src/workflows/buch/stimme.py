"""Stimmprofil prüfen, bauen und ausgeben.

Der Reduce-Agent liefert Regeln samt Belegen. Bevor eine davon jemals einen
Stilvorschlag rechtfertigen darf, läuft sie hier durch zwei Sperren — **in
Python, nicht im Prompt**:

1. **Belegzahl.** Mindestens zwei wörtliche Belege je Regel.
2. **Belegechtheit.** Jeder Beleg muss tatsächlich im Manuskript vorkommen.

Punkt 2 ist der wichtigere. Ein Modell, das eine hübsche Regel formulieren will,
erfindet dafür notfalls ein passendes Zitat — und eine Regel, die auf einem
erfundenen Beleg steht, ist schlimmer als gar keine, weil sie überzeugend
aussieht. Verworfene Regeln verschwinden nicht still, sie landen mit Begründung
im Profil unter ``verworfene_regeln``.

Rein: keine I/O, kein Modell. Damit im Workflow-Thread ausführbar und testbar.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from .models import Korpus, Stimmprofil, Stimmregel, StimmProfilRoh


def _norm(text: str) -> str:
    """Vergleichsform für Belege: NFC, einheitlicher Whitespace, einheitliche Zeichen.

    Typografische Varianten (Anführungszeichen, Apostrophe, Striche) werden
    vereinheitlicht — ein Beleg soll nicht daran scheitern, dass der Agent ein
    gerades statt eines typografischen Anführungszeichens geschrieben hat.
    """
    t = unicodedata.normalize("NFC", text)
    for zeichen, ersatz in (
        ("„", '"'), ("“", '"'), ("”", '"'), ("»", '"'), ("«", '"'),
        ("’", "'"), ("‘", "'"), ("‚", "'"),
        ("—", "-"), ("–", "-"), ("…", "..."),
        (" ", " "),
    ):
        t = t.replace(zeichen, ersatz)
    return re.sub(r"\s+", " ", t).strip().lower()


def normalisiere_id(roh: str) -> str:
    """Macht aus einer vom Modell vergebenen Regel-ID einen stabilen ASCII-Bezeichner.

    Das Modell vergibt IDs frei und produziert dabei Umlaute (``R-bürosprache``)
    und gelegentlich Tippfehler (``R-prospektsrache``). Der Stil-Agent muss diese
    IDs später wörtlich zitieren und der Workflow sie vergleichen — beides wird
    fehleranfällig, sobald Sonderzeichen im Spiel sind.
    """
    s = roh.strip().lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-")
    if not s.startswith("r-"):
        s = f"r-{s}"
    return "R-" + s[2:]


def beleg_gefunden(beleg: str, korpus_norm: str, *, mindestlaenge: int = 20) -> bool:
    """Ob ein Beleg wörtlich im Manuskript steht.

    Sehr kurze „Belege" werden abgelehnt: ein Zitat aus drei Wörtern findet sich
    in 27.000 Wörtern fast immer und belegt deshalb nichts.
    """
    b = _norm(beleg)
    if len(b) < mindestlaenge:
        return False
    return b in korpus_norm


def pruefe_regeln(
    roh: StimmProfilRoh,
    korpus_text: str,
    *,
    min_belege: int,
    max_regeln: int,
) -> tuple[list[Stimmregel], list[dict]]:
    """Filtert die vorgeschlagenen Regeln auf die belegten.

    Gibt ``(angenommene, verworfene)`` zurück; jede verworfene Regel trägt einen
    Grund, damit man sieht, woran das Profil gescheitert ist.
    """
    korpus_norm = _norm(korpus_text)
    angenommen: list[Stimmregel] = []
    verworfen: list[dict] = []

    for r in roh.regeln:
        echte_belege = [b for b in r.beweis if beleg_gefunden(b, korpus_norm)]
        erfunden = [b for b in r.beweis if b not in echte_belege]

        if len(echte_belege) < min_belege:
            verworfen.append(
                {
                    "id": r.id,
                    "titel": r.titel,
                    "grund": (
                        f"nur {len(echte_belege)} von {len(r.beweis)} Belegen im Manuskript "
                        f"gefunden, gefordert sind {min_belege}"
                    ),
                    "nicht_gefunden": erfunden[:3],
                }
            )
            continue

        if len(angenommen) >= max_regeln:
            verworfen.append(
                {"id": r.id, "titel": r.titel, "grund": f"über der Grenze von {max_regeln} Regeln"}
            )
            continue

        angenommen.append(
            Stimmregel(
                **{**r.model_dump(), "id": normalisiere_id(r.id), "beweis": echte_belege}
            )
        )

    return angenommen, verworfen


def baue_profil(
    roh: StimmProfilRoh,
    *,
    werk: str,
    korpus_text: str,
    korpus: Korpus,
    metrik: dict,
    erstellt_am: date,
    min_belege: int,
    max_regeln: int,
    version: int = 1,
) -> Stimmprofil:
    """Setzt das geprüfte Profil zusammen."""
    regeln, verworfen = pruefe_regeln(
        roh, korpus_text, min_belege=min_belege, max_regeln=max_regeln
    )
    return Stimmprofil(
        version=version,
        werk=werk,
        erstellt_am=erstellt_am,
        korpus=korpus,
        metrik=metrik,
        erzaehlhaltung=roh.erzaehlhaltung,
        tempus=roh.tempus,
        person=roh.person,
        regeln=regeln,
        wiederkehrende_motive=roh.wiederkehrende_motive,
        vermeidungen=roh.vermeidungen,
        offene_fragen=roh.offene_fragen,
        verworfene_regeln=verworfen,
    )


# ---------------------------------------------------------------------------
# Ausgabeformen
# ---------------------------------------------------------------------------


def notizregeln_text(notizen) -> str:  # noqa: ANN001 — list[Lektoratsnotiz], zirkelfrei
    """Die selbst formulierten Regeln des Autors, aufbereitet für den Reduce-Agent."""
    zeilen: list[str] = []
    for n in notizen:
        if n.art == "aenderung":
            zeilen += [
                f"REGEL: {n.regel}",
                f"  vorher : {n.vorher}",
                f"  nachher: {n.nachher}",
            ]
            if n.warum:
                zeilen.append(f"  warum  : {n.warum}")
            zeilen.append("")
        elif n.regel.upper().startswith(("NICHT ANFASSEN", "WAS BLEIBT")):
            # Was der Autor als gelungen markiert hat, ist für ein Stimmprofil
            # mindestens so wertvoll wie das, was er geändert hat.
            zeilen += [f"GELUNGEN LAUT AUTOR ({n.abschnitt_titel}): {n.text}", ""]
    return "\n".join(zeilen).strip()


def render_fuer_agent(profil: Stimmprofil) -> str:
    """Kompakte Fassung, die dem Stil-Agent zur Laufzeit mitgegeben wird.

    Bewusst **nicht** in die Agent-Instructions eingebacken: Sonst müsste bei
    jeder Profiländerung der Agent neu synchronisiert werden, und Profil und
    Agent driften auseinander.
    """
    zeilen = [
        f"Erzählhaltung: {profil.erzaehlhaltung}",
        f"Tempus: {profil.tempus} · Person: {profil.person}",
        "",
        "REGELN (jeder Vorschlag muss sich auf eine davon berufen):",
    ]
    for r in profil.aktive_regeln:
        zeilen += [
            f"\n[{r.id}] {r.titel}",
            f"  {r.regel}",
            f"  Erkennbar an: {r.pruefbar_als}",
            f"  Beleg: „{r.beweis[0]}“",
            f"  Verstoß klänge wie: „{r.gegenbeispiel}“",
        ]
    if profil.vermeidungen:
        zeilen += ["", "DAS TUT DER AUTOR NIE:"]
        zeilen += [f"  - {v}" for v in profil.vermeidungen]
    return "\n".join(zeilen)


def render_markdown(profil: Stimmprofil) -> str:
    """Lesbare Fassung für den Skill und die Library."""
    zeilen = [
        f"# Stimmprofil — {profil.werk}",
        "",
        f"Version {profil.version}, erstellt am {profil.erstellt_am.isoformat()} aus "
        f"{profil.korpus.abschnitte} Abschnitten / {profil.korpus.woerter} Wörtern.",
        "",
        f"**Erzählhaltung:** {profil.erzaehlhaltung}",
        f"**Tempus:** {profil.tempus} · **Person:** {profil.person}",
        "",
        "## Regeln",
        "",
    ]
    for i, r in enumerate(profil.aktive_regeln, start=1):
        zeilen += [
            f"### {i}. {r.titel}",
            "",
            f"`{r.id}` · Quelle: {r.quelle}",
            "",
            f"**Regel:** {r.regel}",
            "",
            f"**Warum:** {r.warum}",
            "",
            f"**Erkennbar an:** {r.pruefbar_als}",
            "",
            "**Belege aus dem Manuskript:**",
            "",
        ]
        zeilen += [f"> {b}" for b in r.beweis]
        zeilen += ["", f"**Ein Verstoß klänge so:** {r.gegenbeispiel}", ""]

    if profil.vermeidungen:
        zeilen += ["## Was der Autor nie tut", ""]
        zeilen += [f"- {v}" for v in profil.vermeidungen]
        zeilen.append("")
    if profil.wiederkehrende_motive:
        zeilen += ["## Wiederkehrende Motive", ""]
        zeilen += [f"- {m}" for m in profil.wiederkehrende_motive]
        zeilen.append("")
    if profil.offene_fragen:
        zeilen += ["## Offene Fragen", ""]
        zeilen += [f"- {f}" for f in profil.offene_fragen]
        zeilen.append("")
    if profil.verworfene_regeln:
        zeilen += [
            "## Verworfen (Belegprüfung nicht bestanden)",
            "",
            "Diese Regeln hat das Modell vorgeschlagen, aber ihre Belege standen so nicht "
            "im Manuskript:",
            "",
        ]
        zeilen += [f"- **{v['titel']}** — {v['grund']}" for v in profil.verworfene_regeln]
        zeilen.append("")

    return "\n".join(zeilen)
