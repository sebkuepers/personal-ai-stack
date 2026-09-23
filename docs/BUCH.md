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

Alles Deterministische — Kennzahlen messen, PDF setzen, zurückschreiben — passiert in `buchcli`
auf dem eigenen Rechner. Die Workflows kümmern sich um Agent-Aufrufe, Wiederholungen, Parallelität
und die Ausführungshistorie.

**Eine frühere Fassung dieser Regel war strenger und ist gefallen:** „Kein Workflow fasst das
`.scriv` an." Der Grund dafür war, dass der Worker im Cloudflare-Container laufen sollte, wo
`~/Werk/…` nicht existiert. Der Buch-Worker läuft aber lokal — damit fiel der Grund weg, und mit
ihm eine Einschränkung, die einen echten Preis hatte: Ein Gesprächs-Workflow, der die Kapitelliste
nicht selbst lesen darf, braucht sie als Parameter, und dann kann man ihn in Le Chat nicht ohne
Vorarbeit starten.

Was bleibt, ist die Trennung, auf die es ankommt: **I/O steht in Aktivitäten, nie im
Workflow-Körper.** Der Körper wird bei einer Wiederholung erneut abgespielt; eine Datei, die sich
zwischendurch geändert hat, würde ihn aus der Bahn werfen. Eine Aktivität liest genau einmal, und
ihr Ergebnis steht danach in der Ereignishistorie. Die lesenden Aktivitäten stehen gesammelt in
`buch/lokal.py`.

Geschrieben wird weiterhin nirgends aus einem Workflow heraus.

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

### 3. Lektorieren

Der **Gesprächs-Workflow** ist der eigentliche Arbeitsplatz: in Vibe Work über `+` → Workflows
→ *Buch · Lektorat (im Gespräch)*. Er braucht keine Eingabe und liest Scrivener **live** — ein
`buch-sync` vorher ist nicht nötig. Nur gespeichert muss Scrivener haben; es schreibt die
`content.rtf` erst nach einer Tipppause.

Dieselben Ebenen einzeln im Terminal:

```bash
make buch-lektorat abschnitt="Einführung Strand"        # Ebene 1, headless
make buch-inhalt kapitel="Voll zur Oma"                 # Ebene 3, ein ganzes Kapitel
make buch-uebersicht                                     # Struktur, Dichte, Stand
```

### 4. Setzen

```bash
make buch-pdf kapitel=1-3 vergleich=1     # setzt und hält die Seitenzahl gegen die Referenz
make buch-pdf                             # das ganze Manuskript
```

Braucht `typst` (`brew install typst`). Die Maße stehen in `shared/buch.json` unter `satz.format`
und sind aus dem Referenz-PDF **ausgemessen**: 170 × 245 mm, Satzbreite 126,8 mm, innen 23,6 /
außen 19,5, Palatino 10,9 pt. Erreicht werden 71 Seiten gegen 70 der Referenz.

`trenner_zwischen` ist bewusst eine Einstellung (`alle` · `gruppen` · `keine`): Die Referenz hat
15 Trenner bei 37 möglichen Abschnittsübergängen, ohne erkennbare Regel. Abschnittstitel werden
nicht gesetzt, die Grenzen sind also unsichtbar — das ließ sich nicht ableiten, nur entscheiden.

### 5. Prüfen

```bash
uv run ruff check src/workflows src/buchcli src/evalkit
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

2. **Nur das Manuskript, nichts sonst.** Die Lektoratsnotizen des Autors (`notes.rtf`) flossen
   einmal mit **Vorrang** in den Reduce-Schritt — und prompt kamen 9 von 10 Regeln aus ihnen statt
   aus dem Text. Das ist kein Stimmprofil: Die Notizen sagen, was der Autor an einzelnen Stellen
   korrigiert hat, nicht, wie er schreibt. Sie sind draußen.

3. **Jede Regel beschreibt, was der Autor TUT — niemals ein Verbot.** Der zwingende Grund: Der
   Agent sieht nur den fertigen Text. Darin stehen keine Verstöße gegen ein Verbot, also lässt
   sich ein Verbot nicht belegen. Ein Lauf ohne diese Vorgabe lieferte 8 von 12 Regeln als Verbote,
   und **jede** Fundstelle zeigte einen Satz, der das Verbot einhält — zirkulär und wertlos. Eine
   dieser Regeln lautete „Vermeidet elliptische Sätze"; elliptische Sätze sind die Handschrift
   dieses Autors. Was er nicht tut, steht unter `vermeidungen`, wo kein Beleg verlangt wird.

4. **Belegpflicht, in Python durchgesetzt.** Der Reduce-Agent bekommt einen **nummerierten
   Satzkatalog** aus dem Map-Schritt und wählt daraus, statt Zitate abzutippen. Vorher tat er
   Letzteres und paraphrasierte dabei: 10 von 12 Regeln fielen durch die Belegprüfung, weil ihre
   „wörtlichen" Fundstellen so nicht im Manuskript standen. Der Auflöser nimmt Nummer **oder**
   Wortlaut — `strict: true` erzwingt Enums, aber keine Zahlentypen, und das Modell schreibt
   trotzdem Sätze. Was im Katalog nicht steht, fällt raus.

5. **Höchstens zwölf Regeln.** Ein Profil mit vierzig Regeln liest niemand und befolgt kein Agent.

6. **Die Belege gegen ihre Regeln halten.** Punkt 4 prüft, ob eine Fundstelle im Manuskript
   *existiert* — nicht, ob sie die Regel *zeigt*. Genau das ging schief: „Direkte Rede ohne
   Einleitung" war mit einem Satz ohne jede direkte Rede belegt, „Kurze Sätze (≤5 Wörter)" mit
   einem Satz aus zwölf. Für den Stil-Agenten ist das schlimmer als eine Regel weniger, denn er
   lernt am Beleg, wie die Regel aussieht. `buch-profil-pruefen` hält jede Regel gegen ihre erste
   Fundstelle; wer durchfällt, geht auf `status="beobachtung"` und erreicht den Stil-Agenten nicht
   mehr. Am echten Profil gemessen: 7 von 10 sauber.

Die Felder heißen nach ihrem Inhalt: `fundstellen` (Stellen, an denen man die Regel sieht) und
`so_geht_es` (dieselbe Stelle, wie sie von jemand anderem klänge). Eine frühere Fassung hieß
`beweis` und `gegenbeispiel` — und enthielt das Gegenteil dessen, was die Namen versprachen. Der
Stil-Agent las daraus, der Autor schreibe bürosprachlich, und schlug prompt Bürosprache vor.

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
| `buch-gegenlesen` | Zweites Augenpaar über Ebene 1: sieht denselben Abschnitt wie Stufe 1 plus deren Befunde und meldet, was fehlt und was keiner ist |
| `buch-stil-gegenlesen` | Zweites Augenpaar über Ebene 2: prüft je Vorschlag, ob er hält, was seine Regel verspricht — `traegt`, `verdreht_die_regel`, `kein_verstoss`, `greift_zu_weit` |
| `buch-inhalt` | Ebene 3: prüft ein ganzes **Kapitel** gegen die Rubrik des Autors. Ändert nichts, stellt Fragen |
| `buch-profil-pruefen` | Hält jede Stimmprofil-Regel gegen ihre Fundstelle: Zeigt der Satz, was die Regel behauptet? |

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

### Das Vier-Augen-Prinzip — und wie ich es zuerst falsch gebaut habe

Ebene 1 läuft in zwei Stufen: `buch-korrektorat` findet, `buch-gegenlesen` liest gegen. Der zweite
Agent bekommt **denselben Abschnitt** wie der erste, dazu dessen Befundliste, und beantwortet zwei
Fragen:

1. **Fehlt etwas?** Steht im Text ein Fehler, der nicht in der Liste auftaucht?
2. **Stimmt, was dasteht?** Ist einer der gemeldeten Befunde keiner?

Er läuft **immer** — gerade die leere Befundliste ist der Fall, den sonst niemand prüft.

**Der Vorgänger war ein Judge, der je Befund lief und nur `search` und `replace` bekam.** Also einen
Schnipsel ohne den Satz, in dem er steht. Zwei Dinge konnte er deshalb nicht: beurteilen, ob ein
Fehler wirklich behoben wird, und bemerken, dass einer fehlt. Das zweite war der schwerere Mangel —
bei null Befunden lief er gar nicht erst an, ein übersehener Fehler war unsichtbar. Ein Prüfer, der
nur die Vorschläge des Ersten sieht, prüft nicht dessen Arbeit, sondern nur dessen Wortwahl.

Der Fehler kam daher, dass ich vom Schreibpfad her gedacht habe („was darf ins Manuskript?" ist eine
Frage pro Vorschlag) statt vom Vier-Augen-Prinzip. Mistrals eingebauter Judge macht es übrigens
richtig: Er bewertet eine Antwort **im Kontext ihrer Anfrage**, sieht also den vollständigen Trace.

```bash
make eval agent=buch-gegenlesen faelle=shared/buch/eval-gegenlesen.json zaehlpfad="uebersehen[]"
```

Die sieben Fälle sind konstruiert und liegen deshalb im Repo. Sie decken die vier Betriebsarten ab —
sauberer Text mit leerer Liste, Fehler korrekt gefunden, Fehler übersehen, Befund erfunden — plus
zwei Werkkontext-Fälle und **G-verankerung**: Der Fehler steht noch im Text, aber die erste Stufe hat
Befunde geliefert, die ihn nicht beheben. Beobachtet mit `medium`: Der Zweite hielt die Stelle dann
für erledigt. Verankerung durch die Liste des Ersten ist die eigentliche Schwäche des Prinzips.

### Zwei Stufen, zwei Modelle — mit Absicht

| Stufe | Modell | Gemessen |
|---|---|---|
| `buch-korrektorat` | `mistral-medium-latest` | 21/21 Treffer, 6/63 Fallen, 1,0s, 2.420T |
| `buch-gegenlesen` | **`mistral-large-latest`** | **16/16 Treffer, 0/26 Fallen**, 3,2s, 1.878T |

`large` ist hier kein Luxus: Es schlägt `medium` (10/12) und `zai-glm-5` (11/12, 2 Fallen, fünffache
Tokenzahl) und ist als einziges Modell gegen die Verankerung immun.

Dass die Stufen **verschiedene** Modelle nutzen, ist zusätzlich Absicht. Die Forschung zu
*self-preference bias* ist eindeutig: Ein Judge aus derselben Familie wie der Generator bewertet
dessen Ausgaben systematisch zu gut und teilt seine blinden Flecken. Empfohlen wird ein Judge von
einem **anderen Anbieter** — das steht als langfristige Verbesserung auf der Liste; vorerst genügt
der Abstand zwischen `medium` und `large`. Mistrals eigene Doku sagt zur Modellwahl für Judges
nichts; ihre Best Practices betreffen nur die Instructions (spezifisch sein, Testbarkeit,
Grenzbeispiele).

Nebenbefund: `magistral-medium` liefert praktisch identische Zahlen wie `mistral-medium` — Magistral
steckt inzwischen als `reasoning_effort` in medium/small und ist als eigenes Modell überholt.

### Die Rückkopplungsschleife — gebaut, gemessen, entfernt

Die Idee: Abgelehnte Befunde gehen an den Agent zurück, er darf zurückziehen, enger fassen oder
begründet verteidigen. **Gemessen hat sie geschadet** — 0 Befunde ohne, 6 unsinnige mit. Der Agent
nahm „enger fassen" wörtlich und reduzierte seine Vorschläge bis zur Sinnlosigkeit, statt sie
zurückzuziehen.

Der entscheidende Einwand kam aber woanders her: Eine Schleife feuert nur nach einer Ablehnung.
Dass sie überhaupt anlief, hieß, dass in Runde 1 schon etwas kaputt war. Ich hatte das Symptom
behandelt und die Ursache nie auseinandergehalten. Mit dem Gegenlesen gibt es keine zweite Runde
mehr: Was es verwirft, ist verworfen; was es findet, kommt hinzu.

**Warum kein `handoff`.** Mistral kennt Handoffs, aber dort entscheidet der *Agent*, ob er abgibt.
Für Arbeitsteilung ist das richtig, für ein QA-Gate falsch: keine feste Reihenfolge, kein Zugriff
auf die Zwischenstände. Kontrollstruktur gehört in den deterministischen Teil.

### Der Test, der zuerst hätte kommen müssen

Alle konstruierten Fälle enthielten einen eingebauten Fehler. Dein echter Text ist mehrfach
überarbeitet und meistens sauber — der **häufigste** Fall in der Arbeit, und der letzte, den ich
getestet habe. Er sah so aus:

| Lauf auf `Einführung Strand` (6 Absätze, 278 Wörter) | Befunde | davon brauchbar |
|---|---|---|
| vorher | 2–3 je Lauf, bei jedem Lauf andere | 0 |
| nachher | **0 · 0 · 0** | — |

Darunter war `„auskramen, die" → „auskramen die"` — die Entfernung eines **korrekten** Kommas vor
einem Relativsatz. Der gefährlichste Befundtyp: sieht aus wie Zeichensetzung, macht den Text kaputt.

Die Ursache saß im Auftrag, nicht im Modell. Ein Agent, dem man sagt „finde Fehler", liefert auf
einem sauberen Text eben etwas. Drei Zusätze im Prompt haben es behoben:

1. **Die Erwartung umdrehen.** Gleich im ersten Absatz: Der Text ist meistens schon überarbeitet,
   die leere Liste ist das häufigste richtige Ergebnis, und jeder Befund kostet den Autor Prüfzeit.
2. **„Optional" ist disqualifizierend.** Enthält die eigene Begründung „optional", „besser",
   „schöner", „stärker" — dann ist es Geschmack, kein Fehler. Ein Befund im echten Lauf hatte sich
   selbst als „optional, aber typografisch korrekt" bezeichnet.
3. **Begründung muss zur Änderung passen.** Steht da „muss großgeschrieben werden", muss die
   Änderung eine Großschreibung sein. Passt es nicht zusammen, hat sich das Modell verrannt.

Nachgemessen, damit es nicht bloß still geworden ist:

| | |
|---|---|
| Fehler in den echten Abschnitt gepflanzt (Komma vor `dass` entfernt) | **3/3 gefunden** |
| Eval mit Erwartungen | 19/21 statt 21/21 — findet vorsichtiger |
| Fallenquote | **3/63 statt 6/63** |

Die drei echten Fehlbefunde liegen jetzt als Fälle `H`, `I` und `J` in `eval-gegenlesen.json`.

### Kein Chunking auf Absatzebene

Gemessen an einem Abschnitt aus sechs Absätzen mit bekanntem Fehlerinventar:

| | Pflichtfunde | Fallen | Aufrufe | Zeit | Tokens |
|---|---|---|---|---|---|
| **ganzer Abschnitt** | **4/4 · 4/4** | **0** | **1** | **3,0s** | **381** |
| Absatz für Absatz | 4/4 · 3/4 | 2× Leerlauf | 6 | 6,1s | 473 |

Gleich gut im Finden, aber jeder Einzelaufruf hat einen eigenen Drang, etwas zu liefern. Für Ebene 2
bleibt die Frage offen — Rhythmus und Wiederholung sind absatzübergreifend.

Was **keine** der beiden Betriebsarten fand: dieselbe Sache in Absatz 2 und 5 unterschiedlich
geschrieben. Konsistenz über den Abschnitt hinweg prüft bisher niemand.

### Ebene 2 — eine Beschreibung ist keine Vorschrift

Der teuerste Fehler dieses Projekts, weil ich ihn selbst erzeugt habe. Als das Stimmprofil von
Verboten auf Beschreibungen umgestellt wurde — richtig —, las der Stil-Agent die Beschreibung als
Vorschrift:

```
Profil:  „Nutzt elliptische Sätze für Tempo"
Agent:   macht aus vollständigen Sätzen Ellipsen

Profil:  „Lässt direkte Rede oft ohne Begleitsatz"
Agent:   entfernt alle Redebegleiter

Profil:  „Verwendet Umgangssprache"
Agent:   ersetzt ein Wort durch ein umgangssprachlicheres
```

Sieben Vorschläge auf einem Abschnitt, fast alle so. Die Heilung der einen Seite hatte die andere
gebrochen.

Zwei Änderungen, beide gegen `eval-stil.json` gemessen (sieben Fälle aus echten Fehlvorschlägen,
mit synthetischem Profil und synthetischem Text, deshalb im Repo):

1. **Der Prompt sucht Abweichungen statt Anwendungsgelegenheiten.** Die Prüffrage je Vorschlag
   lautet: *Klingt die Stelle, SO WIE SIE DASTEHT, nach einem anderen Autor?* Nicht: Könnte sie
   noch mehr nach ihm klingen? Fallenquote 62 % → 42 %.

2. **`buch-stil-gegenlesen`** mit vier Urteilen, benannt nach den echten Fehlerarten: `traegt`,
   `verdreht_die_regel`, `kein_verstoss`, `greift_zu_weit`.

Es fragt bewusst **nicht**, ob etwas fehlt — anders als bei Ebene 1. Ein übersehener Stilbruch
kostet nichts; ein aufgedrängter Vorschlag kostet den Autor seine Stimme. Das ist kein
symmetrischer Tausch, und die Prüfung muss das abbilden.

Über beide Stufen: von zehn Vorschlägen fielen fünf zu Recht durch, die drei zum echten Stimmbruch
blieben stehen. Live auf einem echten Abschnitt: sieben Vorschläge vorher, einer nachher.

### Ebene 3 — die Rubrik des Autors als Maßstab

`buch-inhalt` prüft ein ganzes **Kapitel** gegen drei Maßstäbe, absteigend verbindlich: die
Kapitelrubrik aus `shared/buch/<slug>.json` (`beweist`, `muss_tragen`, `muss_nicht_tragen`,
Register, Historie-Budget), die zwei Prüfsteine des Werks, und das Exposé aus `kontext/expose.md`.

Das Exposé steht zuletzt und wird ausdrücklich als **Absicht** gekennzeichnet: Es beschreibt das
Buch, wie es Verlagen angeboten wird, nicht wie das Manuskript ist. Wer beides verwechselt, hält
jede Abweichung für einen Fehler.

Diese Ebene ändert nichts — kein `search`, kein `replace`, nirgends im Schema. Die Antwort auf ein
inhaltliches Problem ist Schreiben, nicht Ersetzen.

**Was dabei zu lernen war: Pflicht gehört ins Schema, nicht in die Prosa.** `pruefsteine` und
`traegt` blieben zweimal leer — auch nach einer ausdrücklichen Anweisung im Prompt und mit
verdoppeltem Token-Budget. Der Grund war ein `default_factory=list` am Pydantic-Feld: Damit steht
es nicht unter `required`, und dann lässt das Modell es weg. Das Entfernen des Standardwerts hat es
sofort behoben.

### Fremdmodelle: GLM 5.3 gemessen, nicht geglaubt

Die veröffentlichten GLM-Benchmarks (Terminal Bench, SWE-Marathon, Toolathlon) zeigen deutliche
Vorsprünge — aber sie messen agentisches Arbeiten mit Werkzeugen. Unsere Aufgabe ist strukturierte
Ausgabe auf deutschem Prosatext. Deshalb gemessen, am 23.09.2026, drei Läufe je Stufe:

| | Treffer | Fallen | Zeit | Tokens |
|---|---|---|---|---|
| **Korrektorat** medium/none | **18/21** | 2/63 | **1,0 s** | **2.083** |
| glm-5-3/max | 17/21 | **0/63** | 6,4 s | 17.515 |
| **Gegenlesen** large/none | **30/30** | 1/51 | **2,4 s** | **3.847** |
| glm-5-3/max | 29/30 | 3/51 | 8,0 s | 37.471 |

Der Ausschlussgrund ist nicht die Qualität — die liegt dicht beieinander — sondern dass GLM in
etwa einem von 30 Aufrufen **ungültiges JSON** liefert, abgeschnitten oder leer, auch mit 12.000
Token Budget. In einer Kette ist das ein fehlgeschlagener Workflow.

Ein Nebenbefund, der beim Vergleichen fast alles entschieden hätte: Mit dem ursprünglichen Budget
von 4.000 Tokens brachen GLM-Antworten mitten im JSON ab und zählten als Modellfehler. Das sah wie
ein Qualitätsproblem aus und war ein Budgetfehler. **Wer Modelle vergleicht, muss ihnen denselben
Platz geben.**

Die Reasoning-Stufen sind modellabhängig: Mistral kennt `none|high` (alles andere HTTP 400), GLM 5.3
`low|high|max`. In `evalkit` über `--modelle modell:stufe` wählbar.

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

**Fertig und gemessen**

- Scrivener-Export über den Binder, mit `synopsis.txt`, `notes.rtf`, **Etikett und Status**;
  zwei Werke im Betrieb
- RTF-Dekodierer und -Kodierer, gegen `textutil` verifiziert, 20 Tests
- Deterministische Stilkennzahlen
- Sieben Studio-Agents, Schemata aus den Modellen generiert
- `buch-stimmprofil` (Map/Reduce) mit Satzkatalog und Belegprüfung — 12 beschreibende Regeln
- `buch-korrektorat` (Ebene 1) mit Vier-Augen-Prinzip · 18/21 Treffer, 2/63 Fallen;
  Gegenlesen 30/30, 1/51
- `buch-stil` (Ebene 2) mit eigenem Gegenlesen · 8 von 10 Urteilen richtig
- `buch-inhalt` (Ebene 3) gegen die Kapitelrubrik · Prüfsteine und `muss_tragen` je Punkt belegt
- `buch-lektorat` — der Gesprächs-Workflow für Vibe Work
- `buch-uebersicht` — Struktur, Dichte, Stand; rein deterministisch
- `buch-pdf` — Typst-Satz, kalibriert auf 71 Seiten gegen 70 der Referenz
- Mistral Library mit Manuskript, Exposé und Kapitelplan

**Als Nächstes**

- **Write-back nach Scrivener** (`buch-anwenden`) mit der Disziplin von unten. Das einzige Stück,
  das schreibt, und bewusst das letzte.
- Entscheidungslog → Verfeinerung des Stimmprofils über die Annahmequote je Regel

**Langfristige Verbesserungen**

- **Gegenlesen über einen fremden Anbieter.** Die Forschung zu *self-preference bias* empfiehlt
  ausdrücklich einen Prüfer von einem anderen Anbieter, nicht nur ein anderes Modell derselben
  Familie. GLM 5.3 wurde am 23.09.2026 über beide Evals gemessen und verliert — nicht an der
  Qualität (die liegt dicht beieinander), sondern daran, dass es in etwa einem von 30 Aufrufen
  ungültiges JSON liefert. Ein Pluspunkt bleibt notiert: null Fallen im Korrektorat, es ist
  vorsichtiger. Neu messen, wenn die Eval-Sätze größer sind oder Z.ai die JSON-Treue verbessert.
- **Konsistenz über den Abschnitt hinweg.** Dieselbe Sache in Absatz 2 und 5 unterschiedlich
  geschrieben findet derzeit keine Stufe. Das ist deterministisch prüfbar (Wortformen vergleichen,
  Eigennamen sammeln) und braucht kein Modell.
- **Abschnittstrenner aus der Referenz ableiten.** Derzeit eine Einstellung, weil das gesetzte PDF
  keine erkennbare Regel zeigt. Ein Abgleich Seite für Seite mit dem Binder könnte sie finden.

**Bewusst nicht gebaut**

Studio-Judges (`client.beta.observability.*`) sind auf dem Pro-Plan nicht erreichbar — die
Endpunkte antworten mit HTTP 404. Das Gegenlesen läuft deshalb als eigener Agent. Ein späterer
Umstieg bliebe klein: Mistrals Judge bewertet eine Antwort im Kontext ihrer Anfrage, bekommt also
wie `buch-gegenlesen` den vollen Zusammenhang; die Kriterien stehen als versionierter Text in
`agents/build_buch_agents.py` und müssten nur registriert werden.

Ein **Korrektheits-Judge** für Ebene 1 und ein **Gesamtqualitäts-Score** stehen ebenfalls nicht
hier: Ein zweites Modell über deutsche Kommas urteilen zu lassen kostet und rauscht, und ein
Gesamtscore ist unfalsifizierbar.

---

## Siehe auch

- [`../workflows/CLAUDE.md`](../workflows/CLAUDE.md) — SDK-Konventionen und die Gotchas, die echte
  Zeit gekostet haben (Sandbox-Importe, `Path.resolve`, gehärtete Deployments)
- [`CRM.md`](CRM.md) — die erste Domäne, nach demselben Muster
- [`architecture.md`](architecture.md) — warum das System so geschnitten ist
