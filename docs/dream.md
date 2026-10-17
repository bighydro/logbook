# The dream

Every morning a model reads yesterday and writes one line about it: the day in a paragraph, the threads
it moved, two questions for your reflection, and proposals, the people it thinks were there, the
promises it thinks were made and the events it thinks the day held. Every sentence points at the lines it came from. The line is a `draft/v1`
([RFC 0036](rfcs/0036-goals-reviews-drafts-chapters.md), [the profile](https://github.com/bighydro/logbook/blob/main/rfcs/0036-draft-v1.md)),
and the Day shows it above your note, labelled as a draft.

```
logbook dream day 2026-06-13            # one day, one line
logbook dream day 2026-06-13 --dry-run  # ask the model, check the answer, write nothing
logbook dream journey trip:2026-06-15:2026-06-17   # a journey that has come home, or any day of it
logbook dream week 2026-W25             # a week whose Sunday is over; no week: the last one over
logbook dream --catch-up --days 14      # every day of the last fortnight that needs it, its weeks, the calls, the journeys
logbook dream --catch-up --since 2026-05-01   # the same, and every call since 1 May that has no synthesis
```

A journey and a week are dreamed by the same engine under the same entry and the same evidence rule
([Journeys and weeks](#journeys-and-weeks)).

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

## When the entry changes

A draft is derived through the `dream` entry, so it follows the entry, not the head ([ADR
0016](adr/0016-tier-crossing-policy.md), *Derived material follows the policy, not the head*). Lowering
the ceiling, letting `until` pass or removing the entry appends no line, so nothing in the record moves;
what changes is what the readers show.

- **Every draft names the entry it was dreamed under**: `extra.policy_version`, the SHA-256 (lowercase
  hex) of the RFC 8785 JSON of the entry's three deciding values, `{"max_tier": 2, "model": null,
  "until": "2026-12-31"}` (`model` and `until` `null` when the entry does not set them). The same values
  give the same version however the file spells them and whatever else the entry says.
- **A reader shows a draft only while the entry allows its tier.** A draft above the entry's `max_tier`
  today is not on the Day, not on `serve`'s Day page or its Journeys pages (a journey's draft, unit
  `journey`, is held to the same rule) and not through the MCP door, whichever head the record is at; an expired entry counts as `max_tier` 0, and so does a file with no `dream` entry, so
  nothing a model wrote is shown until the entry is back. The line stays in the record, as every line
  does. `day` says why in one row and nothing of the draft's text:

  ```
    draft         superseded by policy: tier 3, above max_tier 2 of the 'dream' entry; `dream --catch-up` dreams the day again under it
  ```

  `day --json` carries the same under `draft_withheld` (`line`, `seq`, `tier`, `max_tier`, `why`), a key
  present only then; `--no-dream` leaves it out. A reader through a gate of its own (`export site`, the
  MCP door) hides the draft without the row, as it hides every line above its gate; the door counts it
  among the lines it withheld, and its `line` tool refuses it naming the entry. A withheld draft's
  [proposed events](#proposed-events) are withheld with it: none is on the Day, `day sign` and `day
  reflect` list none of them, and `--accept` naming one is refused with the same reason. When an earlier
  draft the entry allows is shown in its place, its own proposals are the ones shown and listed. An
  event you confirmed before the entry changed stays in the record, your line and not the model's.
- **`doctor` warns** with a `drafts` line naming each day whose standing draft is above what the entry
  allows, its seq and tier, and what to do.
- **`dream --catch-up` dreams such a day again** under the entry as it is now: a standing draft above
  the entry's `max_tier`, or one dreamed under another version of the entry (a ceiling raised or
  lowered, an `until` moved, another model), is a change of the day as much as a new line is. The new
  draft supersedes the old one. A day the lowered ceiling leaves empty is `empty` and its draft stays
  withheld. An expired entry dreams nothing: the run refuses before any day, as it always has, and says
  that no reader shows a draft above it. A draft written before drafts named their entry has no version
  to compare, so only its tier is held against the entry.

## The endpoint

Any OpenAI-compatible chat completions endpoint, through four variables; a cloud model today and a
local one tomorrow is a change of variables, not of code. No SDK is involved: one JSON request over the
standard library, a timeout of two minutes, and one retry when the connection fails or the server
answers 429 or 5xx.

| Variable | What it is |
|---|---|
| `LOGBOOK_DREAM_ENDPOINT` | the URL. `https://api.example.org/v1/chat/completions` in full, or the base a server prints (`http://127.0.0.1:8080` or `http://127.0.0.1:8080/v1`), which gets `/chat/completions` appended |
| `LOGBOOK_DREAM_MODEL` | the model's name as the endpoint knows it; the policy's `model` wins when the entry names one |
| `LOGBOOK_DREAM_KEY` | the bearer token, optional; a local `llama-server` needs none and gets no header |
| `LOGBOOK_DREAM_TEMPERATURE` | the request's temperature, optional: unset sends `0.2`; a number from 0 to 2 is sent as given; `none` sends no temperature at all, for a hosted model that refuses one. Anything else is refused, naming the variable. A model that answers HTTP 400 about the temperature gets the error with `set LOGBOOK_DREAM_TEMPERATURE=none for a model that takes no temperature`; the dream never retries without one on its own |

The schedule's environment file, `~/.config/logbook/sync.env`, is where these live for the morning run
([the schedule](schedule.md)); set them in the shell to try by hand.

## What the model sees

The day's material is built from the Day reader under the entry's ceiling, never from raw lines above
it: the nights either side, the stays and moves with what attached to each and who was there, the
flights, what the calendar planned where the track has nothing, the health line when tier 3 is allowed;
then the day's messages by counterpart, how many and, since a message in the reading is under the
ceiling, their text; the notes in full; the commitments on the day; and the note you wrote when you
signed it. Every item carries a reference (`L1`, `L2`, ...) that stands for one line id of the day.
Each stay carries its `place`, the id a proposed event names it by, and the material ends with
`people`: the canonical people the day names, by `id` and `name`, the only people a proposed event
may hold.

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
model was shown. Its `extra` says which prompt wrote it (`dream-day/3`; `dream-day/1` drafts asked for
no events, and drafts before `dream-day/3` were not told that agents are not people), which part of the
dream each segment belongs to (`day`, `threads`, `questions`, `people`, `promises`) and the digest of
the ids it read, which `--catch-up` compares.

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
day that has one (and the entry allows, *When the entry changes*), so the Day's object is otherwise what it was: the line, the model, when it was written, what it read, the segments each with `supported`, its
`evidence`, its `part` and `why` when a reader found it wanting, `supersedes`, the `earlier` drafts'
ids newest first, how many times the day was `dreamed` and the day it was `last`. `serve` shows the
same above the timeline, an unsupported segment a muted block marked with the word.

## Proposed events

The record should be able to guess what you did and fill the calendar afterwards: a stay at a
restaurant from 19:30 to 22:10 with two photos and a recording Kari spoke in is a dinner with Kari. The
dream proposes such events beside its segments, and nothing more: a proposal is kept inside the draft
line, never written as an event line, and becomes one only when you accept it.

**What the model gives.** A sixth key of its answer, `events`, each `{title, start, end, place, people,
evidence}`: `start` and `end` as the material writes times, `place` the `place` of the stay it happened
at (a named place of `places.json` by its name, or an observed place by its id, `place:<lat>,<lon>`, as
`places review` names a cluster) or null, `people` ids from the material's `people`, `evidence` the
references it rests on.

**The check.** A proposal has no unsupported form, so where a segment would be marked a proposal is
dropped, and the drops are counted by why under the draft's `extra.dropped`:

| Dropped as | When |
|---|---|
| `unresolved person` | a person who is not one of the day's canonical people: a name instead of an id, an id the record does not resolve to a person (or no longer does, after a merge), the owner |
| `a time not on the day` | a start that is not on the day, an end not after the start, an event of 24 hours or more, a time that is not one |
| `a place not on the day` | a place the material did not give |
| `evidence not on the day` | a reference the day does not have, or none at all |
| `no title`, `not an event` | an empty title, an item that is not an object |

What holds is kept in the draft under `proposals`, kind `event`, the times in UTC, the references
turned into line ids ([the profile](https://github.com/bighydro/logbook/blob/main/rfcs/0036-draft-v1.md)):

```json
"proposals": [{"kind": "event", "title": "Dinner with Kari Nordmann",
               "start": "2026-06-10T17:30:00Z", "end": "2026-06-10T20:10:00Z", "place": "Bistro Eksempel",
               "people": ["019cadd3-6bc0-7dcd-9133-000000000001"],
               "evidence": ["019cadd3-…-0000000000b1", "019cadd3-…-0000000000b2", "019cadd3-…-0000000000b3"]}]
```

`dream day` prints them after the segments, numbered, and says how many were dropped and why:

```
  ? event 1   19:30–22:10  Dinner with Kari Nordmann · Bistro Eksempel · with Kari Nordmann  proposed  […000000b1, …000000b2, …000000b3]
  1 proposed event dropped: unresolved person 1
```

**Confirming one.** `day sign DAY` lists the standing draft's proposed events, numbered from 1, and
`day sign DAY --accept 1` writes the first: one `event/v1` line, the profile every calendar adapter
writes ([RFC 0009](https://github.com/bighydro/logbook/blob/main/rfcs/0009-event-v1.md)), made by the
calendar adapter's own mapping from the entry a calendar named `logbook` would hold for its fields: the
UID `<draft id>/<number>` (the line's `raw_id`), the span in the record's zone, the title, the place's
name and its coordinates (`extra.location`; an observed place gives the coordinates alone), and each
person as an accepted attendee by their email address, their label as the name. So the line is byte for
byte what the calendar adapter writes for those fields, but for two things: `source` is `owner`, since
you confirmed it and the model only proposed it, and `extra.from` names the draft it came from. A person
the record knows by no address is an attendee by the ref it does know. The tier is the profile's, 1, as
every calendar entry's. The event and the signature are written under one hold of the writer lock, the
proposals read again inside it. `day reflect DAY --sign --accept N` does the same, the events numbered
after the reflection's own proposals ([the signed day](signed-day.md#events-the-dream-proposed)).
Nothing is written without `--accept`: not by `dream`, not by `day`, not by `serve`.

**On the Day.** A proposed event is a row of the draft, `?` and `proposed` in text, greyed on the
`serve` page; once accepted it says `confirmed as #seq`, and the event itself sits among the day's
events in the timeline, where it places its attendees as any calendar entry held at the stay does. A
proposal whose lines were retracted since is marked unsupported and cannot be accepted. Dreaming the day
again proposes afresh; an event you confirmed stays in the record whatever the next draft says. The
proposals follow the policy with their draft: a draft the `dream` entry no longer allows shows and
offers none of them ([When the entry changes](#when-the-entry-changes)).

Sending a confirmed event to an external calendar would be a crossing, and nothing does it yet.

## The re-dream rule

A draft names the head it read (`read_head`) and how many lines of the day it read (`read_count`).

- `dream day DAY` on a day that has a draft writes a new one whose `supersedes` names the standing
  draft; the Day then says `dreamed 2×` and lists the earlier id. The same model at the same head
  under the same entry writes nothing and says so (RFC 0036 rule 1); since writing a draft moves the
  head, that happens only when the record has not moved since the draft was read, as when a write
  failed half-way.
- `dream --catch-up [--days N]` looks at each of the last N days before today (14 by default) and
  dreams it when it has no draft, when its standing draft is above the entry's `max_tier` today or was
  dreamed under another version of the entry (*When the entry changes*), or when its lines under the
  ceiling today are not what the standing draft read: a different count, or a different set of ids.
  A day unchanged is skipped and nothing is sent for it. One line per day says what happened: `dreamed` with the line's seq and why, `unchanged`,
  `empty` (nothing logged under the ceiling), or `refused` and why. Then each call of the last 7 days
  (fewer when `--days` is under 7) that no model has synthesized yet, or whose synthesis was made under
  another version of the entry, is synthesized, one line each, `synthesized` or `refused` ([the
  synthesis of a call](transcript-synthesis.md#the-week-the-close-covers)); a call above the ceiling,
  or without its text, is counted in the closing line and never sent. An older call is never sent: the
  ones without a synthesis are counted in one line after the closing one, naming `transcript synthesize
  --day DAY` and `dream --catch-up --since DAY`, and `--since DAY` is how you ask for the calls from
  `DAY` on (the days dreamed are still the last N). The exit status is 1 when any day or call was
  refused, so the schedule's run can say so; a policy or endpoint refusal is said once, before any
  day, exit 2.

The whole dream, reading the day, the model's turn and the write, runs inside the record's writer lock
([the commands](commands.md), one writer at a time), and the head is read again before the line is
appended: a head that moved under the reading is the record's `HeadMoved`, one sentence, and nothing
is written; dream the day again.

## Journeys and weeks

Two more units for the same engine, under the same `dream` entry, the same endpoint and the same
evidence rule, each one `draft/v1` line ([the profile](https://github.com/bighydro/logbook/blob/main/rfcs/0036-draft-v1.md)):
a **journey**, unit `journey`, and an ISO **week**, unit `week`. Neither is ever a fact: you star a
photo, name a journey (`logbook add --trip ID "NAME"`) and review a goal (`goal review`) yourself.

**A journey** is a trip as `show trips` derives it ([ADR 0019](adr/0019-trips-are-derived.md)): a run of
nights away from home, its id `trip:<first day>:<last day>`, its return day the day after its last
night. It is dreamed once it has **closed**: its return day is before today and the night after it was
spent at home. A journey still away, or whose last night the record does not yet place, is refused
(`has not closed`), so a half trip is never sent. The model reads the journey whole through the entry's
ceiling: every line of its days, first day to return day; each day's timeline with the hours of each
stay; the hours at each place; the flights; the canonical people confirmed on it; the messages counted
by counterpart, never their text; the notes; the decisions of its calls as their standing syntheses
have them, read through the same rule as the Day reads them; the promises made on its days; its
photos, the ones already starred apart; and your name for it, when you gave one. It writes the trip as
a whole, the days that stood out, the places, who was on it, what was decided and promised, the photos
it would star (`extra.star`, never one starred already) and one name it proposes (`extra.name`; a
second is dropped and counted). `subject` is the journey's id, then the ids of the lines the trip rests
on (each night's stay, its flights, its companions'), so the Journeys reader finds it by its id.

**A week** is an ISO week, Monday to Sunday, `2026-W25`. It is dreamed from its seven days once they
are over: `dream week` refuses a week whose Sunday is today or later, and with no week named dreams the
last one whose Sunday is over. It reads the week's lines under the ceiling and **the seven days'
drafts** the entry allows today (their supported sentences, given as a model's words, with the lines
they rest on); a day that has lines and no such draft refuses the week until it is dreamed. It writes:

- `time`: where the week went, by place, person and thread;
- `energy`: sleep and training, when the health lines cross the ceiling (they are tier 3), else
  nothing: the material says `no data`;
- `people`: who moved against the week before (each canonical person's contacts this week and the
  week before, the largest changes either way) and the promises open both ways;
- `goals`: for each goal open on the Sunday, a review it proposes, one of the five dispositions, with
  the lines of the week that show it (`extra.goals`); a goal item without such lines, of no goal, of
  no disposition, or of a goal named twice is dropped and counted;
- `next_week`: one proposal for next week, never more (a second is dropped and counted);
- `personal`: the one place for anything personal.

The prompt says it in so many words: never moralise. No praise, no blame, no lesson.

**Numbers are the code's.** Every figure the model is given is computed from the lines and carries
their references: the hours at a place from the stays' first and last lines, clipped to each day (the
Day's stays); the counts of messages in a direct chat, calendar entries attended, calls and recordings
spoken in (the people reader's channels: a person's `contacts`, the same count for a mover), and the
days together the with module confirms (a day, never hours: it puts someone at a stay, not beside you
for all of it); the threads (each chat, mail subject, calendar title and recording title, their time
clipped to the week); the nights that ended on the week's days as the Day counts them (Monday's began
the Sunday before, whose evening's sleep lines are read for it), their mean asleep hours, and the
workouts. The week keeps them under `extra.numbers`, each with its line ids. A sentence that writes a
figure no item it cites gives (rounded, added up, estimated, or a number a day's draft wrote) is
**marked unsupported** before anything is written and counted under `extra.marked`, so it counts
against the 30 %. A figure is digits, glued to a unit or not (`45min`, `7,5t`), or a number written
in words in English or Norwegian (`three`, `tre`); dates (`2026-06-16`, `16.06.2026`, `16/6`, `16
June`), clock times (`19:30`, `kl. 19`, `9am`), ISO weeks and the unit's own years are not numbers.
What the rule checks is that the figure is one the cited lines give, not that it is the right one of
them: `3 calls` passes when the person's item gives `contacts: 3`, and a small number is lent by many
items. The words around a figure are the model's; the figure is the code's.

The journey's and the week's segments are held strictly to the evidence rule: a sentence that cites
one reference the material did not give is unsupported, whatever else it cites.

**The readers.** `show trips` and `show trip ID` carry each journey's standing draft after its rows,
`draft` or `draft_withheld` under `--json` (keys there only on a journey that has one); `day` of a Sunday carries the week it closes, after the
Day, `week`, `week_draft` and `week_draft_withheld` under `--json` (keys there only on a Sunday whose
week has a draft; `--no-dream` leaves them out). Both follow the entry as the day's draft does ([When
the entry changes](#when-the-entry-changes)): above it, one row, `superseded by policy`, and nothing of
the text. The Library's Journeys page already reads a journey's draft through the same Journeys
reader (`journeys.draft_of`), its parts named and, under `proposed`, the name and the photos it
proposes; the Day page shows the week's in a later change.

`read_count` is the unit's own lines the model read, under the ceiling (the journey's days', the
week's seven days'), as for a day (RFC 0036 rule 5). What it read beside them (a call's synthesis for a
journey; for a week, the seven days' drafts, the goals and reviews it gives, the lines of the promises
open on its Sunday, the week before's contacts of the people it names as movers, and Monday's night's
sleep lines from the Sunday evening) counts toward the tier and the digest, and how many under
`extra.read_beside`; none of it is ever cited.

**The re-dream rule is the day's.** `dream --catch-up` dreams, after the days, each week whose seven
days are all among the days it looks at, then, after the calls, each journey whose return day is one of
them and that has closed. So the close of a Sunday (the 06:00 run on the Monday) dreams the week that
Sunday ended, and the first 06:00 run after a journey comes home dreams the journey. After that a run
leaves each alone while it is unchanged, and dreams it again, superseding the standing draft, when what
it would read under the ceiling today is not what it read (another count, another set of ids: a day of
the week dreamed again is one), when the standing draft is above the entry's `max_tier` today, or when
it was dreamed under another version of the entry. `dream journey ID` and `dream week` dream it again on
demand; the same model at the same head under the same entry writes nothing. `doctor`'s `drafts` line
still names days only.

A week is read as its Sunday stood: the goals and their reviews dated up to it, and the promises open
on it (one marked done or signed off later was open then), so what you do in a later week never
changes it. Three things to know. A journey's id is its first and last night, so a late sync that
moves one makes it another journey: it is dreamed under the new id and the draft of the old one is no
longer shown. A catch-up of one or two days may not see a journey whole enough to find it (a last
night in transit on an overnight flight); `dream journey` finds it on demand, and the default fortnight
always does. And "today" is this machine's date, as for the days: a run between midnight and a
`day_start` of 06:00 counts the day before as over.

```
$ logbook dream --catch-up
2026-06-21  dreamed   #5502 · no draft yet · 4 segments
2026-W25  dreamed   #5503 · its Sunday is over, no draft yet · 7 segments
trip:2026-06-15:2026-06-17  unchanged unchanged since #5480
```

## What a morning looks like

```
$ logbook dream --catch-up
2026-06-12  unchanged since #5431
2026-06-13  dreamed   #5440 · 3 lines now, 2 when last dreamed · 6 segments, 1 unsupported
2026-06-14  dreamed   #5441 · no draft yet · 5 segments
2 dreamed · 1 unchanged
```

Then `logbook day 2026-06-14` shows the draft above the timeline; read it, write your own note, and
sign the day, with `--accept N` for each proposed event that happened. The schedule change that runs this at 06:00 is a separate change; until then, run it by
hand or from your own schedule.
