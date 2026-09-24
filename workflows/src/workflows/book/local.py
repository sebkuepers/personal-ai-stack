"""Activities that touch the local disk.

The original design forbade this categorically: workflows were to be text in /
text out, because the worker ran in the Cloudflare container and ``~/Werk/…``
does not exist there. The worker now runs locally, so the reason is gone — and
with it an unnecessary restriction: a conversational workflow that can list the
chapters itself can be started from Le Chat without a single parameter.

What remains is the separation that actually matters: **I/O lives in activities,
never in the workflow body.** The workflow is replayed on a retry; a file that
changed in between would throw it off course. An activity reads exactly once,
and its result is in the event history afterwards.

Nothing is written here. Writing back into the manuscript is a separate, guarded
step and deliberately stays outside every workflow.

Messages that reach the author stay German.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import mistralai.workflows as workflows

from . import config
from . import decisions as log
from .models import Decision, VoiceProfile
from .scrivener import read_binder
from .voice import render_for_agent

REPO = Path(__file__).parents[4]
DATA = REPO / "workflows" / "data"


def _modified(package: Path, uuid: str) -> str:
    """ISO date of a section's last change, empty when unknown."""
    file = package / "Files" / "Data" / uuid / "content.rtf"
    if not file.is_file():
        return ""
    return datetime.fromtimestamp(file.stat().st_mtime, tz=UTC).date().isoformat()


def _manuscript(work: str):
    w = config.load_work(work)
    structure = w.get("structure") or {}
    return read_binder(
        config.scrivener_path(work),
        work,
        root=structure.get("root"),
        chapter_level=structure.get("chapter_level", 0),
    )


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def list_sections(work: str) -> dict:
    """All sections that have text, for the choice in the chat."""
    m = _manuscript(work)
    package = config.scrivener_path(work)
    sections = [
        {
            "uuid": s.uuid,
            "title": s.title,
            "chapter": s.chapter or "—",
            "path": s.path,
            "words": s.words,
            "paragraphs": len(s.paragraphs),
            "label": s.label,
            "status": s.status,
            # When the section was last touched. NOT in the binder — Scrivener
            # shows the column but stores it as the file date of content.rtf.
            # Which is exactly why an activity has to read it.
            "last_changed": _modified(package, s.uuid),
        }
        for s in m.sections
        if s.has_text
    ]
    # The outline nodes without text too: a chapter that holds nothing yet is
    # the single most important piece of information for the overview.
    without_text = [
        {
            "uuid": s.uuid,
            "title": s.title,
            "chapter": s.chapter or "—",
            "path": s.path,
            "is_folder": s.is_folder,
        }
        for s in m.sections
        if not s.has_text
    ]
    w = config.load_work(work)
    return {
        "work": work,
        "title": w.get("title", work),
        "subtitle": w.get("subtitle", ""),
        "sections": sections,
        "empty": without_text,
        "chapters_planned": [
            c.get("title", "") for c in (w.get("chapters") or []) if isinstance(c, dict)
        ],
    }


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def read_section(work: str, uuid: str) -> dict:
    """One section with its paragraphs and paragraph hashes.

    The hashes travel through the whole session: when applying later it is
    checked whether the paragraph is still the same. A session can stay open for
    hours — anything can happen in Scrivener in that time.
    """
    m = _manuscript(work)
    s = next((x for x in m.sections if x.uuid == uuid), None)
    if s is None:
        raise ValueError(f"Abschnitt {uuid} gibt es in {work} nicht.")
    return {
        "uuid": s.uuid,
        "title": s.title,
        "path": s.path,
        "text": s.text,
        "paragraphs": s.paragraphs,
        "hashes": [s.paragraph_hash(i) for i in range(len(s.paragraphs))],
        "words": s.words,
    }


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def load_voice_profile(work: str) -> str:
    """The voice profile in the form the style agent gets — empty when there is none."""
    path = REPO / "shared" / "book" / f"{work}-voice.json"
    if not path.is_file():
        return ""
    return render_for_agent(VoiceProfile.model_validate_json(path.read_text(encoding="utf-8")))


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def list_works() -> list[dict]:
    """All works that have a config in ``shared/book/``.

    This lets the conversational workflow start without any parameter — and ask
    for the work only when there is more than one.
    """
    directory = REPO / "shared" / "book"
    works = []
    for path in sorted(directory.glob("*.json")):
        name = path.stem
        if name.endswith(("-voice", "-context")) or name.startswith(("eval-", "work.")):
            continue
        if ".example" in path.name:
            continue
        try:
            w = config.load_work(name)
        except Exception:  # noqa: BLE001 — one broken config must not topple the rest
            continue
        works.append({"slug": name, "title": w.get("title", name)})
    return works


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=60),
)
async def read_chapter(work: str, chapter: str) -> dict:
    """A whole chapter with all its sections — the input of the content level.

    Level 3 judges arcs, cast and omissions. That is not visible on a single
    section, so the chapter comes in as a whole here.
    """
    m = _manuscript(work)
    inside = [s for s in m.sections if s.has_text and s.chapter == chapter]
    if not inside:
        raise ValueError(f"Kapitel {chapter!r} hat in {work} keinen Text.")
    return {
        "chapter": chapter,
        "sections": [
            {
                "title": s.title,
                "path": s.path,
                "text": s.text,
                "words": s.words,
                "synopsis": s.synopsis or "",
                "status": s.status,
                "label": s.label,
            }
            for s in inside
        ],
        "words": sum(s.words for s in inside),
    }


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def load_context(work: str, name: str) -> str:
    """A context document from ``kontext/`` — exposé, chapter plan, whatever comes.

    Empty string when it is missing: a missing exposé should not prevent the
    review, only weaken it — and that then shows up in the notes.
    """
    directory = config.work_path(work, "context")
    file = directory / f"{name}.md"
    if not file.is_file():
        return ""
    return file.read_text(encoding="utf-8")


@workflows.activity(
    retry_policy_max_attempts=3,
    start_to_close_timeout=timedelta(seconds=30),
)
async def write_decisions(
    work: str,
    section: dict,
    session_id: str,
    decisions: list[dict],
) -> int:
    """Append a level's decisions to the log — immediately, not at the very end.

    Called after EVERY approved level. If the session is aborted afterwards or
    times out, nothing up to that point is lost. Idempotent enough: a retry
    appends the same lines once more, and the ``session`` identifier makes
    duplicates countable later.
    """
    lines = [
        log.line(
            Decision.model_validate(d),
            work=work,
            section_uuid=section["uuid"],
            section_title=section["title"],
            path=section.get("path") or [],
            session_id=session_id,
        )
        for d in decisions
    ]
    return log.write(log.log_file(DATA, work), lines)


# How long a session lock counts as fresh. Longer than a session typically
# takes, shorter than a night — a lock that blocks the section until next
# morning is worse than the problem.
LOCK_FRESH = timedelta(hours=3)


@workflows.activity(
    retry_policy_max_attempts=2,
    start_to_close_timeout=timedelta(seconds=30),
)
async def claim_section(work: str, uuid: str, session_id: str, title: str) -> str:
    """Register a running session and warn about another one.

    **Warns, does not block.** A lock can be orphaned — crashed session, closed
    browser, timeout. Someone who may then no longer edit the section is worse
    off than someone who decides the same thing twice. The anchor check when
    applying catches the actual damage anyway: a paragraph the other session
    changed has a different hash.

    Returns a hint text or an empty string.
    """
    directory = DATA / "book" / work / "sessions"
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / f"{uuid}.json"
    now = datetime.now(UTC)

    hint = ""
    if file.is_file():
        try:
            other = json.loads(file.read_text(encoding="utf-8"))
            since = datetime.fromisoformat(other["since"])
            if other.get("session") != session_id and now - since < LOCK_FRESH:
                minutes = int((now - since).total_seconds() // 60)
                hint = (
                    f"Achtung: An {title!r} läuft seit {minutes} Minuten eine andere Sitzung "
                    f"({other['session'][:8]}). Beide zu Ende zu führen heißt, dieselben Stellen "
                    "zweimal zu entscheiden — die zweite Anwendung scheitert dann an der "
                    "Ankerprüfung."
                )
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # A broken lock file is no reason to prevent the session.

    file.write_text(
        json.dumps(
            {"session": session_id, "section": title, "since": now.isoformat(timespec="seconds")},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return hint


@workflows.activity(
    retry_policy_max_attempts=1,
    start_to_close_timeout=timedelta(seconds=30),
)
async def release_section(work: str, uuid: str, session_id: str) -> bool:
    """Clear our own lock. Other sessions' locks are left untouched."""
    file = DATA / "book" / work / "sessions" / f"{uuid}.json"
    if not file.is_file():
        return False
    try:
        if json.loads(file.read_text(encoding="utf-8")).get("session") != session_id:
            return False
    except json.JSONDecodeError:
        return False
    file.unlink()
    return True
