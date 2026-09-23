"""Skills aus diesem Repo nach Mistral Studio spielen.

Gegenstück zu ``agents/sync.py``: Dort sind die Agents die Quelle der Wahrheit,
hier die ``SKILL.md``-Dateien. Beides bleibt im Git versioniert, beides ist in
Studio sichtbar — das ist der Punkt der Übung.

    uv run --project workflows python skills/sync.py --dry-run
    uv run --project workflows python skills/sync.py

**Wer Skills tatsächlich lädt:** Vibe Work, Vibe Code und Projekte. Ein
Studio-Agent in einem Workflow kann *keinen* Skill referenzieren — die erlaubten
Tool-Typen sind code_interpreter, connector, document_library, function,
image_generation und web_search. Der Stil-Agent bekommt sein Stimmprofil deshalb
weiterhin zur Laufzeit in den Prompt gerendert. Skills sind für die Arbeit *mit*
Mistral gedacht, nicht für die Workflows.

**Warum Inhalte eingebettet werden:** Ein Skill in Studio muss selbsttragend
sein — Vibe hat keinen Zugriff auf lokale Dateien. Ein ``SKILL.md`` darf deshalb
Platzhalter der Form ``<!-- einbetten: <pfad> -->`` enthalten; der Inhalt der
Datei wird beim Sync an dieser Stelle eingesetzt. So wandert das Stimmprofil in
den Skill-Body, ohne im (öffentlichen) Repo zu liegen.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
_EINBETTEN = re.compile(r"^[ \t]*<!--\s*einbetten:\s*(.+?)\s*-->[ \t]*$", re.M)


def lies_skill(pfad: Path) -> tuple[str, str, str]:
    """Zerlegt eine SKILL.md in (name, description, body).

    Der Body wird um eingebettete Dateien ergänzt — siehe Modul-Docstring.
    """
    roh = pfad.read_text(encoding="utf-8")
    m = _FRONTMATTER.match(roh)
    if not m:
        raise ValueError(f"{pfad}: kein YAML-Frontmatter gefunden")
    kopf, body = m.group(1), m.group(2)

    felder: dict[str, str] = {}
    schluessel = None
    for zeile in kopf.splitlines():
        if ":" in zeile and not zeile.startswith((" ", "\t")):
            schluessel, _, wert = zeile.partition(":")
            schluessel = schluessel.strip()
            felder[schluessel] = wert.strip()
        elif schluessel:  # Fortsetzungszeile eines mehrzeiligen Werts
            felder[schluessel] += " " + zeile.strip()

    fehlend = [k for k in ("name", "description") if not felder.get(k)]
    if fehlend:
        raise ValueError(f"{pfad}: Frontmatter ohne {fehlend}")

    def ersetze(treffer: re.Match[str]) -> str:
        ziel = (ROOT / treffer.group(1)).resolve()
        if not ziel.is_file():
            return (
                f"> _Hinweis: {treffer.group(1)} war beim Sync nicht vorhanden "
                f"und fehlt deshalb hier._"
            )
        return ziel.read_text(encoding="utf-8").strip()

    return felder["name"], felder["description"], _EINBETTEN.sub(ersetze, body).strip()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="SKILL.md-Dateien nach Studio synchronisieren.")
    p.add_argument("--dry-run", action="store_true", help="nur prüfen, Studio nicht berühren")
    p.add_argument("--nur", help="nur diesen Skill (Ordnername)")
    args = p.parse_args(argv)

    pfade = sorted(SKILLS.glob("*/SKILL.md"))
    if args.nur:
        pfade = [x for x in pfade if x.parent.name == args.nur]
    if not pfade:
        print("Keine SKILL.md gefunden.", file=sys.stderr)
        return 1

    gelesen = []
    for pfad in pfade:
        try:
            gelesen.append((pfad, *lies_skill(pfad)))
        except ValueError as e:
            print(f"FEHLER  {e}", file=sys.stderr)
            return 1

    if args.dry_run:
        for pfad, name, beschreibung, body in gelesen:
            eingebettet = len(_EINBETTEN.findall(pfad.read_text(encoding="utf-8")))
            print(
                f"[dry-run] OK  {name:22} {len(body):6} Zeichen"
                f"{f'  (+{eingebettet} eingebettet)' if eingebettet else ''}"
            )
            print(f"             {beschreibung[:88]}…")
        return 0

    from dotenv import load_dotenv

    load_dotenv(ROOT / "workflows" / ".env", override=False)
    from mistralai.client import Mistral
    from mistralai.client import models as m

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    # Die Liste ist paginiert: SkillsListResponse{next, result} → result.data
    antwort = client.beta.skills.list()
    eintraege = getattr(getattr(antwort, "result", antwort), "data", []) or []
    vorhanden = {s.name: s for s in eintraege}

    for _pfad, name, beschreibung, body in gelesen:
        definition = m.SkillDefinition(description=beschreibung, body=body, assets={})
        if name in vorhanden:
            skill_id = vorhanden[name].id
            client.beta.skills.create_version(
                skill_id=skill_id,
                definition=definition,
                notes="Sync aus personal-ai-stack",
            )
            print(f"neue Version  {name}  ({skill_id})")
        else:
            erzeugt = client.beta.skills.create(
                name=name,
                definition=definition,
                notes="Sync aus personal-ai-stack",
                sharing_scope="private",
            )
            print(f"angelegt      {name}  ({erzeugt.id})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
