# Promises

`logbook promises [--since YYYY-MM-DD] [--open] [--json]` reads the record's own words for the
things people said they would do: "I'll send you the photos by Friday", "we'll get back to you next
week", "ich melde mich bis Montag". It looks in every `transcript/v1` line (RFC 0004) whose text is in
the attachment store and every `note/v1` line (RFC 0010), by rules alone: no model runs and no socket
opens. What it prints are **proposals**, never facts. A sentence that reads like a promise is one
until you say so; the command's job is to make sure you see it.

```bash
logbook promises                        # every proposal the record holds, oldest first
logbook promises --since 2026-06-08     # from that local day on
logbook promises --open                 # without the ones you have marked done
logbook promises --json                 # the report as one JSON object, every proposal with its line id
logbook promises done 7c1d2e3f4a5b6c7d  # it was kept: one task/v1 line, status done; --open hides it
logbook promises done 7c1d… --note "photos came Thursday"
```

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
  own names are `you`; so is every note, since a note is yours. A diarizer's `Speaker A`, or a name
  nobody has resolved, stays as spoken, with no person behind it.
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

Under `--json` the report is one object: `since`, `open_only`, `extractor` (`name`, `version`, and
`languages` for the rules), `proposals` and `skipped`. Each proposal carries `id`, `status` (`open`
or `done`), `closed_by` (the task line's id), `day`, `at`, `line` (the origin), `seq`, `kind`
(`transcript` or `note`), `source`, `title`, `speaker` (`label`, `spoken`, `person`, `owner`, or
null), `direction` (`owed_by_owner` when you said it, `owed_to_owner` when a resolved person did,
null when nobody is behind the label), `certainty` (always `inferred`, RFC 0007's word for a
commitment read into the words), `language`, `cue` (the words that made it a promise, as written),
`class`, `quote` and `due` (`phrase` and `date`, or null). The fields are RFC 0007's where the two
overlap, so a later `commitment/v1` writer has nothing to translate.

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
or `cancelled`. `done` on a proposal already closed writes nothing and says so; an id the record
does not propose is refused with status 2. A proposal is yours to close only: the command never
closes one on its own, and nothing it reads can close another (RFC 0007 rule 3).

Why `task/v1` and not `commitment/v1`? A promise you confirm is, by RFC 0007, a `commitment/v1`
line, and a kept one a `commitment-close/v1`. That is two lines and a counterparty, and it is where
this command leads once a confirmation step exists; for now the one act the owner takes is "that
was done", and RFC 0016's task is the line that says exactly that with a title and a status. The
`extra` fields keep what a commitment writer would need.

## Replacing the rules with a model

The command does not know the rules. `promises.extract(lb, since, extractor=RULES)` takes any
object with a `name`, a `version` and `__call__(text) -> list[Match]`, where a `Match` is the
quoted sentence, the cue, the class, the language, the date phrase and, when the extractor resolved
it itself, the due day. A local model that reads a turn and returns the same shape slots in with no
change to the report, the text, the ids (a digest of line and sentence, so a model quoting the
same sentence agrees with the rules) or `done`, whose task lines record which extractor proposed
what. The report's `extractor` field says which one ran. What stays fixed is the contract: the
extractor sees text and returns sentences; the command owns the record, the speakers, the days and
the closes, and never lets an extractor write.

## What it does not do

It does not read the free-text notes files (`notes/<YYYY>/<date>.md`), messages (`message/v1`),
mail or calendar entries; a first-person promise in a chat message is a later source, under the same
contract. It does not know who a promise is *to*: the `direction` says who made it, not whom it
binds. It does not write commitments, retract anything, or run anything but regular expressions.
