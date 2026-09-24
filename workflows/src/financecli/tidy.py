"""Collect everything private-financial into one place — reversibly.

    python -m financecli.tidy            # preview (default)
    python -m financecli.tidy --apply    # actually move
    python -m financecli.tidy --undo     # take the last applied batch back

Why this exists: the material was spread over seven places. The most important
document — the top-level planning workbook — sat on the Desktop with an Excel
lock file next to it, the statements were three folders deep, and 58 further
candidates were in Downloads and on the Desktop. Nothing can be built on that.

**The discipline**

1. **Preview is the default.** ``--apply`` moves; without it only shows.
2. **Nothing is renamed, nothing merged, no sub-structure flattened.** A folder
   that arrives here keeps its shape exactly — ``Telsche/Rechnungen/Victron/``
   stays ``Telsche/Rechnungen/Victron/``.
3. **Never overwrite.** If the target exists, the move is skipped and named.
   Not "renamed to (1)", not merged — skipped, so the author decides.
4. **Never move an open file.** Checked with ``lsof``. Excel holds a lock on
   the planning workbook right now, and moving a file out from under an open
   application is how spreadsheets get lost.
5. **Every move is logged** to ``data/finance/moves.jsonl`` with source, target
   and timestamp, and ``--undo`` walks the last batch backwards.
6. **Work material stays out.** ``Belege Juli`` are receipts for the company
   credit card. tidy proposes where they belong and never touches them again;
   the ledger never reads from there.

The rules themselves are data (``shared/finance.json`` → ``tidy``), so a wrong
target is a JSON edit rather than a patch.

Output stays German: the author reads it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from workflows.finance import config as c
from workflows.shared_config import expand

DATA = Path(__file__).resolve().parents[2] / "data" / "finance"
MOVES = DATA / "moves.jsonl"

# Files that are never moved and never counted — they are noise, not material.
IGNORED_NAMES = {".DS_Store", "Icon\r"}


@dataclass
class Move:
    """One proposed move. ``reason`` is what the author reads in the preview."""

    source: Path
    target: Path
    reason: str
    blocked: str = ""  # non-empty means: will not happen, and why


# --------------------------------------------------------------------------- #
# Safety
# --------------------------------------------------------------------------- #


def is_open(path: Path) -> bool:
    """Whether a process holds this file (or anything inside it) open.

    Without ``lsof`` we carry on rather than block for no reason — the same
    judgement ``bookcli/apply.py`` makes.
    """
    try:
        args = ["lsof", "+D", str(path)] if path.is_dir() else ["lsof", "--", str(path)]
        result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    lines = [ln for ln in result.stdout.strip().splitlines() if ln.strip()]
    return len(lines) > 1


def _blocked_reason(source: Path, target: Path) -> str:
    """Why this move must not happen — empty string when it may."""
    if not source.exists():
        return "Quelle gibt es nicht (mehr)"
    if target.exists():
        return f"Ziel existiert bereits: {target}"
    if is_open(source):
        return "in einer Anwendung geöffnet"
    return ""


def _plan_move(source: Path, target: Path, reason: str) -> Move:
    return Move(source, target, reason, _blocked_reason(source, target))


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #


def _account_for(name: str) -> str | None:
    """Which account folder a statement file belongs to, by its file name.

    The prefixes are IBAN fragments, so the map lives in the gitignored
    ``paths.json`` rather than in the checked-in domain config.
    """
    for prefix, account in c.paths().get("accounts_from_filename", {}).items():
        if prefix.startswith("_"):
            continue
        if name.startswith(prefix):
            return account
    return None


def plan() -> list[Move]:
    """Everything tidy would do, in the order it would do it."""
    paths = c.paths()
    root = c.root()
    moves: list[Move] = []

    # 1. The planning workbook, wherever it currently is.
    planning = paths["planning_workbook"]
    before = planning.get("path_before_tidy")
    if before:
        source = expand(before)
        if source.exists():
            moves.append(
                _plan_move(source, c.planning_workbook(), "das Planungsdokument")
            )

    # 2. Whole folders, structure untouched.
    for source_str, folder_name in c.paths().get("collect_from", {}).items():
        if source_str.startswith("_"):
            continue
        source = expand(source_str)
        if not source.exists():
            continue
        target = root / folder_name
        if source.is_dir() and target.exists():
            # The target folder is already there — move the CONTENTS, so the
            # statements land in Konten/ rather than in Konten/Kontoauszüge/.
            for child in sorted(source.iterdir()):
                if child.name in IGNORED_NAMES:
                    continue
                moves.append(_plan_move(child, target / child.name, f"→ {folder_name}/"))
        else:
            moves.append(_plan_move(source, target, f"Ordner → {folder_name}/"))

    # 3. Statements into their account folder.
    konten = root / "Konten"
    for source in sorted(konten.rglob("*")) if konten.exists() else []:
        if source.is_dir() or source.name in IGNORED_NAMES:
            continue
        account = _account_for(source.name)
        if account and source.parent.name != account:
            moves.append(
                _plan_move(source, konten / account / source.name, f"Konto {account}")
            )

    # 4. Superseded material into the archive.
    for source_str in paths.get("archive", {}).get("paths", []):
        source = expand(source_str)
        if source.exists():
            moves.append(_plan_move(source, root / "Archiv" / source.name, "überholt"))

    # 5. His own prose into Kontext.
    for source_str in paths.get("context", {}).get("paths", []):
        source = expand(source_str)
        if source.exists():
            moves.append(_plan_move(source, root / "Kontext" / source.name, "eigener Text"))

    # 6. Work material — proposed, never claimed for the ledger. The NAMES are
    #    a domain rule (shared/finance.json); where they go is personal and
    #    therefore lives in paths.json.
    targets = {k: v for k, v in paths.get("out_of_scope_targets", {}).items() if not k.startswith("_")}
    for folder_name in c.TIDY["out_of_scope"]["names"]:
        source = Path.home() / "Documents" / folder_name
        target = targets.get(folder_name)
        if source.exists() and target:
            moves.append(
                _plan_move(source, expand(target), "BERUFLICH — nicht ins Ledger")
            )

    # 7. The scattered candidates.
    moves.extend(_scattered(root))
    return moves


def _scattered(root: Path) -> list[Move]:
    """Loose files in Downloads and on the Desktop that look financial.

    They land in a holding pen (``Unsortiert/``), never in a folder the ledger
    reads. The patterns match a FILE NAME and nothing has looked inside — and
    the first real preview showed why that matters: 54 of 57 hits were work
    material (vendor invoices, company-card summaries), not private bookkeeping.
    Collecting them in one place is still worth doing, because that is what was
    asked for; filing them as private finance would be a lie.

    Deliberately shallow (no ``rglob``): a file three folders deep in Downloads
    belongs to whatever put it there, not to this domain.
    """
    patterns = [p.lower() for p in c.TIDY["scatter_patterns"]]
    out: list[Move] = []
    for source_str in c.TIDY["scatter_sources"]:
        folder = expand(source_str)
        if not folder.is_dir():
            continue
        for source in sorted(folder.iterdir()):
            if source.is_dir() or source.name in IGNORED_NAMES or source.name.startswith("~$"):
                continue
            name = source.name.lower()
            hit = next((p for p in patterns if p in name), None)
            if hit:
                out.append(
                    _plan_move(
                        source,
                        root / c.TIDY["scatter_target"] / source.name,
                        f"Fundstück ({hit}) — ungeprüft, oft beruflich",
                    )
                )
    return out


# --------------------------------------------------------------------------- #
# Doing it
# --------------------------------------------------------------------------- #


def _log(entries: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with MOVES.open("a", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def apply(moves: list[Move]) -> tuple[int, int]:
    """Move what is not blocked. Returns (moved, skipped)."""
    batch = f"{datetime.now(UTC):%Y%m%d-%H%M%S}"
    done: list[dict] = []
    moved = skipped = 0
    for move in moves:
        # Re-check immediately before touching anything: the preview may be
        # minutes old, and "target exists" can have become true since.
        reason = _blocked_reason(move.source, move.target)
        if reason:
            print(f"  übersprungen  {move.source.name} — {reason}")
            skipped += 1
            continue
        move.target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(move.source), str(move.target))
        done.append(
            {
                "batch": batch,
                "ts": datetime.now(UTC).isoformat(),
                "source": str(move.source),
                "target": str(move.target),
                "reason": move.reason,
            }
        )
        moved += 1
    if done:
        _log(done)
    return moved, skipped


def undo() -> int:
    """Take the most recent applied batch back."""
    if not MOVES.is_file():
        print("Kein Protokoll — es gibt nichts zurückzunehmen.")
        return 0
    entries = [json.loads(line) for line in MOVES.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not entries:
        print("Protokoll ist leer.")
        return 0
    last = entries[-1]["batch"]
    batch = [e for e in entries if e["batch"] == last]
    print(f"Nehme Durchgang {last} zurück — {len(batch)} Bewegung(en):")
    back = 0
    for entry in reversed(batch):
        target, source = Path(entry["target"]), Path(entry["source"])
        if not target.exists():
            print(f"  fehlt   {target}")
            continue
        if source.exists():
            print(f"  belegt  {source} — nicht zurückgelegt")
            continue
        source.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(target), str(source))
        print(f"  zurück  {source}")
        back += 1
    _log([{**e, "batch": f"{last}-undo", "ts": datetime.now(UTC).isoformat()} for e in batch])
    return back


def show(moves: list[Move], root: Path) -> None:
    """The preview — grouped by reason, because 60 lines in a row read as noise."""
    if not moves:
        print("Nichts zu tun — es liegt bereits alles am richtigen Ort.")
        return
    by_reason: dict[str, list[Move]] = {}
    for move in moves:
        by_reason.setdefault(move.reason, []).append(move)

    doable = sum(1 for m in moves if not m.blocked)
    print(f"ZIEL  {root}\n")
    for reason, group in by_reason.items():
        print(f"{reason}  ({len(group)})")
        for move in group[:12]:
            mark = "  !" if move.blocked else "   "
            note = f"   ← {move.blocked}" if move.blocked else ""
            try:
                shown = move.source.relative_to(Path.home())
            except ValueError:
                shown = move.source
            print(f"{mark} ~/{shown}{note}")
        if len(group) > 12:
            print(f"    … und {len(group) - 12} weitere")
        print()
    blocked = len(moves) - doable
    print(f"{doable} Bewegung(en) möglich, {blocked} blockiert.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finanz-Ablage aufräumen.")
    parser.add_argument("--apply", action="store_true", help="wirklich verschieben")
    parser.add_argument("--undo", action="store_true", help="letzten Durchgang zurücknehmen")
    args = parser.parse_args(argv)

    if args.undo:
        return 0 if undo() >= 0 else 1

    try:
        root = c.root()
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    moves = plan()
    if not args.apply:
        show(moves, root)
        print("\nVorschau — nichts verändert. Mit --apply ausführen.")
        return 0

    for name in c.TIDY["folders"]:
        (root / name).mkdir(parents=True, exist_ok=True)
    moved, skipped = apply(moves)
    print(f"\n{moved} verschoben, {skipped} übersprungen. Rückgängig: --undo")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
