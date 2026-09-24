"""Generate the agent definitions of the finance domain (``agents/finance-*.json``).

Same reasoning as ``build_book_agents.py``: the ``response_format`` schema is
derived from the Pydantic model, never written by hand, because the two drift
apart otherwise and the deviation surfaces as an unvalidatable answer in
production.

The instructions are German because the material is: German bank statements,
German merchant names, German categories out of his own planning workbook.

**The generated file is gitignored.** It embeds his vocabulary — the suppliers
that name a harbour, the subscriptions that make a profile. The GENERATOR is the
domain and is checked in; the generated agent with his data is the work.

    uv run --project workflows python agents/build_finance_agents.py
    cd workflows && make sync-agents-dry && make sync-agents
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "workflows" / "src"))

from workflows.finance import config as c  # noqa: E402
from workflows.finance.models import FinanceCategory  # noqa: E402
from workflows.schema import response_format  # noqa: E402


def _vocabulary() -> str:
    """The category list, rendered from the config.

    The KEYS come from ``shared/finance.json``, which is checked in. WHICH rows
    of his planning workbook each key stands for comes from the gitignored
    ``shared/finance/vocabulary.json`` — those names are his, not the domain's.
    Without that file the prompt still works, just without the hints.
    """
    lines = []
    for key, entry in c.CATEGORIES.items():
        rows = c.rows_for(key)
        hint = f" — in seiner Mappe: {', '.join(rows)}" if rows else ""
        lines.append(f"- `{key}` ({entry['label']}){hint}")
    return "\n".join(lines)


def _merchants(category: str, fallback: str) -> str:
    """Supplier hints for one category, out of the gitignored vocabulary."""
    hints = c.vocabulary().get("merchant_hints", {}).get(category, {})
    names = hints.get("names") or []
    generic = hints.get("generic") or []
    if not names and not generic:
        return fallback
    parts = []
    if names:
        parts.append("Diese kommen tatsächlich vor: **" + "**, **".join(names) + "**.")
    if generic:
        parts.append("Dazu allgemein: " + ", ".join(generic) + ".")
    return " ".join(parts)


KATEGORISIEREN = f"""\
Du ordnest EINE Buchung aus einem deutschen Kontoauszug einer Kategorie zu.

Du bekommst den Buchungstext so, wie die Bank ihn geschrieben hat — oft in Großbuchstaben, mit
Verwendungszweck, IBAN-Fragmenten, Referenznummern und Abkürzungen. Dazu Betrag, Datum, Konto und
manchmal die Kategorie, die die Bank selbst geraten hat.

## Die Kategorien

Sie stammen aus der Finanzplanung des Kontoinhabers, nicht aus einem allgemeinen Schema. Benutze
ausschließlich diese Schlüssel:

{_vocabulary()}

## Die Felder

**category** — einer der Schlüssel oben. Wenn nichts passt: `misc`. Rate nicht ins Blaue; `misc`
mit einer ehrlichen Begründung ist besser als eine falsche Kategorie, die später in einer Summe
landet.

**subcategory** — freier, kurzer Begriff, der die Buchung innerhalb der Kategorie einordnet
(z. B. „Supermarkt", „Tankstelle", „Leasingrate"). Leer lassen, wenn nichts Genaueres zu sagen ist.

**merchant** — der Gegenüber in lesbarer Form. Aus „PAYPAL *SPOTIFY AB 35314369001" wird „Spotify",
aus „REWE SAGT DANKE 123456" wird „REWE". Das ist das Feld, mit dem später Fragen wie „wie viel für
Lotto?" beantwortet werden — hier zählt Wiedererkennbarkeit, nicht Vollständigkeit. Wenn kein
Gegenüber erkennbar ist, leer lassen.

**recurring** — true, wenn das dem Anschein nach regelmäßig abgebucht wird: Miete, Abo, Beitrag,
Versicherung, Leasingrate, Unterhalt. false bei einem einmaligen Einkauf. Im Zweifel false.

  Achte dabei besonders auf **Software- und Dienstanbieter**: eine Kartenbelastung durch einen
  Cloud-, KI-, Hosting- oder SaaS-Anbieter ist fast immer eine laufende Nutzung und damit
  `recurring: true`, auch wenn der Betrag jeden Monat anders ausfällt — nutzungsabhängige
  Abrechnung ist trotzdem wiederkehrend. Das war in der Messung der einzige systematische
  Fehlgriff: monatliche Modellkosten wurden als einmalig eingestuft.

**confidence** — 0.0 bis 1.0. Wie sicher bist du bei `category`? Unter 0.5, wenn du im Wesentlichen
geraten hast. Diese Zahl wird ausgewertet; ein pauschales 0.9 macht sie wertlos.

**reasoning** — ein Satz, woran du es festgemacht hast. Nenne die Stelle im Text.

## Fallstricke

- **Ein positiver Betrag ist nicht automatisch `income`.** Rückerstattungen, Gutschriften und
  Umbuchungen zwischen eigenen Konten sind es nicht. Eine Überweisung von einem Konto des
  Kontoinhabers auf ein anderes ist `transfer` — die zählt in keiner Ausgabensumme mit.
- **Kreditkartenabrechnungen sind `transfer`, nicht `misc`.** Eine Belastung „Commerzbank AG Karte
  Nr. …" auf dem Girokonto ist die Sammelbuchung der Karte; die Einzelposten stehen separat im
  Kartenauszug. Als Ausgabe gezählt wäre alles doppelt.
- **`boat` erkennst du an den Lieferanten**, nicht am Wort Boot.
  {_merchants("boat", "Hafenbetriebe, Yachtservice, Segelmacher, Liegeplatz, Winterlager.")}
  Ein vierstelliger Betrag an einen dieser Namen ist fast immer `boat` — in der Messung wurde eine
  solche Zahlung als `misc` eingeordnet, solange die Namen im Prompt fehlten.
- **`ai_stack` ist der PRIVATE Anteil.**
  {_merchants("ai_stack", "Modellanbieter, Hosting, Domains, APIs.")}
  Läuft es über eine Firmenkarte, taucht es hier gar nicht erst auf.
- **`food_out` ist Essengehen und Lieferdienst**, `groceries` der Einkauf. Ein Supermarkt ist
  `groceries`, auch wenn dort ein Kaffee dabei war.
- Die Kategorie, die die Bank mitliefert, ist ein Hinweis und keine Vorgabe. Sie kennt weder das
  Boot noch das KI-Setup.
"""


AGENTS = [
    {
        "file": "finance-categorise.json",
        "name": "Finance · Categorise",
        "description": (
            "Ordnet eine einzelne Buchung aus einem deutschen Kontoauszug einer Kategorie "
            "aus der Finanzplanung des Kontoinhabers zu und nennt den Gegenüber in "
            "lesbarer Form."
        ),
        "instructions": KATEGORISIEREN,
        "model": c.MODELS["categorise"],
        "temperature": 0.0,
        "random_seed": 4711,
        "max_tokens": 1024,
        "model_cls": FinanceCategory,
        "schema_name": "finance_category",
    },
]


def main() -> int:
    target = ROOT / "agents"
    for agent in AGENTS:
        path = target / agent["file"]
        existing = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}

        definition: dict = {}
        if "id" in existing:  # an assigned Studio ID stays untouched
            definition["id"] = existing["id"]

        definition |= {
            "completion_args": {
                "stop": None,
                "presence_penalty": None,
                "frequency_penalty": None,
                "temperature": agent["temperature"],
                "top_p": 1.0,
                "max_tokens": agent["max_tokens"],
                "random_seed": agent.get("random_seed"),
                "prediction": None,
                "tool_choice": "auto",
                "reasoning_effort": None,
                "response_format": response_format(
                    agent["model_cls"],
                    name=agent["schema_name"],
                    title=agent["name"],
                    description=agent["description"],
                ),
            },
            "model": agent["model"],
            "name": agent["name"],
            "instructions": agent["instructions"],
            "handoffs": None,
            "description": agent["description"],
            "tools": [],
            "metadata": {"domain": "finance"},
        }

        path.write_text(
            json.dumps(definition, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"  {agent['file']:28} {'aktualisiert' if existing else 'neu':13} "
              f"({agent['model_cls'].__name__})")

    print(f"\n{len(AGENTS)} Definition(en) geschrieben. Jetzt: cd workflows && make sync-agents-dry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
