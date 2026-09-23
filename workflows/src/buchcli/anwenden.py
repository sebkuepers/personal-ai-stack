"""Entscheidungen ins Manuskript zurückschreiben — der einzige Teil, der schreibt.

    python -m buchcli.anwenden --werk immer-wieder-ruegen              # Vorschau (Vorgabe)
    python -m buchcli.anwenden --werk immer-wieder-ruegen --apply      # tatsächlich schreiben
    python -m buchcli.anwenden --werk immer-wieder-ruegen --uuid 4BEE  # nur ein Abschnitt
    python -m buchcli.anwenden --werk immer-wieder-ruegen --test       # auf der Testkopie

Eingabe ist das Entscheidungslog: alles, was der Autor in einer Sitzung
angenommen und noch nicht angewendet hat. Was angewendet wurde, steht danach in
``angewendet.jsonl`` daneben — ein zweiter Lauf macht dieselbe Änderung nicht
noch einmal.

**Die Disziplin, und warum sie so ist**

1. **Scrivener muss zu sein.** Ist das Projekt offen, überschreibt Scrivener
   beim nächsten Speichern alles, was wir geschrieben haben — ohne Warnung, ohne
   Konflikt. Geprüft mit ``lsof``.
2. **Kein Sync-Ordner.** Ein Cloud-Dienst, der in ein lebendes ``.scriv`` hinein
   synchronisiert, legt Konfliktkopien **im Paket** an; Scrivener verliert daran
   die Orientierung. Das Projekt liegt deshalb unter ``~/Werk/``.
3. **Backup vor dem ersten Byte.** Eine vollständige Paketkopie nach ``backup/``,
   datiert. Nicht als Beruhigung, sondern weil Punkt 6 sie braucht.
4. **Vorschau ist die Vorgabe.** ``--apply`` schreibt; ohne sie wird nur gezeigt.
5. **Vierfacher Anker.** Abschnitt, Absatzindex, Absatz-Hash, Suchtext — und der
   Suchtext muss **genau einmal** vorkommen. Kein Fuzzy-Matching. Stimmt der Hash
   nicht mehr, hat der Autor den Absatz seit der Sitzung angefasst; dann wird
   abgelehnt und benannt, nicht geraten.
6. **Nach dem Schreiben neu lesen.** Die geschriebene Datei wird erneut dekodiert
   und gegen den erwarteten Text gehalten. Weicht sie ab, wird das Backup
   zurückgespielt und abgebrochen. Ein stiller Fehler im Kodierer würde sonst
   erst Wochen später auffallen — beim Lesen des eigenen Buchs.

Gearbeitet wird byteweise: Nur die Spanne, die den Suchtext trägt, wird ersetzt.
Jedes andere Byte der ``content.rtf`` bleibt, wie Scrivener es geschrieben hat.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from workflows.buch import config as c
from workflows.buch import entscheidungen as log
from workflows.buch.scrivener import dekodiere_rtf, ersetze_im_rtf

DATEN = Path(__file__).resolve().parents[2] / "data"
SYNC_ORDNER = ("Library/CloudStorage", "Dropbox", "Google Drive", "OneDrive", "iCloud")


def scrivener_offen(paket: Path) -> bool:
    """Ob ein Prozess Dateien im Paket geöffnet hält."""
    try:
        r = subprocess.run(["lsof", "+D", str(paket)], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False  # Ohne lsof lieber weitermachen als grundlos blockieren.
    return bool(r.stdout.strip() and len(r.stdout.strip().splitlines()) > 1)


def im_sync_ordner(paket: Path) -> str | None:
    teile = str(paket.resolve())
    for name in SYNC_ORDNER:
        if name in teile:
            return name
    return None


def sichere(paket: Path, werk: str) -> Path:
    """Vollständige Paketkopie nach ``backup/`` — vor dem ersten geschriebenen Byte."""
    ziel_ordner = c.werk_pfad(werk, "backup")
    ziel_ordner.mkdir(parents=True, exist_ok=True)
    ziel = ziel_ordner / f"{paket.stem}-{datetime.now(UTC):%Y%m%d-%H%M%S}.scriv"
    shutil.copytree(paket, ziel)
    return ziel


def _schluessel(z: dict) -> str:
    """Stabile Kennung einer Entscheidung — erkennt Wiederholungen wieder."""
    return f"{z['sitzung']}|{z['abschnitt_uuid']}|{z['absatz_index']}|{z['search']}"


def offene_entscheidungen(werk: str, nur_uuid: str | None) -> list[dict]:
    """Angenommene Entscheidungen, die noch nicht angewendet wurden."""
    schon = set()
    datei = log.log_ordner(DATEN, werk) / "angewendet.jsonl"
    if datei.is_file():
        for zeile in datei.read_text(encoding="utf-8").splitlines():
            if zeile.strip():
                try:
                    schon.add(json.loads(zeile)["schluessel"])
                except (json.JSONDecodeError, KeyError):
                    continue

    offen = []
    for z in log.lies_alle(DATEN, werk):
        if z.get("entscheidung") != "angenommen" or _schluessel(z) in schon:
            continue
        if nur_uuid and not z["abschnitt_uuid"].lower().startswith(nur_uuid.lower()):
            continue
        offen.append(z)
    return offen


def merke_angewendet(werk: str, zeilen: list[dict]) -> None:
    datei = log.log_ordner(DATEN, werk) / "angewendet.jsonl"
    datei.parent.mkdir(parents=True, exist_ok=True)
    jetzt = datetime.now(UTC).isoformat(timespec="seconds")
    with datei.open("a", encoding="utf-8") as fh:
        for z in zeilen:
            fh.write(
                json.dumps(
                    {"ts": jetzt, "schluessel": _schluessel(z), "abschnitt": z["abschnitt"]},
                    ensure_ascii=False,
                )
                + "\n"
            )


def anwenden_auf_datei(
    rtf: Path, eintraege: list[dict], *, schreiben: bool
) -> tuple[list[dict], list[str], list[str]]:
    """Wendet die Entscheidungen eines Abschnitts an.

    Gibt ``(erledigte_eintraege, meldungen, abgelehnt)`` zurück — die Einträge
    selbst, damit der Aufrufer sie als angewendet vermerken kann, ohne aus
    Meldungstexten zurückzurechnen.

    Arbeitet auf einer Kopie der Bytes im Speicher und schreibt erst, wenn das
    Ergebnis am Ende dem entspricht, was wir erwarten.
    """
    roh = rtf.read_bytes()
    absaetze = dekodiere_rtf(roh)
    erwartet = list(absaetze)
    erledigt: list[dict] = []
    meldungen: list[str] = []
    abgelehnt: list[str] = []

    for z in eintraege:
        i = z["absatz_index"]
        kurz = z["search"][:45]
        if not 0 <= i < len(absaetze):
            abgelehnt.append(f"Absatz {i} gibt es nicht ({len(absaetze)} vorhanden) — {kurz!r}")
            continue

        # Anker 2: Hash gegen den Stand bei der Analyse — und zwar gegen den
        # Absatz, wie er beim START dieses Laufs dastand, nicht gegen unsere
        # eigenen Zwischenstände. Der Hash soll FREMDE Änderungen erkennen
        # (der Autor hat in Scrivener weitergeschrieben). Prüfte man gegen
        # `erwartet`, schlüge er bei der zweiten Änderung im selben Absatz an
        # — und mehrere Befunde je Absatz sind der Normalfall. Gemessen: 9 von
        # 15 Entscheidungen fielen genau daran, obwohl der Autor sie zusammen
        # freigegeben hatte.
        ist = hashlib.sha256(absaetze[i].encode("utf-8")).hexdigest()[:16]
        if z.get("absatz_hash") and ist != z["absatz_hash"]:
            abgelehnt.append(
                f"Absatz {i} wurde seit der Sitzung geändert (Hash {ist} statt "
                f"{z['absatz_hash']}) — {kurz!r}"
            )
            continue

        if z.get("eigene_fassung"):
            # Der Autor hat den Absatz selbst neu geschrieben — kein Suchen und
            # Ersetzen, sondern ein Austausch. Die Byte-Ersetzung braucht
            # trotzdem einen Anker: den ganzen alten Absatz.
            alt, neu_text = erwartet[i], z["eigene_fassung"]
        else:
            alt, neu_text = z["search"], z["replace"]

        try:
            roh = ersetze_im_rtf(roh, i, alt, neu_text)
        except ValueError as exc:
            abgelehnt.append(f"{exc} — {kurz!r}")
            continue

        erwartet[i] = erwartet[i].replace(alt, neu_text, 1)
        erledigt.append(z)
        if z.get("eigene_fassung"):
            # Sichtbar machen, dass hier der GANZE Absatz getauscht wird — in
            # der Vorschau sah das sonst aus wie eine Wortersetzung mit
            # merkwürdigem Ergebnis.
            meldungen.append(
                f"Absatz {i}: GANZER ABSATZ ersetzt (eigene Fassung) → {neu_text[:60]!r}"
            )
        else:
            meldungen.append(f"Absatz {i}: {kurz!r} → {neu_text[:45]!r}")

    if not erledigt:
        return erledigt, meldungen, abgelehnt

    # Prüfung 6: neu dekodieren und gegen die Erwartung halten.
    if dekodiere_rtf(roh) != erwartet:
        return [], [], abgelehnt + [
            "ABBRUCH: Die neu geschriebene Datei dekodiert nicht zum erwarteten Text. "
            "Nichts geschrieben."
        ]

    if schreiben:
        rtf.write_bytes(roh)
    return erledigt, meldungen, abgelehnt


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Entscheidungen ins Manuskript zurückschreiben.")
    p.add_argument("--werk", default="immer-wieder-ruegen")
    p.add_argument("--uuid", help="nur diesen Abschnitt (UUID oder ihr Anfang)")
    p.add_argument("--apply", action="store_true", help="tatsächlich schreiben (Vorgabe: Vorschau)")
    p.add_argument("--test", action="store_true", help="auf der Testkopie arbeiten")
    args = p.parse_args(argv)

    paket = c.scrivener_pfad(args.werk, test=args.test)
    if not paket.is_dir():
        print(f"Scrivener-Projekt nicht gefunden: {paket}", file=sys.stderr)
        return 1

    offen = offene_entscheidungen(args.werk, args.uuid)
    if not offen:
        print("Nichts anzuwenden — keine offenen angenommenen Entscheidungen.")
        return 0

    je_abschnitt: dict[str, list[dict]] = defaultdict(list)
    for z in offen:
        je_abschnitt[z["abschnitt_uuid"]].append(z)

    print(f"{len(offen)} Entscheidung(en) in {len(je_abschnitt)} Abschnitt(en)")
    print(f"  Paket: {paket}")

    if args.apply:
        if (dienst := im_sync_ordner(paket)) is not None:
            print(f"\nABBRUCH: Das Paket liegt unter {dienst}. Ein Sync-Dienst legt "
                  "Konfliktkopien IM Paket an und zerstört das Projekt.", file=sys.stderr)
            return 1
        if scrivener_offen(paket):
            print("\nABBRUCH: Das Projekt ist geöffnet. Scrivener überschreibt beim nächsten "
                  "Speichern alles, was hier geschrieben wird. Erst schließen.", file=sys.stderr)
            return 1
        kopie = sichere(paket, args.werk)
        print(f"  Backup: {kopie}")

    gesamt_ok: list[dict] = []
    gesamt_nein = 0
    for uuid, eintraege in je_abschnitt.items():
        rtf = paket / "Files" / "Data" / uuid / "content.rtf"
        titel = eintraege[0]["abschnitt"]
        if not rtf.is_file():
            print(f"\n{titel}\n  ✗ content.rtf fehlt ({uuid[:8]})")
            gesamt_nein += len(eintraege)
            continue

        erledigt, meldungen, abgelehnt = anwenden_auf_datei(
            rtf, eintraege, schreiben=args.apply
        )
        print(f"\n{titel}  ({len(erledigt)} von {len(eintraege)})")
        for m in meldungen:
            print(f"  ✓ {m}")
        for a in abgelehnt:
            print(f"  ✗ {a}")
        gesamt_nein += len(abgelehnt)
        gesamt_ok += erledigt

    print(f"\n{len(gesamt_ok)} angewendet, {gesamt_nein} abgelehnt.")
    if args.apply and gesamt_ok:
        merke_angewendet(args.werk, gesamt_ok)
        print("Im Log als angewendet vermerkt. Scrivener kann wieder geöffnet werden.")
    elif not args.apply:
        print("Vorschau — nichts geschrieben. Mit --apply tatsächlich anwenden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
