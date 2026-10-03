# Tasks

`logbook tasks [--open] [--propose-done] [--json]` reads the record's tasks back: every `task/v1`
line (RFC 0016) a task app's export left, as the task it describes, in the state it was last seen.
`--propose-done` asks the record whether an open task was done without anyone ticking it off: a
booking confirmation in the mail for "book flights to Zürich", a calendar entry for "call Ola", a
card payment at the marina for "pay the berth fee at Marina Solvind". It finds them by rules, in
English and German, with no model and no network, and prints each as a **proposal** with the id of
the line that is the evidence, never as a fact. `tasks done <id> --evidence <line>` is the one thing
the command writes: a `task/v1` line that marks the task done, carrying the evidence, and nothing
else.

```bash
logbook tasks                              # every task as it stands, oldest first
logbook tasks --open                       # the open ones
logbook tasks --propose-done               # for each open task, the evidence it was done, with line ids
logbook tasks --json                       # the report as one JSON object
logbook tasks done 0dd9108fb6d5d715 --evidence 01a0fda3-99b0-7af6-a986-0a377117a94b
logbook tasks done ba26f9651977a75b        # done, with no line to show for it
```

## What a task is

A task app's export is a set of snapshots, and the log keeps every one (RFC 0016 rule 2): the same
to-do exported again after it was ticked off is a new line whose `raw_id` ends in a newer
modification time. The command takes, per source id (the `raw_id` before its last `@`), the standing
line with the newest suffix (the later line when two share it; a line with no `@` is keyed whole,
its suffix its `modified_at`) and calls that the task. A retracted line is out; a line with no
`raw_id` or no title is skipped.

```
7 tasks, 6 open (the latest snapshot of each task is its state, RFC 0016)
  2026-06-01  11:00  open                  “Renew the boat insurance”  3096daca87cd18f9
  2026-06-08  08:30  open  due 2026-06-20  “Book flights to Zürich”  [Work]  0dd9108fb6d5d715
  2026-06-09  09:00  open                  “Call Ola about the mooring”  [Boat]  ead035a05df19fee
  2026-06-11  14:10  done                  “Buy the long rope”  [Boat]  75c34488134f6542
```

- **The day and time** are the newest snapshot's `at`, in the record's zone: for Google Tasks the
  last modification (the export keeps no creation time), so a done task sits on the day it was done.
- **The status** is the snapshot's: `open`, `done` or `cancelled`. `--open` keeps the first.
- **The due day** and **the list** are the snapshot's `due` and `list`, when it has them.
- **The id** is a digest of the source id, sixteen hex characters: the same for every snapshot of
  one task, however often it is exported, and the handle `tasks done` takes.

Under `--json` the report is one object: `open_only`, `propose_done`, `window_days` (14),
`matcher` (which matcher read the evidence, or null when none did), `tasks` and `proposals`. Each
task carries `id`, `key` (the source id), `title`, `status`, `due`, `list`, `at`, `day`, `seq`,
`line` (the newest snapshot's line id) and `source`.

## The evidence: `--propose-done`

For every open task the command reads the standing `mail/v1`, `event/v1` and `transaction/v1` lines
of the **fourteen days after the task's `at`** (`taskdone.WINDOW`; both ends included), through
the index, and asks the matcher about each. A line before the task, or after the fortnight, is never
evidence; a retracted line, and one a later line of its kind `supersedes`, is not read.

```
4 open tasks with evidence of being done, read by rules, not facts; close one with `logbook tasks done <id> --evidence <line>`
  “Book flights to Zürich”  (2026-06-08, 0dd9108fb6d5d715)
    2026-06-12  12:00  mail         “Your booking confirmation: Oslo – Zürich, 20 June”  zürich  01a0fda3-99b0-7af6-a986-0a377117a94b
  “Call Ola about the mooring”  (2026-06-09, ead035a05df19fee)
    2026-06-15  15:00  event        “Call with Ola Nordmann”  ola  ×2 sources  01a0fda3-99b0-7631-aeac-6035128fe018
  “Pay the berth fee at Marina Solvind”  (2026-06-10, 5314e1030197326b)
    2026-06-14  12:00  transaction  “Marina Solvind”  marina solvind  01a0fda3-99b1-7769-906c-19117862caf9
  2 open tasks with no evidence found
```

Under each task: the evidence's day and time, its kind, its text (a mail's subject, an entry's title,
a transaction's merchant, never a body), the task's words it carries, `×N sources` when the same
calendar entry comes from several calendars (the same instants and the same title are one proposal
naming every line; the first line's id is printed), and the evidence line's id. Under `--json` every
proposal carries `task` (the task's id), `line`, `lines`, `kind`, `source`, `sources`, `at`, `day`,
`tier` (a transaction's is 3), `text` and `evidence` (`rule`, `shared`, `confidence`).

### The rules

The matcher takes the task's title apart into its **key nouns** and its **verbs**
(`taskdone.words_of`). A verb is a word on the lists of things a task asks for, in English (`book`,
`buy`, `call`, `pay`, `send`, `order`, `renew`, `cancel`, `meet`, `visit`, …) or German (`buchen`,
`kaufen`, `anrufen`, `bezahlen`, `bestellen`, `schicken`, `verlängern`, `kündigen`, `treffen`, …);
a noun is every other word of three letters or more that is not an article, a preposition, a
pronoun or a filler in either language (`the`, `to`, `about`, `my`, `next`; `die`, `nach`, `wegen`,
`bitte`). `Book flights to Zürich` is the nouns `flights`, `zürich` and the verb `book`; `Flüge
nach Tromsø buchen` the nouns `flüge`, `tromsø` and the verb `buchen`. A task with no noun
(`Do it`) has no evidence.

Two words are one when they match case, accents, an English plural `s` and German compounds aside
(`taskdone.same_word`): `Zürich` is `zurich`, `Tromsø` is `tromso`, `flights` is `flight`, `Flug` is
the start of `Flugtickets`. The compound rule needs four letters, so `Ola` never matches `Olav` and
`fee` never `feel`.

A line is evidence when its text carries a key noun of the task **and**, by kind:

| Kind | And | Rule |
|---|---|---|
| `mail/v1` | the subject confirms something — `confirmation`, `confirmed`, `booking`, `booked`, `receipt`, `ticket`, `itinerary`, `reservation`, `invoice`, `order`; `Bestätigung`, `Buchung`, `gebucht`, `Rechnung`, `Quittung`, `Reservierung`, `Bestellung`, `Beleg`, as a word or inside a compound (`Buchungsbestätigung`) | `mail-confirmation` |
| `mail/v1` | the owner sent it (`direction` `sent`): "send the photos to Ola" and a sent mail "Mooring photos" | `mail-sent` |
| `event/v1` | the task is an appointment (its verb `call`, `phone`, `meet`, `see`, `visit`, `talk`, `anrufen`, `treffen`, `besuchen`, or a noun `appointment`, `meeting`, `lunch`, `Termin`, `Besprechung`, …), or the entry's title repeats the task's verb, or it carries two of the task's nouns | `event` |
| `transaction/v1` | the merchant carries a noun: the task names where the money went | `transaction` |

A received mail that shares a noun but confirms nothing (`Zürich newsletter: 10 things to do`) is
not evidence; nor is a mail that shares only the task's verb (`Book club: June reading` for `Book
flights`); nor a calendar entry that shares one place name with a task that is no appointment
(`Zürich standup` for `Book flights to Zürich`); nor a payment at the marina five days before the
task was written. The confidence is 0.6, a tenth more per noun shared beyond the first, a tenth
more for a confirmation cue, 0.9 at most; it is the rules' own estimate and is printed under
`--json` only.

The rules will miss evidence phrased another way and propose a line that is none — a newsletter
with a receipt in its subject, a transaction at a shop whose name is a word of the task — which is
why nothing here is a fact until you close the task.

## Closing one: `tasks done <id> [--evidence <line>]`

`done` appends one `task/v1` line and nothing else: `source` `manual`, `kind` `task`, tier 2 (RFC
0016: MUST), `at` now. Its payload is the newest snapshot of the task: `raw_id` `<source id>@<now>`
so that it is, by rule 2, the task's state from here on; the title, `due` and `list` carried over;
`status` `done`; `completed_at` and `modified_at` now; `supersedes` the snapshot it replaces; and,
when `--evidence` names a line, `extra.evidence` with that line's id. The evidence must be a line
the record holds; an id it does not is refused with status 2, and so is a task id `tasks` does not
print. A task already done or cancelled is left alone and said so; a second `done` writes nothing.

`--open` and `--propose-done` then leave the task out, since its newest snapshot is done. The app's
own export, imported later, may bring a newer snapshot still open; by rule 2 the newest wins, and
the task is open again until the app agrees. Nothing is edited: the earlier snapshots, the mail and
the transaction stay as they were, and the close is a line beside them.

`--evidence` is optional: a task done with nothing in the record to show for it closes the same way,
and the payload then carries no `extra`.

## Replacing the rules with a model

The command does not know the rules. `taskdone.propose(lb, matcher=RULES)` takes any object with a
`name`, a `version` and `__call__(task, candidate) -> Evidence | None`, where the `Task` is the
title and its state, the `Candidate` one line as a matcher sees it (its kind, its one text, whether
the owner sent it) and the `Evidence` a `rule` of the matcher's own naming, the task's words it
found and a confidence from 0 to 1. The command owns the record, the tasks, the window and the
candidates, dedupes a calendar entry across sources and never lets a matcher write. The promises
judge's engine (`judge.Engine`, `docs/promises.md`: a local instruct model that answers one JSON
object per candidate, never the network) is the shape of the next matcher: one that reads a task
and a line and says whether the line shows the task done. Its proposals land in the same report,
with the same task ids, and `done` is unchanged. The report's `matcher` field says which one ran.

## What it does not do

It does not read a mail's body, a calendar entry's notes or a transaction's amount; it does not
look at messages (`message/v1`), notes or transcripts for "I booked it", which is `promises`'
ground; it does not close a task on its own, retract anything, or run a model. A task whose evidence
is in no line of the record — the plants were watered — is yours to close with `done` and no
evidence.
