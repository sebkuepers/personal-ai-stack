"""BATCH-Workflow — das Stimmprofil eines Werks destillieren.

Der erste Meilenstein der Buch-Domäne und die Grundlage für die Stilebene des
Lektorats.

Ablauf (Map/Reduce):

  1. **Map** — je Abschnitt eine Stimmprobe durch den Agent ``buch-stimme-probe``,
     parallel in begrenzter Breite. Kleiner Kontext, konkrete Beobachtung, jede
     mit wörtlichem Beleg.
  2. **Reduce** — ``buch-stimme-profil`` verdichtet alle Proben zusammen mit den
     gemessenen Kennzahlen und den selbst formulierten Regeln des Autors zu
     höchstens zwölf Regeln.
  3. **Prüfung** — deterministisch in Workflow-Code: jede Regel braucht genügend
     Belege, und jeder Beleg muss wörtlich im Manuskript stehen. Das fängt
     erfundene Zitate, die sonst überzeugend aussehende Regeln tragen würden.

Der Workflow rührt **kein Dateisystem an** — der produktive Worker läuft im
Cloudflare-Container und käme an das Scrivener-Projekt ohnehin nicht heran.
Scrivener lesen, messen und die Notizen auswerten erledigt vorher ``buchcli``;
hier kommt alles fertig als Eingabe an.

Auslösen:
  make buch-stimmprofil werk=immer-wieder-ruegen
"""

from __future__ import annotations

from datetime import date

import mistralai.workflows as workflows
from mistralai.workflows import workflow

# Durch die Sandbox-Grenze: die Aktivitäten (sie sprechen mit dem Mistral-Client)
# UND die Konfiguration. Letzteres ist leicht zu übersehen — ``config`` liest beim
# Import ``shared/buch.json`` und benutzt dafür ``Path(__file__).resolve()``, was
# die Temporal-Sandbox verbietet. Der Zugriff ist deterministisch (einmal beim
# Import, danach nur noch Konstanten), also ist Passthrough hier genau richtig.
with workflow.unsafe.imports_passed_through():
    from workflows.buch import config
    from workflows.buch.agenten import (
        heute,
        probiere_stimme,
        pruefe_profil,
        verdichte_stimme,
    )

# Reine Module (Modelle, Prüflogik) normal importieren.
from workflows.buch.models import (  # noqa: E402
    Korpus,
    StimmProfilRoh,
    Stimmprofil,
    StimmprofilInput,
)
from workflows.buch.models import ProfilPruefung  # noqa: E402
from workflows.buch.stimme import baue_profil  # noqa: E402


@workflows.workflow.define(
    name="buch-stimmprofil",
    workflow_display_name="Buch · Stimmprofil destillieren",
    workflow_description=(
        "Beobachtet die Erzählstimme in allen Abschnitten eines Werks, verdichtet die "
        "Beobachtungen zu höchstens zwölf prüfbaren Regeln und verwirft jede Regel, deren "
        "Belege nicht wörtlich im Manuskript stehen."
    ),
)
class BuchStimmprofilWorkflow:
    @workflows.workflow.entrypoint
    async def run(self, inp: StimmprofilInput) -> Stimmprofil:
        # Schritt 1 — Map. Die Breite ist bewusst begrenzt: 48 gleichzeitige
        # Agent-Aufrufe brächten nichts außer Rate-Limit-Fehlern.
        proben = await workflows.execute_activities_in_parallel(
            probiere_stimme,
            items=[a.model_dump(mode="json") for a in inp.abschnitte],
            max_concurrent_scheduled_tasks=inp.parallel,
        )
        proben = [p for p in (proben or []) if p]

        # Schritt 2 — Reduce.
        roh_dict = await verdichte_stimme(
            proben=proben,
            metrik_text=inp.metrik_text,
            max_regeln=config.MAX_STIMMREGELN,
        )
        roh = StimmProfilRoh.model_validate(roh_dict)

        # Schritt 3 — Belegprüfung, deterministisch im Workflow-Thread.
        heute_iso = await heute()
        profil = baue_profil(
            roh,
            werk=inp.werk,
            korpus_text=inp.korpus_text,
            korpus=Korpus(
                abschnitte=len(inp.abschnitte),
                woerter=inp.woerter,
                kapitel=inp.kapitel,
            ),
            metrik=inp.metrik,
            erstellt_am=date.fromisoformat(heute_iso),
            min_belege=config.MIN_BELEGE,
            max_regeln=config.MAX_STIMMREGELN,
            version=inp.version,
        )

        # Schritt 4 — die Belege gegen ihre Regeln halten.
        #
        # Schritt 3 prüft, ob eine Fundstelle im Manuskript EXISTIERT. Ob sie die
        # Regel ZEIGT, ist ein Urteil und braucht ein Modell. Gemessen am ersten
        # brauchbaren Profil: „Umgangssprache in Sachzusammenhängen" war mit
        # einem Satz ohne jede Umgangssprache belegt.
        #
        # Wer durchfällt, wird nicht verworfen, sondern auf `beobachtung`
        # gesetzt: Die Regel kann richtig und nur der Beleg schief sein. Der
        # Stil-Agent bekommt über `aktive_regeln` nur die bestätigten — er lernt
        # am Beleg, wie die Regel aussieht, und ein schiefer Beleg ist dort
        # schlimmer als eine Regel weniger.
        if profil.regeln and config.AGENTS.get("profil_pruefen"):
            urteil = ProfilPruefung.model_validate(
                await pruefe_profil([r.model_dump(mode="json") for r in profil.regeln])
            )
            schief = {p.regel_id: p.warum for p in urteil.pruefungen if not p.zeigt_die_regel}
            for r in profil.regeln:
                if r.id in schief:
                    r.status = "beobachtung"
            if schief:
                profil.offene_fragen.append(
                    f"{len(schief)} Regel(n) auf 'beobachtung', weil die Fundstelle die Regel "
                    "nicht zeigt: " + "; ".join(f"{k} ({v})" for k, v in schief.items())
                )
        return profil
