# The synthesis of a call

A model reads one transcript, a work call, and writes one line about it: what someone is to do after
the call, on top; the topics, each theme once however often the call came back to it; what was
decided; what was left open; and a short personal part. Every item points at the utterances it rests
on. The line is a `draft/v1` ([RFC 0036](rfcs/0036-goals-reviews-drafts-chapters.md),
[the profile](https://github.com/bighydro/logbook/blob/main/rfcs/0036-draft-v1.md)) of unit `event`
whose subject is the transcript line, and the Day shows it under the call's row, collapsed.

```
logbook transcript synthesize 01a1377b-5609-7db6-955c-a2a2b3db9660   # one call, by its line id
logbook transcript synthesize '#5432'                                 # by its seq
logbook transcript synthesize a2b3db9660                              # by the end of its id, as the Day shortens it
logbook transcript synthesize --day 2026-06-10                        # every call of a day
logbook transcript synthesize --day yesterday --dry-run               # ask the model, check the answer, write nothing
```

`--show-prompt` prints the prompt and the material as they are sent; `--again` asks once more when
this model has already synthesized the call. The morning's `dream --catch-up` synthesizes every call of
the days it covers that has no synthesis yet (below).

## What a synthesis is, and is not

A synthesis is a proposal; the transcript is the record. Nothing derives a fact from it: not a task,
not a promise, not a person. An action it proposes is not a task until you make it one; a decision it
reports is the model's reading of the call. The synthesis never writes a note, a task or a signature.
It writes one `draft` line, source `model:<name>`, and nothing else; a synthesis again writes a new line
whose `supersedes` names the one before, and the earlier text stays in the record.

## The policy entry and the endpoint

It runs on the dream's engine, so it is governed by the same `dream` entry of `policy/crossing.json`
and reaches the same model ([the dream](dream.md#the-policy-entry), [the endpoint](dream.md#the-endpoint)):
no entry, or an expired one, and it refuses in one sentence and nothing leaves the machine.

The entry's `max_tier` is the ceiling, and a transcript is one line with one tier: a call above the
ceiling stays home whole. The `granola`, `transcript` and `wispr-flow` adapters write `transcript/v1` at
tier 3, so under the usual `"max_tier": 2` a call is **held back**: `transcript synthesize ID` says so
and exits 2, `--day` says it in the call's row, and the catch-up counts it. To let calls cross, write
`"max_tier": 3` on the entry, which also lets the dream read the day's tier-3 lines (health, money), or
import the calls at tier 2 (`logbook add --tier 2`). The draft's tier is the transcript's.

## What the model sees

The call and nothing else: a header, reference `T`, with the title, the provider, the day, the start
and the end, the participants by name (never an address) and how many utterances there are; then every
utterance in order, as the transcript's text in the attachment store reads (`U1`, `U2`, ...), each with
its speaker as the transcript labels them and, when the recording gives times (Granola's segments,
WebVTT and SRT cues), where it is in the call (`20:05`). A transcript whose text is not in the store, or
is sealed on a machine without the identity, is said and not sent.

The prompt ([docs/synthesis-prompt.md](synthesis-prompt.md) explains it) fixes the schema and the
rules: actions on top, topics consolidated across the whole call, decisions settled and not merely
discussed, and **work only**. That last one is a rule of the prompt and not a filter in the code: the
whole call reaches the model, and the model is told that anything personal goes to the personal part,
at most three short neutral sentences, and nowhere else. No code decides what is personal.

## Evidence: the transcript line, and the utterances beside it

A transcript's utterances are not lines of their own: `transcript/v1` keeps the text in one attachment
(RFC 0004), so the only line a synthesis can point at is the transcript. Every supported segment's
`evidence` is that line's id, and which utterances it rests on is kept beside the segments, under
`extra.segments`, one object per segment:

```json
{"part": "actions", "utterances": [{"n": 10, "offset": "46:30"}, {"n": 11, "offset": "47:00"}],
 "assignee": "Ola Nordmann", "due": {"phrase": "by Friday", "date": "2026-06-12"}}
```

`n` is the utterance's place in the transcript's text, from 1, in the order `transcripts.turns_of`
reads it; `offset` is where it is in the recording, when the recording says. `due.date` is the phrase
read against the day of the call, as `promises` reads a due hint (SPEC §3.2.10 rule 4), and is shown with
a question mark because it is a reading of the words.

Before anything is written, every reference of the answer is checked: `T`, the transcript's own id, or
`U<n>` for an utterance the material gave. An item that cites anything else, alone or beside good
references (an utterance past the end, another line, a day's `L1`), is **unsupported**, as RFC 0036
rule 6 asks; an item without text is dropped; topics the model names twice are one topic, their texts
joined and their utterances united; and when more than 30 % of the items are unsupported the answer is
refused and nothing is written, as the dream refuses. The line holds the segments, the ids and the
utterance numbers, never the prompt, the material or the call's words.

## Once, and again

A call the same model has synthesized under the same prompt (`transcript-synthesis/1`, kept in
`extra.prompt`) is **unchanged**: nothing is sent, nothing is written, and the standing synthesis is
printed. Another model, a new prompt, or `--again` writes a new line that supersedes the standing one. A
transcript that is retracted or superseded is not the call as the record stands and is refused.

The run holds the record's writer lock and reads the head again before it appends: a head that moved
under the reading is `HeadMoved`, one sentence, nothing written.

`dream --catch-up`, the 06:00 close's second step ([the schedule](schedule.md)), synthesizes, after the
days, each call of those days that no model has synthesized yet, one row each; a call held back by the
ceiling or without its text is counted in the closing line:

```
$ logbook dream --catch-up --days 3
2026-06-09  empty     nothing logged
2026-06-10  dreamed   #5440 · no draft yet · 4 segments
2026-06-11  unchanged unchanged since #5431
2026-06-10  synthesized #5441 · “Yard plans” · 6 segments
1 dreamed · 1 unchanged · 1 empty · 1 synthesized · 1 transcript held back above max_tier 2
```

## On the Day

Under the call's row, one row, collapsed: what the synthesis holds and which model wrote it.

```
  09:00–12:00  stay   Home · 3 h · 1 transcript
      transcript   Yard plans
                   synthesis · 1 action, 2 topics, 1 decision, 1 open thread, 1 personal · model:qwen2.5-7b-instruct
```

The items are behind it: in `serve`, a toggle under the call opens them, actions on top, each with its
assignee and due hint and where in the call it rests (the line on hover), an unsupported one muted and
marked; `day --json` carries them under `syntheses`; `transcript synthesize ID` prints them:

```
2026-06-10 10:00 “Yard plans”: synthesized as #5441 draft/v1 · model:qwen2.5-7b-instruct · tier 3 · 11 utterances read at b7e3ddf2 · 6 segments, 1 unsupported
    action    Send the survey report to Ines.  → Ola Nordmann · due by Friday (2026-06-12?)  [46:30, 47:00]
    topic     Hull survey: The yard in Vollen surveys in week 26; the keel is to be checked too.  [02:00, 20:00, 45:00]
    topic     Mooring lines: The new mooring lines arrived.  [08:30]
    decision  The survey goes to the yard in Vollen.  [12:00, 12:20]
    open      Who pays for the haul-out is still open.  [31:00]
  ~ personal  A family matter of Ines's came up.  unsupported
  a synthesis is a proposal: the transcript is the record
```

`day --no-dream` leaves syntheses out with the day's draft. `show` lists the draft line on the day it
was written, as every line.
