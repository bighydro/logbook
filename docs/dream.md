# The dream

Every morning a model reads yesterday and writes one line about it: the day in a paragraph, the threads
it moved, two questions for your reflection, and proposals, the people it thinks were there and the
promises it thinks were made. Every sentence points at the lines it came from. The line is a `draft/v1`
([RFC 0036](rfcs/0036-goals-reviews-drafts-chapters.md), [the profile](https://github.com/bighydro/logbook/blob/main/rfcs/0036-draft-v1.md)),
and the Day shows it above your note, labelled as a draft.

```
logbook dream day 2026-06-13            # one day, one line
logbook dream day 2026-06-13 --dry-run  # ask the model, check the answer, write nothing
logbook dream --catch-up --days 14      # every day of the last fortnight that needs it
```

## What the dream is, and is not

The dream is a proposal. Your signature (`day sign`) and your notes are the facts; a draft is never one,
however many times the model agrees with itself. No reader derives anything from a draft: not a stay,
not a person, not a promise. You confirm a sentence by confirming the lines it rests on, in a signed day;
a sentence that rests on nothing is confirmed by nothing but you writing it down yourself.

The dream never writes a note, a signature or a review. It writes one `draft` line, source
`model:<name>`, and nothing else. Dreaming a day again writes a new line whose `supersedes` names the
one before; the earlier text stays in the record and the Day lists its id. Nothing is edited and nothing
is deleted.

## The policy entry

Sending a day to a model is a crossing like any other, so it is governed by `policy/crossing.json`
([ADR 0016](adr/0016-tier-crossing-policy.md), [ADR 0022](adr/0022-the-records-home.md)). The dream
needs a `dream` entry:

```json
{"hermes": {"max_tier": 2},
 "mcp": {"max_tier": 1},
 "dream": {"max_tier": 2, "until": "2026-12-31", "model": "qwen2.5-7b-instruct"}}
```

- `max_tier` is the ceiling the day is read under. The model sees only lines at or under it: with 2,
  the stays, photos, calendar, notes and messages; with 1, no note and no message at all, since those
  are tier 2; tier 3 (health, money) only when you write 3.
- `until` is the last day the entry holds. From the next day it counts as `max_tier` 0 and the dream
  refuses, as every expired entry does; `logbook doctor` names it.
- `model`, optional, is the one model the day may go to. When the entry names one, it is the model used,
  and a `LOGBOOK_DREAM_MODEL` that says otherwise is refused: the entry is a ceiling, not a default.

No entry, or an expired one, and `dream` refuses in one sentence saying what to write. Nothing is read
and nothing leaves the machine. `doctor` lists the entry on its `crossing` line as it lists every
ceiling: `dream 2 until 2026-12-31 model qwen2.5-7b-instruct`.

**The draft's tier** is the highest tier among the lines the model actually read, not the ceiling and
not the lines it cited (SPEC §4: derived data inherits the highest tier of its evidence, and the
evidence of a draft is everything it read). A day of locations and photos dreamed under a ceiling of 2
is a tier-1 draft; the same ceiling over a day with a note is tier 2, and is sealed as tier 2 is in a
record that seals.

## The endpoint

Any OpenAI-compatible chat completions endpoint, through three variables; a cloud model today and a
local one tomorrow is a change of variables, not of code. No SDK is involved: one JSON request over the
standard library, a timeout of two minutes, and one retry when the connection fails or the server
answers 429 or 5xx.

| Variable | What it is |
|---|---|
| `LOGBOOK_DREAM_ENDPOINT` | the URL. `https://api.example.org/v1/chat/completions` in full, or the base a server prints (`http://127.0.0.1:8080` or `http://127.0.0.1:8080/v1`), which gets `/chat/completions` appended |
| `LOGBOOK_DREAM_MODEL` | the model's name as the endpoint knows it; the policy's `model` wins when the entry names one |
| `LOGBOOK_DREAM_KEY` | the bearer token, optional; a local `llama-server` needs none and gets no header |

The schedule's environment file, `~/.config/logbook/sync.env`, is where these live for the morning run
([the schedule](schedule.md)); set them in the shell to try by hand.

## What the model sees

The day's material is built from the Day reader under the entry's ceiling, never from raw lines above
it: the nights either side, the stays and moves with what attached to each and who was there, the
flights, what the calendar planned where the track has nothing, the health line when tier 3 is allowed;
then the day's messages by counterpart, how many and, since a message in the reading is under the
ceiling, their text; the notes in full; the commitments on the day; and the note you wrote when you
signed it. Every item carries a reference (`L1`, `L2`, ...) that stands for one line id of the day.

`--show-prompt` prints what is sent: the prompt ([docs/dream-prompt.md](dream-prompt.md) explains it)
and the material as JSON. The prompt says which language to write in: the language most of the day's
own text is in, decided by counting each language's commonest words over the notes, messages, titles
and subjects of the day (English, Norwegian, German, French and Spanish are told apart; English when
nothing decides it). The draft records it as `language`.

## The evidence rule

The model answers with segments, each a sentence or a few with the references it rests on, or marked
unsupported. Before anything is written:

- every reference is checked against the day. A reference the material gave becomes the line's id in
  the draft; a reference the day does not have, or a segment with none, makes the segment
  `unsupported`.
- a segment without text is dropped.
- when more than 30 % of the segments are unsupported (`UNSUPPORTED_SHARE`), the answer is refused and
  nothing is written. A model that mostly makes things up writes nothing into the record.

The draft line holds the segments and the ids, never the prompt, the material or the day's text the
model was shown. Its `extra` says which prompt wrote it (`dream-day/1`), which part of the dream each
segment belongs to (`day`, `threads`, `questions`, `people`, `promises`) and the digest of the ids it
read, which `--catch-up` compares.

On the Day, each segment prints with its evidence after it, the ids shortened; an unsupported one is
set apart with a leading `~` and the word `unsupported`, never run into the prose around it and never
as a fact. A reader that finds an evidence id that is not on the day marks the segment unsupported and
says why; a segment of neither documented shape is unsupported and the line is said to be malformed.

```
  draft         model:qwen2.5-7b-instruct · read at bb97e90d · 5 lines · dreamed 2×, last on 2026-06-14 · 1 unsupported
      day       A morning at home, then the afternoon aboard Solvind on the fjord.  […000000a1, …000000a2]
      day       You wrote that the engine sounded right for the first time since May.  […000000a4]
      question  What made the engine sound right this time?  […000000a4]
    ~ question  Was the evening alone what you wanted?  unsupported
      people    Ola Nordmann was aboard in the evening.  […000000a4]
```

`day --no-dream` leaves the draft out; `day --json` carries it under `draft`, the key there only on a
day that has one, so the Day's object is otherwise what it was: the line, the model, when it was written, what it read, the segments each with `supported`, its
`evidence`, its `part` and `why` when a reader found it wanting, `supersedes`, the `earlier` drafts'
ids newest first, how many times the day was `dreamed` and the day it was `last`. `serve` shows the
same above the timeline, an unsupported segment a muted block marked with the word.

## The re-dream rule

A draft names the head it read (`read_head`) and how many lines of the day it read (`read_count`).

- `dream day DAY` on a day that has a draft writes a new one whose `supersedes` names the standing
  draft; the Day then says `dreamed 2×` and lists the earlier id. The same model at the same head
  writes nothing and says so (RFC 0036 rule 1); since writing a draft moves the head, that happens
  only when the record has not moved since the draft was read, as when a write failed half-way.
- `dream --catch-up [--days N]` looks at each of the last N days before today (14 by default) and
  dreams it when it has no draft, or when its lines under the ceiling today are not what the standing
  draft read: a different count, or a different set of ids. A day unchanged is skipped and nothing is
  sent for it. One line per day says what happened: `dreamed` with the line's seq and why, `unchanged`,
  `empty` (nothing logged under the ceiling), or `refused` and why. The exit status is 1 when any day
  was refused, so the schedule's run can say so; a policy or endpoint refusal is said once, before any
  day, exit 2.

The whole dream, reading the day, the model's turn and the write, runs inside the record's writer lock
([the commands](commands.md), one writer at a time), and the head is read again before the line is
appended: a head that moved under the reading is the record's `HeadMoved`, one sentence, and nothing
is written; dream the day again.

## What a morning looks like

```
$ logbook dream --catch-up
2026-06-12  unchanged since #5431
2026-06-13  dreamed   #5440 · 3 lines now, 2 when last dreamed · 6 segments, 1 unsupported
2026-06-14  dreamed   #5441 · no draft yet · 5 segments
2 dreamed · 1 unchanged
```

Then `logbook day 2026-06-14` shows the draft above the timeline; read it, write your own note, and
sign the day. The schedule change that runs this at 06:00 is a separate change; until then, run it by
hand or from your own schedule.
