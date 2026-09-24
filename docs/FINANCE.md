# Finance — private finances, on this machine

The repo's fourth domain (next to [`CRM.md`](CRM.md), [`BOOK.md`](BOOK.md) and
[`INBOX.md`](INBOX.md)). It reads bank statements and a depot export, categorises every booking,
compares the result against the owner's own planning workbook, and writes three summaries into the
Mistral Library so Vibe can be asked about it.

> **A note on language.** Identifiers, module names, config keys and this documentation are English.
> German stays where the *material* is German: the agent instructions (they read German bank
> statements), the category labels and the rows they map to (quotations from his workbook), the CLI
> output and everything he reads.

> **And on the split.** This domain runs **locally only** — no Cloudflare container, no deployment
> gating, no schedule. The worker on this machine may therefore read the file system from inside an
> activity, the exception [`BOOK.md`](BOOK.md) argues for. Writing still happens only in
> `financecli`, never in a workflow.

---

## What was actually there

Measured on 2026-09-24, before anything was built:

| | |
|---|---|
| Bank statements | 4 CSVs, **669 bookings**, 02.01.–13.04.2026, ~290 distinct texts |
| Accounts | Commerzbank Giro · 2× Mastercard · bunq Haushaltskasse |
| Depot | 19 positions, 4.891,40 € — exported the same day |
| His planning workbook | `finanzen_privat_project55.xlsx`, sheet *Ausgaben*, last changed 22.07.2026 |
| His boat workbook | `Telsche_Ausgaben.xlsx`, 7 sheets, 39 invoices, last changed 27.07.2026 |
| Spread over | 7 places, the most important one on the Desktop with an Excel lock file beside it |

**The categories were not invented here.** His workbook already names them — Miete, Wasser, Gas,
Autos, Max & Paul, Essengehen, Haushaltskasse — plus fifteen subscriptions one by one, a savings
rate and an emergency-fund target. `shared/finance.json` says for each category which of his rows it
stands for, and a test holds that claim. Only two categories are additions: `boat` and `ai_stack`,
because they run across his rows and he asked to see them separately.

---

## Where things live

| Path | Content |
|---|---|
| `shared/finance.json` | **Domain configuration** — categories with their derivation, models with the numbers that justify them, tidy rules, library settings. Checked in; contains no path under `~/Documents` and no IBAN fragment, enforced by test. |
| `shared/finance/paths.json` | **Machine-local** — where the statements live, which accounts exist, which workbooks are read. Gitignored; `paths.example.json` is the template. |
| `shared/finance/eval-categorise.json` | The constructed eval cases. In the repo because every merchant and amount is invented. |
| `agents/finance-categorise.json` | The Studio agent, **generated** by `agents/build_finance_agents.py`. |
| `workflows/src/workflows/finance/` | Domain code: parser, ledger, planning reader, report, renderer, library. |
| `workflows/src/financecli/` | Everything that touches the file system. |
| `workflows/data/finance/` | The ledger and the move log. Gitignored. |
| `~/Documents/02_PRIVATE/Finance/` | His files. Never in the repo, never in the library. |

---

## What may leave the machine

Two things cannot stay local, and saying so is part of the design: the model runs at Mistral, and
Vibe only knows what is in the library. So the line is not local against cloud but **raw data
against aggregates**:

| | stays local | goes up |
|---|---|---|
| Statements, invoices, depot export, his workbooks | always | never |
| IBANs, card numbers, balances | always | never |
| The full ledger | `workflows/data/finance/` | never |
| One booking text + amount, for categorisation | — | transient, `store=False` |
| Category totals, subscriptions, depot positions | — | library |

Merchant names have to go up — "how much on Lotto?" cannot be answered without the word Lotto24.
Account identifiers do not, and `library.check` refuses them at the one door out: IBAN, card number,
masked card number. An ISIN is explicitly allowed, because it looks like an IBAN and the portfolio
section is impossible without it. A test runs the real renderers through that check.

`library.enabled` turns all of it off in one line; the local report and the workbook keep working.

---

## The three library documents

| Document | Content | Rebuilt |
|---|---|---|
| `finance-overview.md` | The standing frame from his workbook: plan, 15 subscriptions, goals, plus the live depot. **Not one booking.** | when the workbook changes |
| `finance-<YYYY-MM>.md` | Balance, per category against plan, the twenty largest recipients. | per report run |
| `finance-subscriptions.md` | What is actually charged in three or more separate months, held against his planned list. | per report run |

They sit next to his own `anlagestrategie.md` in the same library rather than in a new one: the
rulebook says what to do, the summaries say what of. A second library would have split the context
in half.

---

## The funnel

```
Konten/**.csv          four dialects, parsed deterministically      no model
  ↓
ledger/YYYY-MM.jsonl   deduplicated by BOOKING, not by file         no model
  ↓
Finance · Categorise   one booking at a time, store=False           model
  ↓
report.build           totals, plan comparison, subscriptions       no model
  ↓
Finanzbericht.xlsx · library summaries · the chat                   no model
```

**Transfers never count.** A credit-card collective debit on the current account and the individual
items on the card statement are the same money seen twice; counting both doubles roughly a fifth of
the spending. They stay in the ledger — they happened — and are excluded from every total.

**The subscription list is arithmetic, not the agent's opinion**: a merchant charged in three
separate months. The agent's own `recurring` flag sits next to it, and where the two disagree is
where to look.

---

## What the real files taught

Every one of these was invisible until the actual data ran through:

* **The depot export states three decimals** (`416,859`). Truncating the third loses a cent per
  position and the total never quite matches the broker's. Rounded, half up, through `Decimal`.
* **`Anzahl` is a count, not an amount.** Read through the money parser, 1,128 shares became 1,12
  and the unrealised gain was four euros wrong on a position of a hundred and fifty.
* **The Commerzbank statement carries the value date `30.02.2026`.** Not a defect — German banks book
  value dates on a 30/360 basis. It is clamped to the last day the month has, and **only** the value
  date: clamping a booking date would silently move a booking into the wrong month.
* **bunq writes thousands as `1,200.00`.** With the comma left in, `Decimal` refused the value — and
  only on the four-figure bookings, so a smaller sample would have passed.
* **macOS is case-insensitive.** `Konten/Girokonto` and `Konten/girokonto` are one directory; the
  rename looked like a conflict and needed a detour over a temporary name.
* **The broker calls every download `investments.csv`** and macOS appends " (1)", which sorts
  *before* the original. Picking the alphabetically last one served a two-month-old portfolio while
  the fresh one lay beside it. Newest by modification time now.
* **"Summe" appears once per column block** in his workbook. Keyed by label alone the last one won,
  and the monthly expense total silently became the savings-potential figure.
* **"Sonstige" is a roll-up**, not an expense: it carries the total of the middle column. Filed as an
  item it lands under the wrong heading and double-counts all fifteen subscriptions.
* **HTTP 429 counts tokens, not requests.** 649 bookings at concurrency 10 died after 23 and threw
  all 23 away. Now 6 at a time, 40 per chunk, 8 seconds between, backoff with jitter — and the
  ledger is written after every chunk.

---

## Measurement

`make finance-eval` — 12 constructed cases, 15 expectations, 13 traps, 3 runs each, 2026-09-24:

| | hits | traps | s | tokens |
|---|---|---|---|---|
| small/none | 42/45 (93 %) | 3/39 (8 %) | 1.0 | 2,982 |
| small/high | 39/45 (87 %) | 5/39 (13 %) | 3.0 | 14,088 |
| **medium/none** | **42/45 (93 %)** | **0/39** | **1.0** | **2,747** |

`medium/none` wins on every column at once — and the small model needs *more* tokens to give a worse
answer. Reasoning hurts here for the third time in this repo.

**The hit rate alone would have hidden all of it.** It sat at 93 % for `small/none` and
`medium/none` alike; only the traps separated them.

Two corrections the measurement forced, both on claims made before it existed:

1. The confidence field was called worthless because 665 of 669 real bookings sat at 0.9 or above.
   The deliberately illegible case asks for confidence below 0.8 and the agent delivers it. The
   scale works; his bookings are simply legible.
2. A prompt change fixing the one systematic miss (`recurring` on a monthly AI charge) lifted
   medium to 15/15 and made `small/none` **worse** — it started reading an electronics purchase as a
   subscription, in 3 of 3 runs, while the hit rate stayed at 93 %.

---

## Usage

```bash
make finance-tidy                  # collect everything into one place — apply=1 moves
make finance-ingest apply=1        # statements → ledger
make finance-categorise apply=1    # ledger → categories, resumable
make finance-report write=1 upload=1   # workbook + library summaries
make finance-overview upload=1     # the standing frame from his workbook + depot
make finance-eval runs=3           # measure the agent
```

Everything defaults to a preview; `apply=1` is what acts. `make finance-tidy-undo` takes the last
tidy run back.

---

## Next

- **The contradiction rate.** Re-running the categorisation over the same bookings answers whether
  "always a model" is consistent, with a number rather than an opinion. That number decides whether
  a merchant map is needed after all.
- **Reimbursements.** Nothing separates a private expense from one that is paid back. It matters for
  exactly one category — but that one is 17 % of all spending.
- **The weekly briefing** against `anlagestrategie.md`: the rulebook names four regime signals and a
  falsification trigger, which makes a briefing falsifiable rather than general market commentary.
- **The conversational workflow**, so the four questions can be asked without a terminal.

---

## See also

- [`../workflows/CLAUDE.md`](../workflows/CLAUDE.md) — SDK conventions and the gotchas
- [`INBOX.md`](INBOX.md) — the third domain; its library and eval patterns are reused here
- [`BOOK.md`](BOOK.md) — where the local-CLI discipline comes from
