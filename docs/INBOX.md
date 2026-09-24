# Inbox — the daily round over the mailbox

The repo's third domain (next to [`CRM.md`](CRM.md) and [`BOOK.md`](BOOK.md)). It works the
mailbox once a day: what needs an answer, what involves money, what is noise worth
unsubscribing from — and what of it Vibe should know in the next working session.

> **A note on language.** Identifiers, module and workflow names, schema fields and config keys
> are English, like this documentation. German stays where the *subject matter* is German: the
> agent instructions (they classify German mail), and everything the author reads — the workflow
> descriptions in Studio, the strings in the conversation, the rendered report.

---

## What the mailbox actually looks like

Measured before anything was built, over the live account on 2026-09-23. Every design decision
below follows from these numbers rather than from an idea about mail:

| | |
|---|---|
| Inbox, last 7 days | 322 threads, 276 of them unread |
| Distinct senders | 117 |
| Gmail categories | UPDATES 144 · PROMOTIONS 86 · FORUMS 51 · **PERSONAL 5** · SOCIAL 1 |
| 90-day machine mail | 2,094 mails from 334 senders |
| The top 20 senders | 1,278 mails — 61 % of the volume — at **four** opens in total |

**The mailbox is about 98 % machine mail.** So the work is mostly subtraction, and the expensive
mistake is not "missed a newsletter" but "archived the one mail that wanted an answer".

---

## Where things live

| Path | Content |
|---|---|
| `shared/inbox.json` | **Domain configuration** — agent IDs, models, Gmail tool names, label vocabulary, limits, and the measurements that justify the settings. |
| `shared/inbox/eval-review.json` | The constructed eval cases. In the repo because they carry no real mail (`.example` domains throughout). |
| `agents/inbox-review.json`, `agents/inbox-second-review.json` | The two Studio agents as code. |
| `workflows/src/workflows/inbox/` | Domain code: Gmail layer, parsers, escalation rule, cleanup plan, report, rendering, workflows. |

Everything derived from the real mailbox — sender statistics, dossiers, eval cases built from real
envelopes — is gitignored. The repo is public; correspondents' addresses are not.

---

## The daily round, and why it can run unattended

`inbox-daily` triages **yesterday, the complete calendar day**, and writes the
dossier into the library. It changes nothing in the mailbox — no label, no draft,
no archive. Level 2 of the safety ladder needs an approval per session, and a
scheduled run has nobody to ask, so it stays on level 1 permanently. That is not
a gap to be closed later; it is the reason it is allowed to run at all.

Three things had to be right before it could exist:

**The identity.** A scheduled execution carries no user, so `on_behalf_of=True`
cannot work — the run dies with `400 Execution is missing user_id or
organization_id`. The inbox domain therefore has its own connector slot,
`connector("gmail", run_as="deployment")`, and every inbox workflow is declared
`on_behalf_of=False`. Measured end to end: a schedule-fired run completed with
`user_id = None` and read the real mailbox. The schedule lives in the code
(`daily.DAILY_SCHEDULE`, 06:00 Europe/Berlin); the worker registers it with
Studio at startup, so the repo stays the source of truth for when this runs.

**Where it runs.** A worker registers a workflow's schedules under **its own**
deployment name, so the laptop (`macbook-pro`) and the Cloudflare container
(`cloudflare`) would each register one and the round would run twice a day — or,
on the laptop alone, only while the laptop happens to be awake.
`shared/inbox.json` → `schedule.deployment` names the owner; `config.schedules_here()`
gates the `schedules=[…]` list, and everywhere else the workflow is trigger-only
(`make inbox-daily`). A test pins that this name and `worker-host/wrangler.jsonc`
agree.

**The window.** `newer_than:1d` is relative to the moment of the call — a run at
09:00 covers yesterday 09:00 to today 09:00. Two runs overlap, a late run loses
the start of its day, and no run covers exactly one day. `window.calendar_window`
builds a half-open `[start, end)` of calendar days and `gmail_query` renders it
as `after:2026/09/22 before:2026/09/23`. Consecutive days then tile without gap
or overlap, which is what makes a daily job something one can reason about —
and it is the property the tests pin.

**The brake.** `max_threads` used to be a silent cut: fetch, slice, say nothing.
On a seven-day window that threw away 272 of 322 threads without a word.
`gmail_search_threads` now returns `has_more`, the report carries `truncated`,
and the headline says *"abgeschnitten bei N — das Fenster trägt mehr"*. A cap
that cannot report that it bit is not a limit.

**The backlog stays out of it.** 2,094 machine mails from 334 senders will not be
worked off one mail at a time by a model — 61 % of the volume comes from twenty
senders at four opens in total. That is `inbox-senders` and an unsubscribe, not a
triage run.

---

## The safety ladder

Three levels, and nothing skips one:

1. **Read.** `inbox-scan` changes nothing. It reads, classifies, condenses.
2. **Label and mark read.** Only inside `inbox-review`, only after an explicit approval per
   session, and only with the labels from `shared/inbox.json`.
3. **Draft.** Mailto unsubscribes become drafts. The Gmail connector **cannot send** — which is
   the property that makes any of this acceptable.

Archiving is removing the `INBOX` label, marking read is removing `UNREAD`. Both are reversible in
Gmail, which is why they sit at level 2 rather than level 3.

---

## The funnel

**The model only sees what a model is needed for.** 46 mails a day, of which 64 in a week come
from `notifications@github.com` alone — letting a model re-decide that one 64 times is money for a
question already answered.

```
search_threads          both passes, paginated, envelopes only    no model
  ↓
envelope parsing        sender, subject, snippet, labels, date    no model
  ↓  own replies out    he had the last word → not a candidate    no model
inbox-review (small)    every envelope, in parallel               model
  ↓  escalation rule    reply? money? due today? correspondence?  no model
inbox-second-review     the critical subset only; it wins         model
  ↓
build_report            counting, grouping, sorting               no model
unsubscribe links       <a> anchors out of the HTML               no model
```

**Why bodies are not fetched in bulk:** `search_threads` returns bodies always as null, and one
single promotional mail carried 132,689 characters of HTML. Bodies are fetched individually, and
only where an unsubscribe link is needed.

---

## What the Gmail connector can and cannot do

Verified live (`connectors.list_tools`, 2026-09-23) — twelve tools:

| reading | writing |
|---|---|
| `search_threads`, `get_thread`, `list_labels`, `list_drafts` | `create_draft`, `label_thread`, `unlabel_thread`, `label_message`, `unlabel_message`, `create_label`, `update_label`, `delete_label` |

**It cannot unsubscribe.** There is no tool for it, and no `List-Unsubscribe` header in the
answer. So the link is pulled out of the HTML deterministically: the `<a>` anchor whose link text
contains "unsubscribe", "abmelden", "abbestellen" or "opt-out". Measured: 6 of 8 promotional
mails. The remaining two are reported by sender, for manual handling.

**Non-ASCII characters do not survive the connector.** Every umlaut, every `ß`, every emoji comes
back as one `U+FFFD` per byte — `Grüße` arrives as `Gr����e`, `können` as `k��nnen`. Measured on
2026-09-24 in the *raw* tool answer, before any of this repo's code touches it: 37 of 50 snippets
and 2 of 50 subjects damaged in a single `search_threads` page. It is not repairable downstream —
`U+FFFD` carries no byte value, so the original letter is gone. The triage still works (German
sentences stay readable around the holes), but the dossier and the report show it, and nothing in
this repo can fix it. **This is a bug in Mistral's Gmail connector and belongs in a report to
them.**

**Four field names that are not what one would guess**, each one measured rather than assumed:

* `resultCountEstimate` is useless — constant 201 on every non-final page. Paginate to the end of
  the token.
* Some threads come back with `messages: null`, non-deterministically, 26–57 per run on an
  identical query. Not an error; the parser returns `None` and the report counts them.
* `list_labels` returns `labelId`, **not** `id`.
* `create_label` requires `displayName`, **not** `name`.

The last two cost a day: with the expected names the lookup never found an existing label and the
creation failed schema validation — the entire cleanup step was dead, silently.

**A label name can be rejected for its first word.** The label namespace was `inbox/` and Gmail
answered every `create_label` with HTTP 400 `Invalid label name` — for `inbox/processed`, for
`Inbox/processed` and for a plain `inbox`. Gmail reserves its system label names (`INBOX`, `SENT`,
`DRAFT`, `SPAM`, `TRASH`, `STARRED`, `IMPORTANT`, `UNREAD`, `CHAT`, `CATEGORY_*`) and refuses a user
label whose first path segment collides with one, whatever the case. `Triage/processed` was created
on the first try; the namespace is now `Triage/`. `gmail.RESERVED_LABEL_SEGMENTS` rejects such a
name before the call, and a test checks every entry of `shared/inbox.json` → `labels` against it.

Worth noting *how* this hid: the error reached the screen as **"Activity task failed"**. Temporal
carries the connector's own answer in `details`, not in the message, so the one line naming the
actual cause was only in the event history. `review._root_reason` now unwraps the cause chain *and*
its `details`. The screen used to print a guess instead ("the connector is missing the permission")
— it was wrong twice in two days.

**A stale grant looks exactly like a missing feature.** On the first real cleanup run every label
tool failed — `create_label`, `label_thread`, `unlabel_thread` — for any input, including a plain
name with no slash. Reading worked. `create_draft` worked. And the credential reported
`status: valid`, so it did not look like an authentication problem at all.

It was one. The connector *does* request `gmail.modify`; the grant on this account simply predated
it. Re-authorising fixed all of it in one click. The cheap check that settles it:

```python
beta.connectors.get_auth_url(connector_id_or_name="gmail")   # the URL carries the scopes
```

Worth a minute before suspecting the code — the alternative on the table was building a Gmail MCP
server with its own OAuth client, which would have been a day of work for nothing.

One real bug did come out of it: the connector reports a failed tool as *plain text*
(`Error calling tool 'create_label'`), not as an error field. `json.loads` then raised, the
activity failed, and all Le Chat showed was "Activity task failed" — no tool name, no reason.
`_tool_json` now recognises that text and raises `GmailToolError` with the tool named, and the
cleanup step reports it on screen instead of taking the session down.

---

## The cascade, and what the first real run said about it

`inbox-review` (small) triages everything; `inbox-second-review` (medium) re-checks only what
`escalation.needs_second_review` selects: a needed reply, any money, a deadline today, and the two
small but delicate types (`correspondence`, `other`).

The rule is deliberately Python and not a model's feeling, because its failure directions are
asymmetric: small reporting too much is corrected cheaply; small missing something critical has to
escalate anyway.

Measured with `evalkit` and the cascade eval, 8 constructed cases, 2026-09-24:

| | hits | traps | s | tokens |
|---|---|---|---|---|
| **first stage small/none** | **41/42 (98 %)** | **0/30** | **1.0** | **2,092** |
| second stage medium/none | 41/42 (98 %) | 0/30 | 1.0 | 1,870 |
| second stage medium/high | 23/23 (100 %) | 0/13 | 5.3 | 7,182 |
| cascade (final) | 40/42 (95 %) | 0/30 | 1.6 | 3,169 |

On the constructed cases the cascade scored *below* the first stage alone, and the second stage
looked like a re-roller on probation.

**The first real run reversed that**, 2026-09-24, one day, 47–50 threads:

| | first stage alone | with the second stage |
|---|---|---|
| classified `correspondence` | **5 of 50** | **0** |

All five were machine mail — four GitHub threads with `Re:` in the subject and one automated
waitlist invite. The first stage reads a threaded `Re:` as a conversation. And `correspondence`
routes to `NEEDS_REPLY` in the cleanup plan, so those five would have been labelled "reply owed"
instead of archived as noise. The second stage caught every one.

So it stays. Nobody had constructed a GitHub `Re:` thread — which is the same lesson the book
domain paid for: constructed cases only prove what one already thought of.

The kill switch keeps counting, but it now compares `InboxReview.verdict()` rather than the whole
answer. Comparing everything counted a reworded `reasoning` as a change, and two models never word
it identically: the first run reported 5 of 5 "changed", a number that can never read zero and
therefore decides nothing.

Side note, contradicting the book domain's finding: reasoning *helped* here (medium/high reached
100 %). Which is the argument for measuring per agent rather than adopting a rule.

---

## Usage

```bash
make start-worker                     # in its own terminal; first run prompts Gmail OAuth
make inbox-daily                      # the nightly round by hand — yesterday, complete
make inbox-scan                       # dry run over the last day
make inbox-review                     # the same as a conversation, with the cleanup step
make inbox-senders window=90          # the 90-day sender statistic, pure arithmetic
make inbox-eval                       # measure the triage agent
make inbox-eval-cascade               # measure the cascade end to end
```

The conversational run is the actual workplace: in Vibe Work via `+` → Workflows →
*Inbox · Review (conversational)*. It needs no input, runs `inbox-scan` as a child workflow, shows
the report in a canvas, offers the unsubscribe view and the sender statistic, asks for the cleanup
approval, and puts the dossier into the library.

---

## The dossier — context for Vibe

The report is for reading once. The **dossier** is something else: a rolling document in the
Mistral Library, one per day, holding only what influences a working session — replies owed with
their urgency, deadlines and amounts, things promised or learned, and what he wrote himself.

The noise statistic deliberately stays out of it. Vibe does not need to know how many newsletters
arrived; it needs to know that an answer is owed to someone since Tuesday.

**Non-empty was not a good enough filter.** The first real run (2026-09-24, 50 mails) put fourteen
notes in the dossier and nine of them said, in so many words, that nothing had to happen: two
GitHub PR summaries, an issue notification, a weekly business digest, a trade-fair ad, a bank
inbox notice. The agent writes `context_for_vibe` for everything it reads, so the cut is made in
Python — `escalation.matters_for_vibe`, on the same fields the escalation rule uses: an owed reply,
money, a deadline today or this week, or one of the two delicate types. Replayed against that run's
data it keeps five of fourteen, and the five are the two failed payments, the CI failure and the
two dated offers.

Earlier versions of the same day are replaced, so the library never holds two states — the same
rule as `bookcli.sync`. The document is named after the day it **describes**, not the day it was
written, so a re-run replaces its predecessor and the library reads as a history rather than a pile.

That history is the reason every date in it is absolute. The first stored dossier said
`**today**` next to every owed reply — the agent's urgency enum, rendered raw. Read three weeks
later through retrieval it claims a deadline that has long passed, and nothing in the text says
otherwise. Urgency is now rendered as *"heute fällig, eingegangen 22.09.2026"*, and the header
names the window in calendar dates.

---

## What was wrong when this was reviewed

Six bugs, all found in the modules **without tests** (`review.py`, `scan.py`, `gmail.py`); the six
tested modules had none. Recorded here because the pattern matters more than the individual fixes:

1. `InboxReview` mirrored the agent schema with `betrag` while the agent returns `amount`, under
   `extra="forbid"`. **Every triage call died in validation.** The only visible symptom was a
   workflow at 50 % health.
2. `InboxReviewWorkflow` did not inherit `InteractiveWorkflow` but called `self.wait_for_input()`.
   The conversation died at the first form.
3. `gmail_ensure_label` read `label["id"]` instead of `labelId`.
4. …and created labels with `{"name": …}` instead of `displayName`.
5. `scan.py` read `params.zweitblick`; the field is `second_review`.
6. `_sender_stats_view` had three errors in eight lines — two wrong attribute names and a
   two-argument call to a one-argument helper.

Guards now in `workflows/tests/test_workflow_contracts.py`, checked across **every** workflow
module rather than for these cases:

* a class calling `self.wait_for_input` has to inherit `InteractiveWorkflow`;
* Pydantic field names are ASCII;
* a hand-written agent schema and its Pydantic mirror declare the same fields.

The third one exists only because the inbox agents are hand-written JSON. The book domain
generates its schemas from the models (`agents/build_book_agents.py`), which removes the drift
instead of detecting it — the better fix, and the one this domain should get next.

---

## Next

- **Run it for a week on real mail.** Everything measured so far rests on eight constructed cases,
  and constructed cases only prove what one already thought of. The book domain learned this the
  expensive way: on clean, real text the agent invented findings that no constructed case had
  predicted.
- **Then decide the cascade** by `second_review_changed`, not by opinion.
- **Generate the inbox agent schemas from the models**, as the book domain does.
- **Reply drafts.** `create_draft` takes `replyToMessageId`, so pre-written replies are one step
  away — but only for mails the author has marked, never automatically.

---

## See also

- [`../workflows/CLAUDE.md`](../workflows/CLAUDE.md) — SDK conventions and the gotchas
- [`CRM.md`](CRM.md) — the first domain; it shares the Gmail connector slot
- [`BOOK.md`](BOOK.md) — the second domain, and where most of these lessons were paid for
