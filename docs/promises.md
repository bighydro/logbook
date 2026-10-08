# Promises

`logbook promises [--since YYYY-MM-DD] [--open] [--all] [--judge] [--json]` reads the record's own
words for the things people said they would do: "I'll send you the photos by Friday", "we'll get
back to you next week", "ich melde mich bis Montag". It looks in every `transcript/v1` line (RFC 0004)
whose text is in the attachment store and every `note/v1` line (RFC 0010), in two passes. The
**rules** find every sentence that reads like a promise, by regular expressions alone; on a real
record that is far too many (seven hundred in twelve days, most of them "I'll have a look"). The
**judge** is a local instruct model that reads each candidate in its context and says whether it is
a commitment, by whom, to whom, what and by when; its verdicts are kept in the record and never
redone. By default the command shows the judged commitments; `--all` shows every candidate the
rules found; `--judge` runs the model on the candidates it has not read yet. No model runs unless
you ask, and nothing leaves the machine either way: the judge is `mlx-lm` on Apple silicon, an
optional extra, with the Hugging Face hub told it is offline while it runs. What it prints are
**proposals**, never facts. A sentence that reads like a promise is one until you say so; the
command's job is to make sure you see it.

```bash
logbook promises                        # the judged commitments (confidence 0.6 or above), oldest first
logbook promises --all                  # every candidate the rules found, judged or not
logbook promises --judge                # judge the unjudged candidates first, then list; a progress line per candidate
logbook promises --judge --limit 50     # at most fifty this run; the next run carries on
logbook promises --judge --model mlx-community/Qwen2.5-3B-Instruct-4bit   # a smaller model
logbook promises --judge --fetch-model  # download the model first; the only time the command uses the network
logbook promises --since 2026-06-08     # from that local day on
logbook promises --open                 # without the ones you have marked done
logbook promises --json                 # the report as one JSON object, every proposal with its line id
logbook promises done 7c1d2e3f4a5b6c7d  # it was kept: one task/v1 line, status done; --open hides it
logbook promises done 7c1d… --note "photos came Thursday"
```

The judge needs the extra: `uv pip install 'openlogbook[judge]'` (or `pip install`), which brings
`mlx-lm`; it runs on Apple silicon only. Without it `--judge` stops with the message that says so,
and everything else works.

## What a proposal is

One sentence, with where it was read and who said it:

```
10 proposed promises, read by rules, not facts; confirm one with `logbook promises done <id>`
  2026-06-11  14:00  Ola Nordmann  “I'll send you the mooring photos by Friday.”  due 2026-06-12? (by Friday)  3b9e5d0f2a71c846
  2026-06-11  14:00  you           “I will book the crane for next week.”  due 2026-06-15? (next week)  a1f0…
  2026-06-11  14:00  you           “Let me check the forecast first.”  5d2c…
  2026-06-13  19:00  you           “I need to order the new bilge pump next week.”  due 2026-06-15? (next week)  e97b…
  2026-06-16  19:00  Kari Nordmann “Ich melde mich bis Montag wegen Tromsø.”  due 2026-06-22? (bis Montag)  08c4…
  2026-06-16  19:00  Speaker A     “We will see.”  f3a2…
  1 transcript whose text is not in the attachment store skipped
```

- **The day and time** are the line's: a transcript's start, a note's writing time, in the record's
  zone. A transcript's turns carry no time of their own here, so every promise in a meeting is on
  the meeting's hour.
- **Who** is the speaker when the transcript resolves one. The source's label for the turn
  (`Ola Nordmann:` in Markdown, `<v Ola Nordmann>` in WebVTT, Granola's `speaker.name`) is matched
  to the line's `participants`, and their email, phone or provider id to a person through the
  record's resolution lines (RFC 0006), the same way the with module places a transcript's
  participants at a stay. A bare name the record labels one person by resolves too. `me` and your
  own names are `you`; so is a note, since a note is yours. A diarizer's `Speaker A`, or a name
  nobody has resolved, stays as spoken, with no person behind it. Text that carries its own labels
  belongs to them: a line of a note or of a turn that begins `Speaker 2:` (or with the name of a
  participant, of a person the record resolves, or of you) is that speaker's, whatever label the
  source put on the turn and whoever's note it is in; you are `you` only when the label resolves to
  one of your identities. A word before a colon that names nobody (`Plan:`) is text.
- **The sentence** is quoted as written, whitespace collapsed, never paraphrased.
- **The due hint** is there when the sentence carries a date phrase, with a `?` because it is a
  reading of the words, not a deadline anyone agreed. It is resolved against the day the sentence
  was said: a weekday is the next one strictly after that day (`by Friday` on a Thursday is
  tomorrow; on a Friday it is next week's); `next week` is its Monday; `this week` and `by the end of
  the week` the Friday on or after the day; `tomorrow`, `morgen`, `übermorgen`, `tonight`, `heute
  Abend`, `in two weeks`, `in drei Tagen`, `next month`; a month and a day (`by June 20`, `20 June`,
  `bis 20. Juni`, `bis zum 20.6.`) the next such date; `the 5th` and `am 5.` the next fifth.
- **The id** is a digest of the origin line's id and the quoted sentence, case and whitespace
  aside: sixteen hex characters. The same sentence in the same line has the same id however often
  the command runs, and whichever extractor found it (below).
- **`done`** after the due hint marks a proposal you closed; `--open` leaves those out.
- **`kept`, `missed on 2026-06-14`, `dropped`, `carried`** is what the signed day of the line the
  promise was read in says became of it ([the signed day](signed-day.md), RFC 0034 amendment 1):
  kept and dropped close the promise, missed closes and flags it, carried leaves it open; `--open`
  leaves the first three out.

Under `--json` the report is one object: `since`, `open_only`, `judged_only` (false under
`--all`), `threshold` (0.6), `extractor` (`name`, `version`, and `languages` for the rules), `judge`
(what a `--judge` run just did: `engine`, `model`, `candidates`, `judged`, `unparsed`; null when
none ran), `unjudged` (how many candidates have no verdict yet), `proposals` and `skipped`. Each
proposal carries `id`, `status` (`open` or `done`), `closed_by` (the task line's id), `disposition`
(`value`, `day` and `line`, the signed-day line's, when the standing signature of its day disposed
of the line it was read in; null otherwise), `day`, `at`,
`line` (the origin), `seq`, `kind` (`transcript` or `note`), `source`, `title`, `speaker` (`label`,
`spoken`, `person`, `owner`, or null), `direction` (`owed_by_owner` when you said it,
`owed_to_owner` when a resolved person did, null when nobody is behind the label), `certainty`
(always `inferred`: the words were read into a promise, never stated as one), `language`, `cue` (the
words that made it a promise, as written), `class`, `quote`, `due` (`phrase` and `date`, or null)
and `judgement` (below, or null). The fields are this reader's own; `commitment/v1` (RFC 0007), which
they once mirrored, was withdrawn by RFC 0031.

## The judge

`--judge` reads every candidate the rules found that has no verdict yet, oldest first, with a local
instruct model, and prints one progress line per candidate on stderr. The model sees the candidate
sentence marked among the two sentences before and after it in the same transcript or note, across
turns, each with who said it as the report names them (`you`, `Ola Nordmann`, `Speaker A`); the
day, the title; your name as the record resolves it; and the names the record resolves in that
line, so it can say who a promise is to. It answers one JSON object, sampled at temperature 0, so
the same candidate gets the same verdict from the same model:

| Field | What |
|---|---|
| `is_commitment` | whether the sentence is a specific thing a specific person said they will or must do; "we'll see", "I'll have a look", "let me think" and reports of what someone else will do are not |
| `by` | who made it: `owner`, a name from the list, or `unknown` |
| `to` | whom it binds them to: `owner`, a name, or `unknown` |
| `what` | the commitment in one line, in the speaker's own words shortened |
| `due` | `YYYY-MM-DD`, resolved against the day it was said, or null when the words name no day |
| `confidence` | 0 to 1 |

A candidate **shows** when the verdict is a commitment at confidence 0.6 or above
(`promises.THRESHOLD`); `--all` shows every candidate, judged or not. A judged row carries the
verdict after the due hint: the confidence, `by <name>` when it is not the speaker, `to <name>`
when known, and `no 0.95` for a judged non-commitment. The due hint is the verdict's day when it
gave one, else the rules' reading with its phrase. The quote stays the sentence as written, since
the id is a digest of it.

```
judged 10 candidates with mlx-lm (mlx-community/Qwen2.5-7B-Instruct-4bit)
2 judged promises (a commitment at confidence 0.6 or above, read by mlx-lm); `--all` shows every candidate; confirm one with `logbook promises done <id>`
  2026-06-11  14:00  Ola Nordmann  “I'll send you the mooring photos by Friday.”  due 2026-06-12?  0.92 to you  3b9e5d0f2a71c846
  2026-06-11  14:00  you           “I will book the crane for next week.”  due 2026-06-15? (next week)  0.8 to Ola Nordmann  a1f0…
  1 transcript whose text is not in the attachment store skipped
```

**The verdicts are kept in the record**, outside the chain, in `policy/promises-cache.json`:
`{"version": 1, "judgements": {"<candidate id>": {"is_commitment", "by", "to", "what", "due",
"confidence", "engine", "model", "judged_at"}}}`, the ids sorted. A candidate is judged once,
however often the command runs and whatever `--model` is set later; the model that read it is in
its entry, so a verdict from a weaker model can be told from a later one. The file is rewritten
after every verdict, so an interrupted run keeps what it did and the next carries on; `--limit N`
judges at most N candidates in one run. An answer with no whole verdict in it (no JSON object, a
field missing or malformed) is counted, not kept, and the next `--judge` tries that candidate
again. Delete an entry, or the file, to have a candidate judged afresh. Under `--json` every
proposal carries its `judgement` with the same fields, or null.

**The engine** is `mlx-lm`, Apple's MLX runner for language models, with
`mlx-community/Qwen2.5-7B-Instruct-4bit` by default (`judge.DEFAULT_MODEL`): about four gigabytes,
a few seconds per candidate on an M-series Mac; `--model` names any instruct model the hub serves
in MLX format (`mlx-community/Qwen2.5-3B-Instruct-4bit` is a third the size and a few times faster;
`mlx-community/Meta-Llama-3.1-8B-Instruct-4bit` another). It is imported only when `--judge` runs,
and while it runs the hub is told it is offline (`HF_HUB_OFFLINE`), so no socket is opened for any
reason. A model not yet on the machine stops the command naming the one flag that fetches it,
`--fetch-model`, which downloads the model before the first candidate and nothing else, ever; the
same rule `transcribe` has. Without the extra, `--judge` stops with the message that names it.
There is no cloud model and there will not be one: a record's words are read on the record's
machine.

The judge is a second reading of the rules' candidates, never a third extractor: it changes neither
a proposal, nor its id, nor what `done` writes, and it writes nothing to the chain. What it makes
of a sentence is as much a draft as the sentence itself; the owner still closes a promise, or not.

## The rules

A sentence is proposed when it carries one of these, is not negated right after it (`I will not`,
`I'll never`, `ich werde nicht`) and does not end in a question mark. One proposal per sentence; the
first cue decides the class.

| Class | English | German |
|---|---|---|
| `future` | `I'll`, `I will`, `I shall`, `I'm going to`, `we'll`, `we will`, `we're going to`, `I promise` | `ich werde`, `ich schicke`, `ich sende`, `ich melde mich`, `ich kümmere mich`, `ich rufe`, `ich bringe`, `ich liefere`, and the same with `wir` |
| `obligation` | `I need to`, `I have to`, `I must`, `I've got to`, `I ought to`, and with `we` | `ich muss`, `wir müssen` |
| `offer` | `let me` (not `let me know`) | |

Only the first person counts: `he will send`, `they'll get back` and `will you` propose nothing. The
rules are plain regular expressions over sentences; they will miss a promise phrased another way
and propose a sentence that is none, which is why nothing here is a fact until you close it.

Sentences are cut at a full stop, `!` or `?` that does not follow a digit (`bis 20. Juni` stays
whole) and at every line break. A transcript's text is read by its media type: WebVTT and SRT cues,
Granola's JSON segments, and `Speaker: text` prose or plain text through the file adapter's own
parsers. A transcript whose text is not in the store is counted and skipped, never a traceback. A
retracted line, and a note or transcript a later line `supersedes`, is not read: the latest version
stands, as every reader has it.

## Closing one: `promises done <id>`

`done` appends one `task/v1` line (RFC 0016) and nothing else: `source` `manual`, `kind` `task`,
tier 2, `at` now. Its payload is the sentence as `title`, `status` `done`, the due hint as `due`
when there was one, `completed_at`, `list` `promises`, your `--note` as `notes`, and under `extra`
the proposal's `promise` id, its `origin` line, the `speaker` and the `extractor` that proposed it,
so a reader can trace the close back to the words. `raw_id` is `promise:<id>@<time>`, the snapshot
form the profile asks for. Nothing is edited: the transcript and the note stay as they were, and
the close is a line beside them.

`--open` hides a proposal whose latest standing task line (by `extra.promise`) has status `done`
or `cancelled`, and one whose day's standing signature kept, missed or dropped the line it was read
in (a carried one is still open, and `done` closes it as any other). `done` on a proposal already
closed, by a task line or by the signed day, writes nothing and says so; an id the record
does not propose is refused with status 2. A proposal is yours to close only: the command never
closes one on its own, and nothing it reads can close another: a proposal is never asserted, and
only the owner closes one.

Why `task/v1`? `commitment/v1` and `commitment-close/v1` (RFC 0007) were the lines a confirmed
promise and its keeping would have become: two lines and a counterparty. Nothing ever wrote or read
them, and RFC 0031 withdrew them. The one act the owner takes is "that was done", and RFC 0016's
task is the line that says exactly that with a title and a status. The `extra` fields keep what a
counterparty's writer would need.

## Replacing the rules with a model

The command does not know the rules. `promises.extract(lb, since, extractor=RULES)` takes any
object with a `name`, a `version` and `__call__(text) -> list[Match]`, where a `Match` is the
quoted sentence, the cue, the class, the language, the date phrase and, when the extractor resolved
it itself, the due day. A local model that reads a turn and returns the same shape slots in with no
change to the report, the text, the ids (a digest of line and sentence, so a model quoting the
same sentence agrees with the rules) or `done`, whose task lines record which extractor proposed
what. The report's `extractor` field says which one ran. What stays fixed is the contract: the
extractor sees text and returns sentences; the command owns the record, the speakers, the days and
the closes, and never lets an extractor write. The judge is the same shape one step on:
`judge.Engine` is anything with a `name`, a `model`, `ready()`, `fetch()` and
`answer(messages) -> str`, and the tests run the whole command through a fake one with fixed
answers.

## What it does not do

It does not read the free-text notes files (`notes/<YYYY>/<date>.md`), messages (`message/v1`),
mail or calendar entries; a first-person promise in a chat message is a later source, under the same
contract. Whether a task the apps hold was *done* is `logbook tasks --propose-done`'s question
([docs/tasks.md](tasks.md)), asked of the mail, the calendar and the transactions under a matcher of
the same shape. The rules do not know who a promise is *to*: the `direction` says who made it, not whom
it binds; only a judgement's `to` does, and it is the model's reading. It does not write
commitments, retract anything, or run a model you did not ask for.
