"""Write decisions back into the manuscript — the only part that writes.

    python -m bookcli.apply --work immer-wieder-ruegen              # preview (default)
    python -m bookcli.apply --work immer-wieder-ruegen --apply      # actually write
    python -m bookcli.apply --work immer-wieder-ruegen --uuid 4BEE  # one section only
    python -m bookcli.apply --work immer-wieder-ruegen --test       # on the test copy

The input is the decision log: everything the author accepted in a session and
has not applied yet. What has been applied then sits next to it in
``applied.jsonl`` — a second run does not make the same change twice.

**The discipline, and why it is what it is**

1. **Scrivener has to be closed.** If the project is open, Scrivener overwrites
   everything we wrote at its next save — without a warning, without a conflict.
   Checked with ``lsof``.
2. **No sync folder.** A cloud service syncing into a live ``.scriv`` creates
   conflict copies **inside the package**; Scrivener loses its bearings over
   that. Which is why the project lives under ``~/Werk/``.
3. **Backup before the first byte.** A complete package copy into ``backup/``,
   dated. Not for reassurance, but because point 6 needs it.
4. **Preview is the default.** ``--apply`` writes; without it only shows.
5. **Fourfold anchor.** Section, paragraph index, paragraph hash, search text —
   and the search text has to occur **exactly once**. No fuzzy matching. If the
   hash no longer matches, the author has touched the paragraph since the
   session; then it is rejected and named, not guessed.
6. **Re-read after writing.** The written file is decoded again and held against
   the expected text. If it deviates, the backup is restored and it aborts. A
   silent bug in the encoder would otherwise only surface weeks later — while
   reading one's own book.

The work is done byte-wise: only the span carrying the search text is replaced.
Every other byte of ``content.rtf`` stays as Scrivener wrote it.

Output stays German: the author reads it.
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

from workflows.book import config as c
from workflows.book import decisions as log
from workflows.book.scrivener import decode_rtf, replace_in_rtf

DATA = Path(__file__).resolve().parents[2] / "data"
SYNC_FOLDERS = ("Library/CloudStorage", "Dropbox", "Google Drive", "OneDrive", "iCloud")


def scrivener_open(package: Path) -> bool:
    """Whether a process holds files inside the package open."""
    try:
        r = subprocess.run(["lsof", "+D", str(package)], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False  # Without lsof, carry on rather than block for no reason.
    return bool(r.stdout.strip() and len(r.stdout.strip().splitlines()) > 1)


def in_sync_folder(package: Path) -> str | None:
    full = str(package.resolve())
    for name in SYNC_FOLDERS:
        if name in full:
            return name
    return None


def back_up(package: Path, work: str) -> Path:
    """Full package copy into ``backup/`` — before the first byte is written."""
    target_dir = c.work_path(work, "backup")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{package.stem}-{datetime.now(UTC):%Y%m%d-%H%M%S}.scriv"
    shutil.copytree(package, target)
    return target


def _key(entry: dict) -> str:
    """Stable identifier of a decision — recognises repeats."""
    return (
        f"{entry['session']}|{entry['section_uuid']}|"
        f"{entry['paragraph_index']}|{entry['search']}"
    )


def pending_decisions(work: str, only_uuid: str | None) -> list[dict]:
    """Accepted decisions that have not been applied yet."""
    already = set()
    file = log.log_dir(DATA, work) / "applied.jsonl"
    if file.is_file():
        for line in file.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    already.add(json.loads(line)["key"])
                except (json.JSONDecodeError, KeyError):
                    continue

    pending = []
    for entry in log.read_all(DATA, work):
        if entry.get("decision") != "angenommen" or _key(entry) in already:
            continue
        if only_uuid and not entry["section_uuid"].lower().startswith(only_uuid.lower()):
            continue
        pending.append(entry)
    return pending


def mark_applied(work: str, entries: list[dict]) -> None:
    file = log.log_dir(DATA, work) / "applied.jsonl"
    file.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    with file.open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(
                json.dumps(
                    {"ts": now, "key": _key(entry), "section": entry["section"]},
                    ensure_ascii=False,
                )
                + "\n"
            )


def apply_to_file(
    rtf: Path, entries: list[dict], *, write: bool
) -> tuple[list[dict], list[str], list[str]]:
    """Apply one section's decisions.

    Returns ``(applied_entries, messages, rejected)`` — the entries themselves,
    so the caller can mark them as applied without back-computing them from
    message texts.

    Works on a copy of the bytes in memory and only writes once the result
    matches what we expect.
    """
    raw = rtf.read_bytes()
    paragraphs = decode_rtf(raw)
    expected = list(paragraphs)
    applied: list[dict] = []
    messages: list[str] = []
    rejected: list[str] = []

    for entry in entries:
        i = entry["paragraph_index"]
        short = entry["search"][:45]
        if not 0 <= i < len(paragraphs):
            rejected.append(f"Absatz {i} gibt es nicht ({len(paragraphs)} vorhanden) — {short!r}")
            continue

        # Anchor 2: hash against the state at analysis time — and specifically
        # against the paragraph as it stood at the START of this run, not
        # against our own intermediate states. The hash is meant to detect
        # FOREIGN changes (the author kept writing in Scrivener). Checked
        # against `expected` it would fire on the second change in the same
        # paragraph — and several findings per paragraph are the normal case.
        # Measured: 9 of 15 decisions failed on exactly that, although the
        # author had approved them together.
        actual = hashlib.sha256(paragraphs[i].encode("utf-8")).hexdigest()[:16]
        if entry.get("paragraph_hash") and actual != entry["paragraph_hash"]:
            rejected.append(
                f"Absatz {i} wurde seit der Sitzung geändert (Hash {actual} statt "
                f"{entry['paragraph_hash']}) — {short!r}"
            )
            continue

        if entry.get("own_version"):
            # The author rewrote the paragraph himself — not a search and
            # replace but a swap. The byte replacement still needs an anchor:
            # the whole old paragraph.
            old, new_text = expected[i], entry["own_version"]
        else:
            old, new_text = entry["search"], entry["replace"]

        try:
            raw = replace_in_rtf(raw, i, old, new_text)
        except ValueError as exc:
            rejected.append(f"{exc} — {short!r}")
            continue

        expected[i] = expected[i].replace(old, new_text, 1)
        applied.append(entry)
        if entry.get("own_version"):
            # Make it visible that the WHOLE paragraph is being swapped here —
            # in the preview this otherwise looked like a word substitution with
            # a strange result.
            messages.append(
                f"Absatz {i}: GANZER ABSATZ ersetzt (eigene Fassung) → {new_text[:60]!r}"
            )
        else:
            messages.append(f"Absatz {i}: {short!r} → {new_text[:45]!r}")

    if not applied:
        return applied, messages, rejected

    # Check 6: decode again and hold it against the expectation.
    if decode_rtf(raw) != expected:
        return [], [], rejected + [
            "ABBRUCH: Die neu geschriebene Datei dekodiert nicht zum erwarteten Text. "
            "Nichts geschrieben."
        ]

    if write:
        rtf.write_bytes(raw)
    return applied, messages, rejected


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Entscheidungen ins Manuskript zurückschreiben.")
    p.add_argument("--work", default="immer-wieder-ruegen")
    p.add_argument("--uuid", help="nur diesen Abschnitt (UUID oder ihr Anfang)")
    p.add_argument("--apply", action="store_true", help="tatsächlich schreiben (Vorgabe: Vorschau)")
    p.add_argument("--test", action="store_true", help="auf der Testkopie arbeiten")
    args = p.parse_args(argv)

    package = c.scrivener_path(args.work, test=args.test)
    if not package.is_dir():
        print(f"Scrivener-Projekt nicht gefunden: {package}", file=sys.stderr)
        return 1

    pending = pending_decisions(args.work, args.uuid)
    if not pending:
        print("Nichts anzuwenden — keine offenen angenommenen Entscheidungen.")
        return 0

    per_section: dict[str, list[dict]] = defaultdict(list)
    for entry in pending:
        per_section[entry["section_uuid"]].append(entry)

    print(f"{len(pending)} Entscheidung(en) in {len(per_section)} Abschnitt(en)")
    print(f"  Paket: {package}")

    if args.apply:
        if (service := in_sync_folder(package)) is not None:
            print(f"\nABBRUCH: Das Paket liegt unter {service}. Ein Sync-Dienst legt "
                  "Konfliktkopien IM Paket an und zerstört das Projekt.", file=sys.stderr)
            return 1
        if scrivener_open(package):
            print("\nABBRUCH: Das Projekt ist geöffnet. Scrivener überschreibt beim nächsten "
                  "Speichern alles, was hier geschrieben wird. Erst schließen.", file=sys.stderr)
            return 1
        copy = back_up(package, args.work)
        print(f"  Backup: {copy}")

    all_applied: list[dict] = []
    all_rejected = 0
    for uuid, entries in per_section.items():
        rtf = package / "Files" / "Data" / uuid / "content.rtf"
        title = entries[0]["section"]
        if not rtf.is_file():
            print(f"\n{title}\n  ✗ content.rtf fehlt ({uuid[:8]})")
            all_rejected += len(entries)
            continue

        applied, messages, rejected = apply_to_file(
            rtf, entries, write=args.apply
        )
        print(f"\n{title}  ({len(applied)} von {len(entries)})")
        for m in messages:
            print(f"  ✓ {m}")
        for r in rejected:
            print(f"  ✗ {r}")
        all_rejected += len(rejected)
        all_applied += applied

    print(f"\n{len(all_applied)} angewendet, {all_rejected} abgelehnt.")
    if args.apply and all_applied:
        mark_applied(args.work, all_applied)
        print("Im Log als angewendet vermerkt. Scrivener kann wieder geöffnet werden.")
    elif not args.apply:
        print("Vorschau — nichts geschrieben. Mit --apply tatsächlich anwenden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
