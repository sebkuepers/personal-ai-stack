"""Der Scrivener-Roundtrip ist die riskanteste Stelle der Buch-Domäne.

Hier wird an das Manuskript des Autors geschrieben; ein Dekodierfehler ist
stiller Textverlust. Deshalb prüfen diese Tests gegen das **echte** Projekt und
gegen einen unabhängigen Dritten (Apples ``textutil``) statt gegen Fixtures, die
dieselben Annahmen enthalten wie der Code.

Die Tests überspringen sich selbst, wenn das Projekt nicht vorhanden ist — sie
sollen auf einer fremden Maschine nicht rot sein.
"""

from __future__ import annotations

import re
import subprocess
import unicodedata

import pytest

from workflows.buch import config as c
from workflows.buch.scrivener import (
    Abschnitt,
    dekodiere_rtf,
    kodiere_rtf_text,
    lies_binder,
    pruefe_anker,
)

SLUG = "immer-wieder-ruegen"

# Minimaler Dokumentkopf in der Form, die Scrivener schreibt.
KOPF = (
    rb"{\rtf1\ansi\ansicpg1252\cocoartf2870"
    rb"{\fonttbl\f0\froman\fcharset0 Palatino-Roman;}"
    rb"{\colortbl;\red255\green255\blue255;}{\*\expandedcolortbl;;}"
    rb"\pard\f0\fs26 \cf0 "
)


def _paket(slug: str = SLUG):
    # Die Werk-Konfiguration ist gitignored — auf einem frischen Klon (CI) fehlt
    # sie, und scrivener_pfad() wirft, bevor ein Pfad geprüft werden könnte.
    # Beide Fälle sind „nicht vorhanden“ und überspringen den Test.
    try:
        pfad = c.scrivener_pfad(slug)
    except FileNotFoundError as e:
        pytest.skip(f"Werk-Konfiguration nicht vorhanden: {e}")
    if not pfad.is_dir():
        pytest.skip(f"Scrivener-Projekt nicht vorhanden: {pfad}")
    return pfad


def _norm(t: str) -> str:
    """Vergleichsform: Unicode-NFC, geschütztes Leerzeichen und Whitespace vereinheitlicht."""
    t = unicodedata.normalize("NFC", t).replace(" ", " ")
    return re.sub(r"\s+", " ", t).strip()


@pytest.fixture(scope="module")
def manuskript():
    return lies_binder(_paket(), SLUG)


# ---------------------------------------------------------------------------
# Struktur
# ---------------------------------------------------------------------------


def test_binder_findet_alle_kapitel(manuskript):
    """Der alte Handexport kannte nur drei Kapitel — der Binder-Lauf muss vier finden.

    Genau dieser Fehler ist der Grund, warum der Export bei jedem Lauf neu gebaut
    und nie von Hand gepflegt wird.
    """
    assert manuskript.kapitel == [
        "Voll zur Oma",
        "Und jetzt?",
        "Ich sehe nix!",
        "Wir bleiben hier",
    ]


def test_nur_entwurf_keine_forschung_kein_papierkorb(manuskript):
    """Im Paket liegen deutlich mehr Text-Items als zum Entwurf gehören."""
    mit_text = [a for a in manuskript.abschnitte if a.hat_text]
    assert len(mit_text) == 48
    assert all(a.kapitel in manuskript.kapitel for a in mit_text)


def test_pfad_traegt_uneinheitliche_gliederung(manuskript):
    """Kapitel 1 hat eine Gruppenebene, die übrigen nicht — beides muss abbildbar sein."""
    tiefen = {len(a.pfad) for a in manuskript.abschnitte if a.hat_text}
    assert tiefen == {1, 2}, f"unerwartete Gliederungstiefen: {tiefen}"

    tief = next(a for a in manuskript.abschnitte if a.titel == "Einführung Strand")
    assert tief.pfad == ["Voll zur Oma", "Strand Thiessow"]
    assert tief.kapitel == "Voll zur Oma"


def test_synopsis_und_notizen_werden_mitgelesen(manuskript):
    """Beides ist Rohstoff für Stimmprofil und Inhaltsebene und darf nicht verloren gehen."""
    assert sum(1 for a in manuskript.abschnitte if a.synopsis) >= 39
    assert sum(1 for a in manuskript.abschnitte if a.notizen) >= 36


# ---------------------------------------------------------------------------
# Dekodierung — gegen einen unabhängigen Dritten
# ---------------------------------------------------------------------------


def test_dekodierer_stimmt_mit_textutil_ueberein():
    """Jede content.rtf muss zeichengleich zu Apples Konverter dekodieren."""
    paket = _paket()
    abweichungen = []
    for f in sorted((paket / "Files" / "Data").glob("*/content.rtf")):
        meins = _norm("\n".join(dekodiere_rtf(f.read_bytes())))
        ref = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", str(f)],
            capture_output=True,
            check=True,
        ).stdout.decode("utf-8", "replace")
        if meins != _norm(ref):
            abweichungen.append(f.parent.name)
    assert not abweichungen, f"Abweichungen gegenüber textutil in: {abweichungen}"


def test_ignorierbare_destination_wird_verworfen():
    """``{\\*\\expandedcolortbl;;}`` darf keinen Stern in den Text spülen.

    Genau dieser Fehler war im ersten Wurf drin: ``\\*`` ist kein Steuerwort im
    Sinne von ``[a-zA-Z]+`` und rutschte als Literal durch.
    """
    rtf = KOPF + b"Hallo Welt}"
    assert dekodiere_rtf(rtf) == ["Hallo Welt"]
    assert not dekodiere_rtf(rtf)[0].startswith("*")


def test_unicode_escape_ueberspringt_ersatzzeichen():
    """Scrivener schreibt ``\\u8222?`` — das ``?`` ist Ersatzzeichen, kein Text."""
    esc = b"\\"  # bewusst zusammengesetzt, damit hier kein \u-Muster im Quelltext steht
    assert dekodiere_rtf(KOPF + esc + b"u8222?Zitat" + esc + b"u8220?}") == ["„Zitat“"]


def test_hex_escape_ist_cp1252():
    assert dekodiere_rtf(KOPF + rb"F\'fc\'dfe}") == ["Füße"]


def test_absatzumbrueche():
    """Sowohl ``\\par`` als auch ``\\`` am Zeilenende trennen Absätze."""
    assert dekodiere_rtf(KOPF + b"Eins\\\nZwei}") == ["Eins", "Zwei"]
    assert dekodiere_rtf(KOPF + rb"Eins\par Zwei}") == ["Eins", "Zwei"]


# ---------------------------------------------------------------------------
# Kodierung — die Identität, auf der der Write-back beruht
# ---------------------------------------------------------------------------


def test_kodieren_dekodieren_ist_identitaet(manuskript):
    """Jeder Absatz des Manuskripts muss verlustfrei durch den Encoder laufen."""
    fehler = []
    for a in manuskript.abschnitte:
        for i, absatz in enumerate(a.absaetze):
            rtf = KOPF + kodiere_rtf_text(absatz).encode("cp1252", "replace") + b"}"
            zurueck = dekodiere_rtf(rtf)
            if not zurueck or zurueck[0] != absatz:
                fehler.append(f"{a.titel!r} Absatz {i}")
    assert not fehler, f"Roundtrip verletzt bei: {fehler[:5]}"


def test_zeichen_ausserhalb_cp1252_ueberleben():
    """``č`` kommt im Manuskript vor und muss über den ``\\uNNNN``-Pfad laufen."""
    text = "Ein čech und ein Dash — und „Anführung“."
    rtf = KOPF + kodiere_rtf_text(text).encode("cp1252", "replace") + b"}"
    assert dekodiere_rtf(rtf) == [text]


def test_geschweifte_klammern_werden_escaped():
    text = "Ein {Wert} und ein \\ Backslash"
    rtf = KOPF + kodiere_rtf_text(text).encode("cp1252", "replace") + b"}"
    assert dekodiere_rtf(rtf) == [text]


# ---------------------------------------------------------------------------
# Anker — die Sperre gegen Schreiben auf veraltetem Stand
# ---------------------------------------------------------------------------


def _demo() -> Abschnitt:
    return Abschnitt(
        uuid="U" * 32,
        titel="Probe",
        pfad=["Kapitel"],
        absaetze=["Der Hund bellt. Die Katze schläft.", "Zweiter Absatz."],
        hat_text=True,
    )


def test_anker_akzeptiert_unveraenderten_absatz():
    a = _demo()
    pruefe_anker(a, 0, a.absatz_hash(0), "Der Hund bellt.")


def test_anker_lehnt_veraenderten_absatz_ab():
    a = _demo()
    with pytest.raises(ValueError, match="geändert"):
        pruefe_anker(a, 0, "0" * 16, "Der Hund bellt.")


def test_anker_lehnt_mehrdeutigen_suchtext_ab():
    a = _demo()
    a.absaetze[0] = "Das Boot. Das Boot."
    with pytest.raises(ValueError, match="nicht eindeutig"):
        pruefe_anker(a, 0, a.absatz_hash(0), "Das Boot.")


def test_anker_lehnt_fehlenden_suchtext_ab():
    a = _demo()
    with pytest.raises(ValueError, match="kommt im Absatz nicht vor"):
        pruefe_anker(a, 0, a.absatz_hash(0), "Der Vogel singt.")


def test_anker_lehnt_ungueltigen_index_ab():
    a = _demo()
    with pytest.raises(ValueError, match="existiert nicht"):
        pruefe_anker(a, 99, "irgendwas", "egal")


# ---------------------------------------------------------------------------
# Mehrere Werke — die Gliederung ist nicht in jedem Projekt gleich
# ---------------------------------------------------------------------------


def test_wurzel_begrenzt_auf_den_manuskriptzweig():
    """Das Autobiographie-Projekt führt Recherche im Entwurf mit.

    ``Personen``, ``Orte``, ``Unternehmen`` und ``Schlüsselmomente`` stehen dort
    neben dem Manuskript und tragen alle ``IncludeInCompile=Yes`` — ohne
    ``wurzel`` würden sie als Kapitel gezählt. Genau daran ist der erste Lauf
    aufgefallen.
    """
    pfad = _paket("autobiographie")

    ohne = lies_binder(pfad, "autobiographie")
    assert "Personen" in ohne.kapitel, "Vorbedingung: Recherche liegt im Entwurf"

    struktur = c.lade_werk("autobiographie")["struktur"]
    mit = lies_binder(
        pfad,
        "autobiographie",
        wurzel=struktur["wurzel"],
        kapitel_ebene=struktur["kapitel_ebene"],
    )
    assert mit.kapitel == [
        "1. Die unbeschwerten Jahre",
        "2. Der totale Absturz",
        "3. Der Weg nach Oben",
    ]
    assert "Personen" not in mit.kapitel


def test_unbekannte_wurzel_schlaegt_fehl():
    """Lieber ein klarer Fehler als ein stillschweigend leerer Export."""
    pfad = _paket("autobiographie")
    with pytest.raises(ValueError, match="nicht im Entwurf"):
        lies_binder(pfad, "autobiographie", wurzel="Gibtsnicht")


def test_kapitel_ebene_verschiebt_die_zuordnung():
    a = Abschnitt(uuid="x", titel="t", pfad=["Sammel", "Kapitel 1"], hat_text=True)
    assert a.kapitel == "Sammel"
    a.kapitel_ebene = 1
    assert a.kapitel == "Kapitel 1"
    a.kapitel_ebene = 5
    assert a.kapitel is None
