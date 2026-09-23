"""Prompts aus diesem Repo nach Mistral Studio spielen.

Dritter Sync neben ``agents/sync.py`` und ``skills/sync.py``, nach demselben
Muster: Die Datei im Repo ist die Quelle der Wahrheit, Studio bekommt eine neue
Version.

    uv run --project workflows python prompts/sync.py --dry-run
    uv run --project workflows python prompts/sync.py

**Was ein Prompt hier ist und was nicht.** Prompts sind eine *Bibliothek*, kein
Laufzeit-Mechanismus: Kein API-Aufruf kann einen gespeicherten Prompt per ID
referenzieren — weder ``ConversationRequest`` noch ``CreateAgentRequest`` haben
ein solches Feld. Man holt den Text mit ``get()``, füllt die Variablen und
schickt ihn selbst.

Deshalb stehen hier **keine** Agent-Instruktionen: Die gehören an den Agent, wo
sie versioniert sind und zur Laufzeit ohne Zusatzaufruf wirken. Was hier steht,
sind die wiederkehrenden Fragen, die der Autor im Chat an sein eigenes Buch
stellt — in Studio versioniert und sichtbar, statt jedes Mal neu formuliert.

Format: eine Markdown-Datei je Prompt, YAML-Frontmatter mit ``name``, ``title``,
``description`` und ``variables`` (kommagetrennt), darunter der Text. Variablen
werden im Text als ``{{name}}`` geschrieben.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROMPTS = ROOT / "prompts"

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", re.S)
_PLATZHALTER = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")
# Wie in skills/sync.py: werkspezifische Inhalte werden erst beim Sync
# eingesetzt, damit sie nicht im (öffentlichen) Repo stehen.
_EINBETTEN = re.compile(r"^[ \t]*<!--\s*einbetten:\s*(.+?)\s*-->[ \t]*$", re.M)


def lies_prompt(pfad: Path) -> tuple[str, str, str, list[str], str]:
    """Zerlegt eine Prompt-Datei in (name, title, description, variables, content)."""
    m = _FRONTMATTER.match(pfad.read_text(encoding="utf-8"))
    if not m:
        raise ValueError(f"{pfad}: kein YAML-Frontmatter gefunden")
    kopf, inhalt = m.group(1), m.group(2).strip()

    def ersetze(treffer: re.Match[str]) -> str:
        ziel = (ROOT / treffer.group(1)).resolve()
        if not ziel.is_file():
            return (
                f"_(Werkkontext {treffer.group(1)} war beim Sync nicht vorhanden.)_"
            )
        return ziel.read_text(encoding="utf-8").strip()

    inhalt = _EINBETTEN.sub(ersetze, inhalt)

    felder: dict[str, str] = {}
    for zeile in kopf.splitlines():
        k, _, v = zeile.partition(":")
        if k.strip():
            felder[k.strip()] = v.strip()

    if not felder.get("name"):
        raise ValueError(f"{pfad}: Frontmatter ohne name")

    deklariert = [v.strip() for v in felder.get("variables", "").split(",") if v.strip()]
    benutzt = sorted(set(_PLATZHALTER.findall(inhalt)))

    # Deklaration und Verwendung müssen zusammenpassen — ein Tippfehler in einer
    # Variablen fällt sonst erst im Chat auf, wenn die Ersetzung ausbleibt.
    if set(deklariert) != set(benutzt):
        raise ValueError(
            f"{pfad}: deklarierte Variablen {deklariert} passen nicht zu den "
            f"im Text benutzten {benutzt}"
        )

    return (
        felder["name"],
        felder.get("title", felder["name"]),
        felder.get("description", ""),
        benutzt,
        inhalt,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Prompt-Dateien nach Studio synchronisieren.")
    p.add_argument("--dry-run", action="store_true", help="nur prüfen, Studio nicht berühren")
    args = p.parse_args(argv)

    pfade = sorted(x for x in PROMPTS.glob("*.md"))
    if not pfade:
        print("Keine Prompt-Dateien gefunden.", file=sys.stderr)
        return 1

    gelesen = []
    for pfad in pfade:
        try:
            gelesen.append(lies_prompt(pfad))
        except ValueError as e:
            print(f"FEHLER  {e}", file=sys.stderr)
            return 1

    if args.dry_run:
        for name, titel, _beschr, variablen, inhalt in gelesen:
            vars_ = f"  Variablen: {', '.join(variablen)}" if variablen else ""
            print(f"[dry-run] OK  {name:22} {len(inhalt):5} Zeichen{vars_}")
            print(f"             {titel}")
        return 0

    from dotenv import load_dotenv

    load_dotenv(ROOT / "workflows" / ".env", override=False)
    from mistralai.client import Mistral
    from mistralai.client import models as m

    client = Mistral(api_key=os.environ["MISTRAL_API_KEY"])
    antwort = client.beta.prompts.list()
    eintraege = getattr(getattr(antwort, "result", antwort), "data", []) or []
    vorhanden = {x.name: x for x in eintraege}

    for name, titel, beschreibung, variablen, inhalt in gelesen:
        definition = m.PromptDefinition(
            content=inhalt,
            variables=[m.PromptVariable(name=v) for v in variablen],
        )
        if name in vorhanden:
            prompt_id = vorhanden[name].id
            client.beta.prompts.create_version(
                prompt_id=prompt_id,
                definition=definition,
                notes="Sync aus personal-ai-stack",
            )
            print(f"neue Version  {name}  ({prompt_id})")
        else:
            erzeugt = client.beta.prompts.create(
                name=name,
                definition=definition,
                title=titel,
                description=beschreibung,
                notes="Sync aus personal-ai-stack",
                sharing_scope="private",
            )
            print(f"angelegt      {name}  ({erzeugt.id})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
