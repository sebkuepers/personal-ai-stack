"""Scrivener lesen und schreiben — der einzige Ort, der das ``.scriv`` kennt.

**Rein lokal.** Der produktive Worker läuft im Cloudflare-Container und hat
keinen Zugriff auf das Dateisystem des Autors; dieses Modul wird deshalb nur von
``buchcli`` benutzt, nie aus einem Workflow heraus.

Zwei Dinge, die man über das Format wissen muss, bevor man hier etwas ändert —
beide am echten Projekt nachgemessen, nicht aus der Dokumentation:

1. **Der Binder ist die Wahrheit, nicht ``Files/Data/``.** Im Paket liegen 73
   Text-Items, aber nur 54 gehören zum Entwurf; der Rest steht in *Forschung* und
   im *Papierkorb*. Wer über ``Files/Data/*`` läuft, exportiert gelöschte
   Fassungen mit. Deshalb: vom ``DraftFolder`` abwärts durch die Binder-Struktur.

2. **Die Gliederungstiefe ist uneinheitlich.** Kapitel 1 hat eine Gruppenebene,
   die übrigen Kapitel nicht. Ein festes Kapitel/Gruppe/Abschnitt-Tripel bricht
   daran. Das kanonische Modell ist deshalb eine *flache* Abschnittsliste, in der
   jeder Abschnitt seinen ``pfad`` mitführt.

Das RTF ist erfreulich schlicht: im gesamten Entwurf kommt keine einzige
Zeichenauszeichnung vor (die wenigen ``\\i``/``\\qc`` stecken ausschließlich im
manuell gebauten Dokument „Titel"). Der Dekodierer muss deshalb nur Escapes,
Absatzgrenzen und Gruppen beherrschen — aber das exakt.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------


@dataclass
class Abschnitt:
    """Ein Text-Item des Entwurfs, mit seinem Weg durch die Gliederung."""

    uuid: str
    titel: str
    pfad: list[str]
    absaetze: list[str] = field(default_factory=list)
    synopsis: str | None = None
    notizen: str | None = None
    hat_text: bool = False
    kapitel_ebene: int = 0
    etikett: str = ""
    status: str = ""
    ist_ordner: bool = False
    """Ein Gliederungsknoten mit Kindern.

    Wichtig für alles, was „hier fehlt noch Text" meldet: Ein Kapitelordner hat
    nie eigenen Text und ist deshalb kein Mangel, sondern Struktur.
    """

    @property
    def kapitel(self) -> str | None:
        """Die Gliederungsebene, die in diesem Werk ein Kapitel bezeichnet.

        Nicht jedes Projekt legt die Kapitel direkt unter den Entwurf: „Immer
        wieder Rügen" tut das (Ebene 0), das Autobiographie-Projekt schiebt einen
        Sammelordner „Kapitel" dazwischen (Ebene 1). Deshalb konfigurierbar statt
        geraten.
        """
        return self.pfad[self.kapitel_ebene] if len(self.pfad) > self.kapitel_ebene else None

    @property
    def text(self) -> str:
        return "\n\n".join(self.absaetze)

    @property
    def woerter(self) -> int:
        return len(self.text.split())

    def absatz_hash(self, index: int) -> str:
        """Anker für den Write-back — siehe :func:`pruefe_anker`."""
        return hashlib.sha256(self.absaetze[index].encode("utf-8")).hexdigest()[:16]


@dataclass
class Manuskript:
    """Der komplette Entwurf eines Werks zu einem Zeitpunkt."""

    slug: str
    scrivx: Path
    abschnitte: list[Abschnitt]

    @property
    def kapitel(self) -> list[str]:
        """Kapiteltitel in Binder-Reihenfolge, ohne Dubletten."""
        gesehen: list[str] = []
        for a in self.abschnitte:
            if a.kapitel and a.kapitel not in gesehen:
                gesehen.append(a.kapitel)
        return gesehen

    @property
    def woerter(self) -> int:
        return sum(a.woerter for a in self.abschnitte)

    def nach_uuid(self, uuid: str) -> Abschnitt | None:
        return next((a for a in self.abschnitte if a.uuid == uuid), None)

    def in_kapitel(self, kapitel: str) -> list[Abschnitt]:
        return [a for a in self.abschnitte if a.kapitel == kapitel]

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "kapitel": self.kapitel,
            "woerter": self.woerter,
            "abschnitte": [
                {
                    "uuid": a.uuid,
                    "titel": a.titel,
                    "pfad": a.pfad,
                    "woerter": a.woerter,
                    "synopsis": a.synopsis,
                    "notizen": a.notizen,
                    "absaetze": [
                        {"index": i, "text": t, "sha256": a.absatz_hash(i)}
                        for i, t in enumerate(a.absaetze)
                    ],
                }
                for a in self.abschnitte
                if a.hat_text
            ],
        }


# ---------------------------------------------------------------------------
# RTF dekodieren
# ---------------------------------------------------------------------------

# Steuerwort, optional mit numerischem Parameter; danach wird genau ein
# folgendes Leerzeichen als Trenner geschluckt (RTF-Regel).
_STEUERWORT = re.compile(r"\\([a-zA-Z]+)(-?\d+)?[ ]?")
# \'xx — ein Byte in der Codepage des Dokuments (hier cp1252).
_HEX_ESCAPE = re.compile(r"\\'([0-9a-fA-F]{2})")

# Steuerworte, deren Gruppeninhalt komplett verworfen wird (Tabellen, Metadaten).
_VERWERFEN = {"fonttbl", "colortbl", "expandedcolortbl", "stylesheet", "info", "*"}
# Steuerworte, die einen Absatzumbruch bedeuten.
_ABSATZ = {"par", "line"}


def dekodiere_rtf(rohdaten: bytes) -> list[str]:
    """Wandelt ``content.rtf`` in eine Liste von Absätzen.

    Behandelt genau die Konstrukte, die in diesem Projekt vorkommen:
    ``\\'xx`` (cp1252), ``\\uNNNN`` samt dem zu überspringenden Ersatzzeichen,
    ``\\par``/``\\line`` sowie ``\\`` am Zeilenende als Absatzumbruch, und
    geschweifte Gruppen inklusive der zu verwerfenden Tabellen.

    Bewusst konservativ: unbekannte Steuerworte werden ignoriert, nicht geraten.
    """
    s = rohdaten.decode("cp1252", errors="replace")
    absaetze: list[str] = []
    puffer: list[str] = []
    tiefe = 0
    # Tiefe, ab der verworfen wird (None = wir behalten alles).
    verwerfen_ab: int | None = None
    i = 0
    n = len(s)

    while i < n:
        c = s[i]

        if c == "{":
            tiefe += 1
            i += 1
            continue

        if c == "}":
            if verwerfen_ab is not None and tiefe <= verwerfen_ab:
                verwerfen_ab = None
            tiefe -= 1
            i += 1
            continue

        if c == "\\":
            # Escapte Sonderzeichen: \\ \{ \}
            if i + 1 < n and s[i + 1] in "\\{}":
                if verwerfen_ab is None:
                    puffer.append(s[i + 1])
                i += 2
                continue

            # \* markiert eine ignorierbare Destination ({\*\expandedcolortbl;;}).
            # Der Stern ist kein Steuerwort und rutschte sonst als Text durch.
            if i + 1 < n and s[i + 1] == "*":
                if verwerfen_ab is None:
                    verwerfen_ab = tiefe
                i += 2
                continue

            # \ unmittelbar vor einem Zeilenumbruch = Absatzumbruch.
            if i + 1 < n and s[i + 1] in "\r\n":
                if verwerfen_ab is None:
                    absaetze.append("".join(puffer))
                    puffer = []
                i += 2
                if i < n and s[i - 1] == "\r" and s[i] == "\n":
                    i += 1
                continue

            m = _HEX_ESCAPE.match(s, i)
            if m:
                if verwerfen_ab is None:
                    puffer.append(bytes([int(m.group(1), 16)]).decode("cp1252", "replace"))
                i = m.end()
                continue

            m = _STEUERWORT.match(s, i)
            if not m:
                i += 1
                continue

            wort, param = m.group(1), m.group(2)
            i = m.end()

            if wort == "u":
                # \uNNNN + genau ein Ersatzzeichen, das zu überspringen ist
                # (Scrivener schreibt implizit \uc1, z. B. "\u8222?").
                if verwerfen_ab is None and param is not None:
                    code = int(param)
                    if code < 0:  # RTF schreibt >32767 als negative Zahl
                        code += 65536
                    puffer.append(chr(code))
                if i < n and s[i] not in "\\{}":
                    i += 1
                continue

            if wort in _VERWERFEN and verwerfen_ab is None:
                verwerfen_ab = tiefe
                continue

            if wort in _ABSATZ and verwerfen_ab is None:
                absaetze.append("".join(puffer))
                puffer = []
                continue

            # Alle übrigen Steuerworte (Schrift, Einzug, Farbe …) tragen keinen
            # Text und werden übergangen.
            continue

        # Rohe Zeilenumbrüche sind in RTF reine Formatierung, kein Textinhalt.
        if c in "\r\n":
            i += 1
            continue

        if verwerfen_ab is None:
            puffer.append(c)
        i += 1

    absaetze.append("".join(puffer))

    # Aufräumen: Ränder trimmen und Leerabsätze entfernen.
    return [a.strip() for a in absaetze if a.strip()]


def kodiere_rtf_text(text: str) -> str:
    """Kodiert Fließtext zurück in RTF-Escapes.

    Gegenstück zu :func:`dekodiere_rtf` für einen einzelnen Absatz. Alles, was
    nicht ASCII ist, wird als ``\\'xx`` (sofern in cp1252 darstellbar) oder als
    ``\\uNNNN?`` geschrieben — mit dem Ersatzzeichen, das der Dekodierer wieder
    überspringt.
    """
    out: list[str] = []
    for ch in text:
        if ch in "\\{}":
            out.append("\\" + ch)
        elif ord(ch) < 128:
            out.append(ch)
        else:
            try:
                out.append(f"\\'{ch.encode('cp1252')[0]:02x}")
            except (UnicodeEncodeError, IndexError):
                out.append(f"\\u{ord(ch)}?")
    return "".join(out)


# ---------------------------------------------------------------------------
# Binder lesen
# ---------------------------------------------------------------------------


def _text_datei(paket: Path, uuid: str, name: str) -> Path:
    return paket / "Files" / "Data" / uuid / name


def _lies_synopsis(paket: Path, uuid: str) -> str | None:
    p = _text_datei(paket, uuid, "synopsis.txt")
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else None


def _lies_notizen(paket: Path, uuid: str) -> str | None:
    p = _text_datei(paket, uuid, "notes.rtf")
    if not p.is_file():
        return None
    return "\n\n".join(dekodiere_rtf(p.read_bytes())).strip() or None


def _lies_vollstaendig(datei: Path, versuche: int = 4) -> bytes:
    """Liest eine RTF-Datei und wartet kurz, falls Scrivener gerade schreibt.

    Scrivener speichert nach einer Tipppause; wer in genau dem Moment liest,
    bekommt eine halbe Datei — und die dekodiert entweder zu Müll oder zu einem
    Absatz, der mitten im Satz endet, ohne Fehler. Eine RTF-Datei endet immer
    mit ``}``. Fehlt es, ist die Datei nicht fertig: kurz warten, neu lesen.
    Nach dem letzten Versuch wird geworfen statt geraten.
    """
    import time

    for versuch in range(versuche):
        roh = datei.read_bytes()
        if roh.rstrip().endswith(b"}"):
            return roh
        if versuch < versuche - 1:
            time.sleep(0.25 * (versuch + 1))
    raise OSError(
        f"{datei.name}: Datei endet nicht mit '}}' — Scrivener schreibt vermutlich gerade. "
        "Kurz warten und erneut versuchen."
    )


def _vokabular(baum: ET.Element, block: str, eintrag: str) -> dict[str, str]:
    """Die Etikett- bzw. Statusliste eines Projekts als ``{ID: Name}``.

    Scrivener führt beide als frei benennbare Listen in ``<LabelSettings>`` und
    ``<StatusSettings>``; die Items verweisen nur über IDs darauf. Sie stehen
    deshalb hier und nicht in der Config: Der Autor pflegt sie in Scrivener, und
    eine Kopie im Repo wäre sofort veraltet.
    """
    el = baum.find(".//" + block)
    if el is None:
        return {}
    return {
        e.get("ID", ""): (e.text or "").strip()
        for e in el.iter(eintrag)
        if e.get("ID") is not None
    }


def lies_binder(
    paket: Path,
    slug: str,
    *,
    nur_mit_text: bool = False,
    wurzel: str | None = None,
    kapitel_ebene: int = 0,
) -> Manuskript:
    """Liest den Entwurf eines Scrivener-Projekts.

    Läuft vom ``DraftFolder`` abwärts und beachtet ``IncludeInCompile``; Ordner
    tragen zum ``pfad`` bei, Text-Items werden zu :class:`Abschnitt`. Items ohne
    ``content.rtf`` (reine Gliederungsknoten) bleiben mit ``hat_text=False``
    erhalten, damit die Struktur vollständig sichtbar ist.

    ``wurzel`` schränkt auf einen benannten Ordner unterhalb des Entwurfs ein.
    Das braucht man, wenn im Entwurf neben dem Manuskript auch Recherche liegt —
    das Autobiographie-Projekt führt dort ``Personen``, ``Orte``, ``Unternehmen``
    und ``Schlüsselmomente``, die kein Manuskripttext sind, aber alle
    ``IncludeInCompile=Yes`` tragen und sonst als Kapitel gezählt würden.

    ``kapitel_ebene`` sagt, welche Pfadebene ein Kapitel bezeichnet (siehe
    :attr:`Abschnitt.kapitel`).
    """
    scrivx = next(paket.glob("*.scrivx"), None)
    if scrivx is None:
        raise FileNotFoundError(f"Keine .scrivx-Datei in {paket}")

    baum = ET.parse(scrivx).getroot()
    etiketten = _vokabular(baum, "LabelSettings", "Label")
    zustaende = _vokabular(baum, "StatusSettings", "Status")
    entwurf = next(
        (b for b in baum.iter("BinderItem") if b.get("Type") == "DraftFolder"), None
    )
    if entwurf is None:
        raise ValueError(f"Kein DraftFolder im Binder von {scrivx}")

    abschnitte: list[Abschnitt] = []

    def begehe(knoten: ET.Element, pfad: list[str]) -> None:
        kinder = knoten.find("Children")
        if kinder is None:
            return
        for item in kinder:
            if item.tag != "BinderItem":
                continue
            meta = item.find("MetaData")
            if meta is not None:
                flag = meta.find("IncludeInCompile")
                if flag is not None and (flag.text or "").strip().lower() == "no":
                    continue

            titel_el = item.find("Title")
            titel = (titel_el.text or "").strip() if titel_el is not None else ""
            uuid = item.get("UUID") or ""
            rtf = _text_datei(paket, uuid, "content.rtf")
            # Fehlt die ID, hat der Autor nichts gesetzt — Scrivener zeigt dann
            # den ersten Eintrag der Liste, also die Vorgabe.
            etikett = etiketten.get((meta.findtext("LabelID") or "-1") if meta is not None else "-1", "")
            status = zustaende.get((meta.findtext("StatusID") or "-1") if meta is not None else "-1", "")
            kinder_el = item.find("Children")
            ist_ordner = kinder_el is not None and len(kinder_el) > 0

            if rtf.is_file():
                abschnitte.append(
                    Abschnitt(
                        uuid=uuid,
                        titel=titel,
                        pfad=list(pfad),
                        absaetze=dekodiere_rtf(_lies_vollstaendig(rtf)),
                        synopsis=_lies_synopsis(paket, uuid),
                        notizen=_lies_notizen(paket, uuid),
                        hat_text=True,
                        kapitel_ebene=kapitel_ebene,
                        etikett=etikett,
                        status=status,
                        ist_ordner=ist_ordner,
                    )
                )
            elif not nur_mit_text:
                abschnitte.append(
                    Abschnitt(
                        uuid=uuid,
                        titel=titel,
                        pfad=list(pfad),
                        synopsis=_lies_synopsis(paket, uuid),
                        notizen=_lies_notizen(paket, uuid),
                        hat_text=False,
                        kapitel_ebene=kapitel_ebene,
                        etikett=etikett,
                        status=status,
                        ist_ordner=ist_ordner,
                    )
                )

            # Ordner und Gruppenknoten erweitern den Pfad für ihre Kinder.
            begehe(item, [*pfad, titel] if titel else list(pfad))

    start = entwurf
    if wurzel:
        gefunden = next(
            (
                b
                for b in entwurf.iter("BinderItem")
                if (b.find("Title") is not None and (b.find("Title").text or "").strip() == wurzel)
            ),
            None,
        )
        if gefunden is None:
            raise ValueError(f"Ordner {wurzel!r} nicht im Entwurf von {scrivx.name} gefunden")
        start = gefunden

    begehe(start, [])
    return Manuskript(slug=slug, scrivx=scrivx, abschnitte=abschnitte)


# ---------------------------------------------------------------------------
# Anker für den Write-back
# ---------------------------------------------------------------------------


def pruefe_anker(
    abschnitt: Abschnitt, absatz_index: int, erwarteter_hash: str, suchtext: str
) -> None:
    """Stellt sicher, dass eine Änderung noch auf den Text passt, den sie meint.

    Vier Bedingungen, alle hart: der Absatz existiert, sein Hash stimmt noch, der
    Suchtext kommt vor, und zwar **genau einmal**. Schlägt eine fehl, wird
    abgebrochen statt geraten — Fuzzy-Matching gibt es hier bewusst nicht.

    :raises ValueError: mit einer Meldung, die den Abschnitt benennt.
    """
    wo = f"{abschnitt.titel!r} ({abschnitt.uuid[:8]}), Absatz {absatz_index}"

    if not 0 <= absatz_index < len(abschnitt.absaetze):
        raise ValueError(f"{wo}: Absatz existiert nicht (nur {len(abschnitt.absaetze)}).")

    ist = abschnitt.absatz_hash(absatz_index)
    if ist != erwarteter_hash:
        raise ValueError(
            f"{wo}: Der Absatz wurde seit der Analyse geändert "
            f"(erwartet {erwarteter_hash}, ist {ist}). Abschnitt neu analysieren."
        )

    treffer = abschnitt.absaetze[absatz_index].count(suchtext)
    if treffer == 0:
        raise ValueError(f"{wo}: Suchtext kommt im Absatz nicht vor.")
    if treffer > 1:
        raise ValueError(f"{wo}: Suchtext kommt {treffer}-mal vor — nicht eindeutig.")


def normalisiere(text: str) -> str:
    """Unicode-Normalform für Vergleiche zwischen Dekodierern."""
    return unicodedata.normalize("NFC", text)
