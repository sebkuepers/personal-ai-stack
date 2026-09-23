# Buch — Lektorat für eigene Manuskripte

Die zweite Domäne dieses Repos (neben [`CRM.md`](CRM.md)). Sie unterstützt das Schreiben von
Büchern in [Scrivener](https://www.literatureandlatte.com/scrivener/): Manuskript exportieren,
die Erzählstimme des Autors als prüfbares Profil destillieren, und darauf aufbauend lektorieren.

Entstanden für **„Immer wieder Rügen"** (Memoir/Reiseerzählung), aber von Anfang an für mehrere
Werke gebaut.

---

## Die eine Regel, die alles trägt

> **Die Domäne ist die Fähigkeit. Das Werk ist der Gegenstand.**

Agents, Workflows, Skills und Makefile-Ziele heißen `buch-*` und gelten für **jedes** Buch.
Welches gemeint ist, sagt der Parameter `werk=<slug>`:

```bash
make buch-sync werk=immer-wieder-ruegen
make buch-sync werk=autobiographie
```

Deshalb kostet das zweite Buch keine einzige neue Definition — nur eine Konfigurationsdatei.

**Slugs** sind kebab-case, ASCII, klein; Umlaute werden transliteriert (ä→ae, ö→oe, ü→ue, ß→ss).
„Immer wieder Rügen" wird zu `immer-wieder-ruegen`, und derselbe Slug gilt überall: Verzeichnis,
Scrivener-Datei, Werk-Konfiguration, Mistral Library, Arbeitsdaten.

---

## Wo was liegt

### Im Repo

| Pfad | Inhalt |
|---|---|
| `shared/buch.json` | **Domänen-Konfiguration** — Agent-IDs, Modelle, Vokabulare, Judge-Kriterien, Satzspezifikation. Gilt für alle Werke. |
| `shared/buch/<slug>.json` | **Werk-Konfiguration** — Titel, Pfade, Kapitelgerüst, Prüfsteine, Library-ID. *Gitignored*, siehe unten. |
| `shared/buch/werk.example.json` | Anonymisierte Vorlage für eine Werk-Konfiguration. |
| `shared/buch/<slug>-stimme.json` | Das destillierte **Stimmprofil**. *Gitignored.* |
| `agents/buch-*.json` | Die Studio-Agents als Code. Erzeugt von `agents/build_buch_agents.py`, hochgespielt von `agents/sync.py`. |
| `workflows/src/workflows/buch/` | Domänencode: Scrivener-Leser, Kennzahlen, Notizparser, Agent-Aktivitäten, Workflows. |
| `workflows/src/buchcli/` | Lokale Kommandozeilen-Werkzeuge (alles, was Dateien anfasst). |
| `workflows/data/` | Arbeitsdaten — **gitignored**, enthält unveröffentlichten Werktext. |
| `skills/buch-stimme/` | Das Stimmprofil als Agent Skill für Vibe. |

### Auf der Platte (außerhalb des Repos)

```
~/Werk/buch/<slug>/
├── <slug>.scriv        die lebende Quelle — hier wird geschrieben
├── export/             manuskript.json + Markdown (generiert, jederzeit neu baubar)
├── pdf/                gesetzte Manuskript-PDFs
├── kontext/            Kapitelplan und anderes Arbeitsmaterial
├── fotos/              Bildmaterial
├── backup/             Paketkopien vor jedem programmatischen Schreibzugriff
└── test/               Testkopie für Write-back-Versuche
```

**Warum nicht in `~/Documents`:** Dort synchronisiert iCloud Drive. Ein Programm, das in ein live
geöffnetes `.scriv`-Paket schreibt, während ein Sync-Dienst es beobachtet, löst das klassische
Scrivener-Korruptionsszenario aus — der Dienst legt Konfliktkopien **innerhalb** des Pakets an.
Fertige Dateien (ZIPs, PDFs, Exporte) dürfen dagegen synchronisiert werden und sollen es auch.
Scrivener-Auto-Backups liegen deshalb bewusst weiter unter `~/Documents/Scrivener-Backups/`
(der Pfad ist eine **globale** Scrivener-Einstellung und darf nie in einen Werk-Ordner zeigen).

> **Werk-Daten sind nicht im Repo.** Dieses Repo ist öffentlich; die Werk-Konfigurationen und
> Stimmprofile enthalten Kapitelpläne, Prüfsteine, Verlagsstrategisches und wörtliche Belegzitate aus
> unveröffentlichten Manuskripten. Geteilt wird deshalb die **Domäne** — Code, Agents, Doku —, nicht
> das **Werk**. Genau dieselbe Trennung, die auch die Namenskonvention trägt.
>
> Wer das Repo klont, legt sich eine eigene Werk-Konfiguration an:
>
> ```bash
> cp shared/buch/werk.example.json shared/buch/mein-buch.json
> # ausfüllen, dann:
> make buch-sync werk=mein-buch
> ```

---

## Die Arbeitsteilung

> **Lokal lesen und rechnen, in Mistral orchestrieren.**

Alles, was Dateisystem oder Determinismus braucht — Scrivener lesen, Kennzahlen messen, Notizen
auswerten, PDF setzen, zurückschreiben — passiert in `buchcli` auf dem eigenen Rechner. Die
Workflows bekommen fertigen Text als Eingabe und kümmern sich um Agent-Aufrufe, Wiederholungen,
Parallelität und die Ausführungshistorie.

Das ist keine Willkür: Scrivener-Lesen und Kennzahlen-Rechnen sind deterministisch und würden bei
jedem Wiederanlauf eines Workflows erneut durchlaufen. Und ein Workflow, der Dateipfade kennt,
ist an einen Rechner gebunden.

Der **Worker** — der Prozess, der den Workflow-Code ausführt — läuft lokal und meldet sich
ausgehend bei Mistral. Die Orchestrierung, die Historie und die Timeline liegen in Mistrals Cloud.

---

## Bedienung

Voraussetzung: `cd workflows && uv sync`, eine `.env` mit `MISTRAL_API_KEY`, und ein
Scrivener-Projekt unter `~/Werk/buch/<slug>/`.

### 1. Manuskript exportieren

```bash
make buch-sync werk=immer-wieder-ruegen           # → export/manuskript.json + Markdown
make buch-export werk=immer-wieder-ruegen         # zusätzlich in die Mistral Library
```

Der Export wird bei **jedem** Lauf neu gebaut und nie von Hand gepflegt. Er läuft durch den
**Binder** (`.scrivx`), nicht über `Files/Data/` — dort liegen auch *Forschung* und *Papierkorb*,
die nicht zum Manuskript gehören.

### 2. Stimmprofil destillieren

```bash
make start-worker                                  # in einem eigenen Terminal lassen
make buch-stimmprofil-probe                        # Probelauf: 6 Abschnitte, schreibt nichts
make buch-stimmprofil werk=immer-wieder-ruegen     # voller Lauf, legt das Profil ab
```

Erst der Probelauf. Er kostet Minuten statt einer Viertelstunde und zeigt sofort, ob die Regeln
konkret werden oder Schreibratgeber-Prosa herauskommt.

### 3. Prüfen

```bash
uv run ruff check src/workflows src/buchcli
uv run pytest tests/ -q
uv run python -c "from entrypoints.worker import discover_workflows as d; print(len(d()))"
```

Die Discovery-Prüfung importiert nur — sie **validiert nicht**. Ob die Workflows in der
Temporal-Sandbox laufen, zeigt allein ein echter Worker-Start.

---

## Wie das Stimmprofil funktioniert

Die Falle: Fragt man ein Modell „beschreibe die Stimme dieses Autors", bekommt man *„warm,
humorvoll, konkrete Bilder"*. Wahr, nutzlos und vor allem **nicht verletzbar** — eine Regel, gegen
die man nicht verstoßen kann, kann auch keinen Verstoß erkennen.

Vier Mechanismen erzwingen Substanz:

1. **Messen vor Modellieren.** `stilmetrik.py` berechnet rein deterministisch Satzlängen,
   Kurzsatzanteil, Absatzlängen, Dialoganteil, Nominalstil- und Passivquote. Aus „kurze Sätze"
   wird „Median 9 Wörter, 25 % höchstens 5 Wörter, längster im Buch 55".

2. **Die eigenen Notizen des Autors auswerten.** In den `notes.rtf` steckt oft schon Lektorat —
   im Fall von „Immer wieder Rügen" 102 Blöcke mit dem Muster *ÜBERSCHRIFT / VORHER / NACHHER /
   WARUM*. `notizen.py` parst sie; der Reduce-Agent bekommt sie mit dem Auftrag, die Formulierung
   und den Namen des Autors zu übernehmen. Das ist der Grund, warum das Profil nach ihm klingt.

3. **Belegpflicht, in Python durchgesetzt.** Jede Regel braucht mindestens zwei wörtliche Belege,
   und jeder Beleg wird gegen den **Werktext** geprüft. Belegbasis sind Manuskript plus die
   VORHER/NACHHER-Fassungen aus den Notizen — ausdrücklich **nicht** die Kommentartexte, denn ein
   Zitat aus einem Kommentar über das Buch ist kein Beleg aus dem Buch. Regeln, die das verfehlen,
   landen mit Begründung unter `verworfene_regeln`.

4. **Höchstens zwölf Regeln.** Ein Profil mit vierzig Regeln liest niemand und befolgt kein Agent.

Das Ergebnis wird dreifach verwendet: als versionierte JSON (Quelle der Wahrheit), als Skill für
Vibe, und zur **Aufrufzeit** als Kontextblock für den Stil-Agent — bewusst nicht in dessen
Instruktionen eingebacken, sonst müsste bei jeder Profiländerung der Agent neu synchronisiert
werden und beide driften auseinander.

---

## Die Agents

Alle in `agents/buch-*.json`, alle mit erzwungenem `response_format.json_schema`.

| Agent | Rolle |
|---|---|
| `buch-stimme-probe` | Map — beobachtet die Stimme an **einem** Abschnitt, jede Beobachtung mit wörtlichem Beleg |
| `buch-stimme-profil` | Reduce — verdichtet alle Beobachtungen zu höchstens zwölf prüfbaren Regeln |
| `buch-korrektorat` | Ebene 1: Rechtschreibung, Zeichensetzung, Grammatik, Tempus, Typografie. Fasst Stil nicht an |
| `buch-stil` | Ebene 2: macht den Text dem Autor **ähnlicher**, nicht glatter. Muss jede Regel des Stimmprofils zitieren |
| `buch-judge` | Bewertet einen Vorschlag nach einem Kriterium, das als Eingabe kommt — ein Agent für alle Kriterien |

Die JSON-Schemata werden **aus** den Pydantic-Modellen in `buch/models.py` generiert
(`agents/build_buch_agents.py`), mit aufgelösten `$defs`. So können Schema und Modell nicht
auseinanderlaufen. Die Instruktionen stehen dort als lesbare Konstanten.

```bash
uv run --project workflows python agents/build_buch_agents.py   # Definitionen erzeugen
cd workflows && make sync-agents-dry                            # validieren, ohne Studio zu berühren
cd workflows && make sync-agents                                # nach Studio spielen
```

Danach die neuen IDs in `shared/buch.json` unter `agents` eintragen.

**Wichtig:** Workflows *triggern* diese Agents über die Conversations-API. Der Weg über
`Agent(id=…)` + `Runner.run` würde die Definition in Studio mit den übergebenen Feldern
**überschreiben** — das ist der Unterschied zwischen benutzen und kaputtmachen.

---

## Ein neues Werk anlegen

1. Projekt nach `~/Werk/buch/<slug>/<slug>.scriv` legen (außerhalb jeder Synchronisation).
2. `shared/buch/<slug>.json` anlegen — als Vorlage `immer-wieder-ruegen.json` nehmen.
3. `make buch-sync werk=<slug>` und prüfen, ob Kapitel und Abschnitte stimmen.

Weicht die Gliederung ab, hilft der Block `struktur`. Beispiel Autobiographie: Dort liegt im
Entwurf neben dem Manuskript auch Recherche (*Personen*, *Orte*, *Unternehmen*), alles mit
`IncludeInCompile=Yes` — ohne Einschränkung würden diese Ordner als Kapitel gezählt:

```json
"struktur": { "wurzel": "Kapitel", "kapitel_ebene": 0 }
```

---

## Sicherheit beim Schreiben ins Manuskript

Noch nicht gebaut (siehe Stand), aber die Regeln stehen fest und gelten für jeden Schreibzugriff:

1. **Scrivener muss geschlossen sein.** Sonst überschreibt es beim nächsten Speichern alles —
   stiller Datenverlust. Wird per `lsof` geprüft.
2. **Vollständige Paketkopie** nach `backup/` vor dem ersten Schreiben einer Sitzung.
3. **Vierfacher Anker** je Änderung: `(abschnitt_uuid, absatz_index, absatz_sha256, search)`.
   Der Hash wird unmittelbar vor dem Schreiben erneut geprüft; `search` muss **genau einmal** im
   Absatz vorkommen. Bei Abweichung wird abgebrochen und der Abschnitt benannt.
   **Kein Fuzzy-Matching, niemals.**
4. **`--dry-run` ist die Vorgabe**, `--apply` zeigt erst einen Diff.
5. Nach dem Schreiben wird die Datei **neu dekodiert und gegen den erwarteten Text geprüft**;
   bei Abweichung Backup zurückspielen und abbrechen.
6. **Kein Agent editiert das `.scriv` direkt** — geschrieben wird ausschließlich über
   `make buch-anwenden`.

Der RTF-Roundtrip ist durch Tests abgesichert: alle `content.rtf` müssen zeichengleich zu Apples
`textutil` dekodieren, und Kodieren→Dekodieren muss für jeden Absatz die Identität ergeben
(`workflows/tests/test_scrivener_roundtrip.py`).

---

## Stand

**Fertig und erprobt**

- Scrivener-Export über den Binder, mit `synopsis.txt` und `notes.rtf`; zwei Werke im Betrieb
- RTF-Dekodierer und -Kodierer, gegen `textutil` verifiziert, 20 Tests
- Parser für die Lektoratsnotizen des Autors
- Deterministische Stilkennzahlen
- Fünf Studio-Agents, Schemata aus den Modellen generiert
- Workflow `buch-stimmprofil` (Map/Reduce) samt Belegprüfung
- Mistral Library mit dem Manuskriptstand

**Als Nächstes**

- Write-back nach Scrivener (`buch-anwenden`) mit der Disziplin von oben
- Der conversational Workflow `buch-lektorat` für Vibe Work
- PDF-Satz (`buch-pdf`) mit Typst, kalibriert gegen die vorhandenen Referenz-PDFs
- Entscheidungslog → Verfeinerung des Stimmprofils
- Ebene 3 (Inhalt) gegen die Kapitelrubrik

**Bewusst nicht gebaut**

Studio-Judges (`client.beta.observability.*`) sind auf dem Pro-Plan nicht erreichbar — die
Endpunkte antworten mit HTTP 404. Bewertung läuft deshalb über einen eigenen Judge-Agent, hinter
einer Weiche in `buch/judge.py`, damit ein späterer Umstieg lokal bleibt.

---

## Siehe auch

- [`../workflows/CLAUDE.md`](../workflows/CLAUDE.md) — SDK-Konventionen und die Gotchas, die echte
  Zeit gekostet haben (Sandbox-Importe, `Path.resolve`, gehärtete Deployments)
- [`CRM.md`](CRM.md) — die erste Domäne, nach demselben Muster
- [`architecture.md`](architecture.md) — warum das System so geschnitten ist
