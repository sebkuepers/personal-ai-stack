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
| `skills/buch-stimme/SKILL.md` | Der Skill für Vibe. Werkinhalt wird beim Sync eingebettet, siehe unten. |
| `prompts/*.md` | Wiederkehrende Sparring-Fragen ans Buch, mit Variablen. |
| `workflows/src/workflows/buch/` | Domänencode: Scrivener-Leser, Kennzahlen, Notizparser, Agent-Aktivitäten, Workflows. |
| `workflows/src/buchcli/` | Lokale Kommandozeilen-Werkzeuge (alles, was Dateien anfasst). |
| `workflows/data/` | Arbeitsdaten — **gitignored**, enthält unveröffentlichten Werktext. |

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

Das Ergebnis wird zweifach verwendet: als versionierte JSON (Quelle der Wahrheit) und zur
**Aufrufzeit** als Kontextblock für den Stil-Agent — bewusst nicht in dessen
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

## Skills und Prompts — für die Arbeit *mit* Mistral

Drei Dinge lassen sich aus dem Repo nach Studio spielen, alle nach demselben Muster
(`--dry-run` prüft, ohne Studio zu berühren):

```bash
uv run --project workflows python agents/sync.py     # Agents
uv run --project workflows python skills/sync.py     # Skills
uv run --project workflows python prompts/sync.py    # Prompts
```

Damit ist alles im Git versioniert **und** im Studio-UI sichtbar.

### Was Skills und Prompts *nicht* können — gegen den ersten Eindruck

Die Oberfläche legt beides nahe („Lehre Agenten wiederverwendbare Skills…", „…um Modellen aus Apps,
Agenten oder API-Aufrufen zu geben"). Am 23.09.2026 gegen die laufende API geprüft, mit
Kontrollversuch:

| Endpunkt | Kontrolle (erfundenes Feld) | `prompt_id` / `prompt` / `prompts` | `skills` / `skill_ids` |
|---|---|---|---|
| `/v1/chat/completions` | 422 `extra_forbidden` | 422 `extra_forbidden` | — |
| `/v1/conversations` (Basisaufruf: **200**) | 422 `extra_forbidden` | 422 `extra_forbidden` | — |
| `/v1/agents` | 422 `extra_forbidden` | 422 `extra_forbidden` | 422 `extra_forbidden` |

**Der Kontrollversuch ist der Kern des Tests:** Die API validiert serverseitig mit `extra="forbid"`
und lehnt unbekannte Felder ab, statt sie zu ignorieren. Erst dadurch ist ein 422 auf ein
Kandidatenfeld ein Beweis und keine Vermutung. Bei `/v1/conversations` wurde zusätzlich erst ein
Basisaufruf abgesetzt, der tatsächlich 200 liefert — sonst wäre das anschließende 422 wertlos.

Ergänzend: `beta.prompts` bietet ausschließlich `create`, `get`, `list`, `delete`, `create_version`,
`get_version`, `list_versions`, `update_metadata` — reines CRUD samt Versionierung, kein `render`
oder `apply`. Und die erlaubten Tool-Typen eines Agents sind `code_interpreter`, `connector`,
`document_library`, `function`, `image_generation`, `web_search`.

**Daraus folgt:**

* **Skills** gelten für Vibe Work, Vibe Code und Projekte — nicht für Workflow-Agents. Der
  Stil-Agent bekommt sein Stimmprofil deshalb zur Laufzeit in den Prompt gerendert.
* **Prompts** sind eine versionierte Textbibliothek für den Chat, keine Laufzeit-Indirektion. Die
  Aufzählung in der UI beschreibt, *wo du den Text verwendest*, nicht dass die API ihn auflöst.
  Agent-Instruktionen gehören deshalb an den Agent.
* Falls doch einmal ein Prompt programmatisch gebraucht wird: `get()` nimmt neben `prompt_id` auch
  `alias` und `version`. Ein stabiler Alias plus Weiterentwicklung der Versionen wäre der saubere
  Weg — der Text muss dann aber selbst in die Anfrage eingesetzt werden.

### Werkinhalt bleibt draußen

Ein Skill in Studio muss selbsttragend sein — Vibe kommt nicht an lokale Dateien. Damit trotzdem
kein Werkinhalt ins öffentliche Repo gerät, kennen beide Syncs einen Platzhalter:

```markdown
<!-- einbetten: shared/buch/immer-wieder-ruegen-stimme.md -->
```

Der Inhalt wird **beim Sync** eingesetzt. Im Repo steht nur das Gerüst, in Studio landet die
vollständige Fassung. Die eingebetteten Dateien (`*-stimme.md`, `*-kontext.md`) erzeugt
`make buch-sync` bzw. `make buch-stimmprofil` und sind gitignored.

## Messen statt raten

`evalkit/` ist **domänenunabhängig** und liegt deshalb neben `workflows/`, nicht darin. Jeder Agent
im Repo wirft dieselbe Frage auf: Liefert er das Richtige, und woran merkt man eine
Verschlechterung?

```bash
make buch-eval-faelle          # Testfälle aus dem Manuskript bauen
make buch-eval                 # alle Konfigurationen vergleichen
make buch-eval nur=small/none  # eine einzelne
make eval agent=<name> faelle=<pfad>   # beliebiger Agent, beliebige Fälle
```

Ein Fall hat zwei Listen, und die zweite ist die wertvollere:

* **erwartet** — muss gefunden werden. Ergibt die *Trefferquote*.
* **verboten** — darf nicht gemeldet werden. Ergibt die *Fallenquote*.

Ein Agent, der alles meldet, hat perfekte Trefferquote und ist wertlos; einer, der nichts meldet,
tappt in keine Falle und ist genauso wertlos. Erst beide Zahlen zusammen sagen etwas.

Die Fallen werden beim Erzeugen automatisch gesetzt (aus der Liste geschützter Umgangssprache in
`shared/buch.json`), die **Erwartungen bewusst nicht**: Welche Stelle ein echter Fehler ist und
welche Stimme, kann nur der Autor entscheiden. Geratene Erwartungen wären schlimmer als keine, weil
sie eine Messung vortäuschen.

### Warum das mehr wert ist als der nächste Filter

Nach dem ersten echten Lauf war die Versuchung groß, für jedes Fehlverhalten einen deterministischen
Filter nachzuschieben. Das ergibt eine Sammlung von Workarounds, die über den nächsten, noch
unbekannten Fehler nichts sagt. Die Messung zeigte stattdessen, dass die **Modellwahl** das Problem
löste:

| Konfiguration | Fallen | Zeit/Fall | Tokens |
|---|---|---|---|
| **small/none** | **0/12** | **4,9s** | **5.599** |
| small/high | 0/12 | 13,7s | 13.955 |
| medium/none *(vorher eingestellt)* | 1/12 ✗ | 8,6s | 8.660 |
| medium/high | 0/12 | 48,0s | 6 Timeouts |

Reasoning (`reasoning_effort`) kennen beide Modelle nur als `none` oder `high` — `low`/`medium`
werden mit HTTP 400 abgelehnt. Bei `high` verbraucht das Modell leicht 2.000 Tokens, bevor die
eigentliche Antwort beginnt; ist `max_tokens` zu knapp, kommt eine abgeschnittene Antwort zurück,
die wie ein Modellfehler aussieht, aber ein Budgetfehler ist.

**Die Filter bleiben trotzdem** — aber nur die, die *Invarianten* prüfen: Absatz-Index, Nicht-Befunde,
Eindeutigkeit des Suchtexts. Das sind billige, absolute Prüfungen ohne Ermessen. Inhaltliche Urteile
gehören in die Modellwahl und in den Judge, nicht in eine Wortliste.

### Der Judge-Loop — gebaut, gemessen, abgeschaltet

Die Idee: Ein Judge, der nur sperrt, wirft auch brauchbare Befunde weg, bloß weil sie zu weit
gefasst waren. Also geht das Urteil an den Agent zurück (`append_conversation` auf dieselbe
Conversation, deshalb `store=True`), und er darf zurückziehen, enger fassen oder begründet
verteidigen.

**Gemessen hat er geschadet.** A/B am selben Abschnitt:

| | Befunde | Qualität |
|---|---|---|
| `runden=1` (nur sperren) | 0 | sauber — alles von den Invarianten abgefangen |
| `runden=2` (mit Rückkopplung) | 6 | alle unsinnig (`runter.` → `runter`), alle mit Treue 5/5 |

Der Agent nimmt „enger fassen" wörtlich und minimiert seinen Vorschlag bis zur Sinnlosigkeit:
Statt ihn zurückzuziehen, reduziert er ihn auf das Entfernen eines Satzzeichens. Formal eine
kleinere Änderung, inhaltlich Unfug. Dabei versagen zwei Sicherungen gleichzeitig —
`verwerfe_nichtbefunde` greift nicht, weil eine Änderung ja stattfindet, und der Treue-Judge gibt
5/5, weil sich die Bedeutung nicht ändert. **Er prüft Treue, nicht Sinn.**

Deshalb steht `max_runden` auf **1**. Der Code bleibt, die Mechanik ist erprobt und in Studio
sichtbar — aber eingeschaltet wird er erst wieder, wenn zwei Dinge erledigt sind: die Optionen in
der Rückmeldung umgedreht (Zurückziehen zuerst und ausdrücklich bevorzugt), und ein Eval mit
annotierten **Erwartungen**, das zeigt, dass es hilft. Eine reine Fallenmessung hätte diesen Schaden
nicht gesehen.

**Warum kein `handoff`.** Mistral kennt Handoffs, aber dort entscheidet der *Agent*, ob und wann er
abgibt. Für Arbeitsteilung ist das richtig („das ist eigentlich ein Stilproblem, übernimm du"), für
ein QA-Gate falsch: keine Schleifenbegrenzung, keine feste Schwelle, kein Zugriff auf die
Zwischenstände. Kontrollstruktur gehört in den deterministischen Teil.

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
