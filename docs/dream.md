# The dream

Every morning a model reads yesterday and writes one line about it: the goodnight story, an answer to
each of your lenses, the threads it moved, what the day shows was learned and decided, the ideas it
moved, one question for your reflection, and proposals, the people it thinks were there, the promises it
thinks were made, the photo of the day, the events it thinks the day held and the lines it thinks belong
to one of your ideas or orgs (*The dream learns*, below). Every sentence points at the lines it came from. The line is a `draft/v1`
([RFC 0036](rfcs/0036-goals-reviews-drafts-chapters.md), [the profile](https://github.com/bighydro/logbook/blob/main/rfcs/0036-draft-v1.md)),
and the Day shows it above your note, labelled as a draft.

```
logbook dream day 2026-06-13            # one day, one line
logbook dream day 2026-06-13 --dry-run  # ask the model, check the answer, write nothing
logbook dream day 2026-10-21 --evening  # today so far: the draft says `the day so far`
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

You write each entry yourself; a new record names only `mcp`, at 1.

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
  nothing a model wrote is shown until the entry is back.
- **A draft is held to the entry it was written under.** A person's draft (`dream person`, unit `person`)
  is written under the `relationship` entry, not this one ([the relationship reader](relationship.md)), so
  every reader holds it to that entry: past its `until`, without an `until`, without the entry, or above its
  `max_tier` today, a person draft is withheld from the door, stays out of a crossing package and is named by
  `doctor`, whatever the `dream` entry allows. Every other unit (day, journey, week, a call's synthesis)
  follows the `dream` entry, as before. The line stays in the record, as every line
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
may hold. dream-day/4 adds `photos` (the day's photos, the owner's own camera first, then the starred,
then by time, each its reference, clock, `provenance` and `starred`, twelve at most), and, under the
same ceiling and only when the day is dreamed (a catch-up's comparison never pays for them): `for`,
what the day was meant for (RFC 0043 §4.1), its `chapter` (the standing chapter the day is in, its
`name`, its `rules` in the owner's words, `from` and `to`) and its `goals` (the open standing goals,
`id` and `text`), under one key so a day's material is never taken for a month's or a chapter's; `named` (the ideas and orgs the owner named, `id`,
`kind`, `name`, forty of each at most, by name: the only ids an idea or a link may name) and `lenses`
(`id` and `text`, from `policy/questions.json`, below). Each is read from its own kind through the
index, a few lines each; never the touches the Ideas shelf sweeps.

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
model was shown. Its `extra` says which prompt wrote it (`dream-day/4`; `dream-day/1` drafts asked for
no events, drafts before `dream-day/3` were not told that agents are not people, and a `dream-day/3`
draft has a `day` paragraph and two questions where dream-day/4 has the story and one), which part of
the dream each segment belongs to (`story`, `lens:<id>`, `threads`, `learned`, `decision`, `ideas`,
`questions`, `people`, `promises`, `photo`; a `dream-day/3` draft's `day` still reads), the digest of
the ids it read and the count and digest of the ids `--catch-up` compares (*The re-dream rule*).

On the Day, each segment prints with its evidence after it, the ids shortened; an unsupported one is
set apart with a leading `~` and the word `unsupported`, never run into the prose around it and never
as a fact. A reader that finds an evidence id that is not on the day marks the segment unsupported and
says why; a segment of neither documented shape is unsupported and the line is said to be malformed.

```
  draft         model:qwen2.5-7b-instruct · read at bb97e90d · 5 lines · dreamed 2×, last on 2026-06-14 · 1 unsupported · 1 proposed link
      story     You spent the morning at home, then the afternoon aboard Solvind on the fjord.  […000000a1, …000000a2]
      story     You wrote that the engine sounded right for the first time since May.  […000000a4]
                Tomorrow: two entries, the first at 09:00.
      lens:boat The new reefing lines ran cleanly; this is an inference.  […000000a4]
      lens:money — the day doesn't answer this
    ~ question  Was the evening alone what you wanted?  unsupported
      people    Ola Nordmann was aboard in the evening.  […000000a4]
      photo     The only photo from the water.  […000000a5]
    ? link 1    Crew list  proposed  […000000a6]
```

`day --no-dream` leaves the draft out; `day --json` carries it under `draft`, the key there only on a
day that has one (and the entry allows, *When the entry changes*), so the Day's object is otherwise what it was: the line, the model, when it was written, what it read, the segments each with `supported`, its
`evidence`, its `part` and `why` when a reader found it wanting, `supersedes`, the `earlier` drafts'
ids newest first, how many times the day was `dreamed` and the day it was `last`. Since dream-day/4 a
day's draft also carries, on every day draft (empty or false for an older one): `evening` and
`read_until`; `lenses`, each `{id, text, answered}`; `entity` on each `ideas` segment; `links`, each
`{number, kind: link, entity, text, note, evidence, supported, why, kept}`; `kept` on each proposed
event beside `confirmed`; `since_signed` and `signed_seq`; `closing`, the story's last line as the
reader computed it, `{text, day, entries, first, lines}` or null; and `marked`, `dropped`,
`dropped_links`, `dropped_segments`, by why. `serve` shows the segments above the timeline, an
unsupported segment a muted block marked with the word; the Day page reads the new fields with RFC 0043
slice A, and until then shows the new parts' segments as it shows every segment.

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
- **Kept lines never make a day be dreamed again** (RFC 0043 §6 rule 4). What the catch-up compares
  leaves out the lines the close writes: a line whose `extra.from` names a draft of the day (an event
  accepted with `--accept`, a sentence or a link kept), and the reflection and its delegations. A star
  is the day's like any line (it changes which photos the material lists first).
  A dream-day/4 draft keeps the count and the digest of what it compared (`extra.compared_count`,
  `extra.compared_ids_sha256`); an older draft is compared by what it read, as before, until it is
  dreamed again.
- **After a signature, only a later line** (rule 5). On a signed day the catch-up, the 06:00 close's
  included, dreams the day again only when a line it compares arrived after both the standing
  signature and the standing draft, by `seq`: `1 line since you signed (#412)`. The new draft
  supersedes the standing one, the evening's among them. A line synced before the signature does not
  count: you signed what you saw.
- **A signed day with no late line is never dreamed again** (rule 6): `signed as #412, no line since`,
  unless its entry changed (the first bullet) or you ask, `dream day DAY`.
- **Today is never the catch-up's.** `dream day TODAY --evening` dreams today so far, writing
  `extra.evening: true` and `extra.read_until`, the moment it read up to; a day that is not today is
  refused with `--evening`. The morning's catch-up dreams the day again when lines arrived after the
  evening's draft, superseding it.

The whole dream, reading the day, the model's turn and the write, runs inside the record's writer lock
([the commands](commands.md), one writer at a time), and the head is read again before the line is
appended: a head that moved under the reading is the record's `HeadMoved`, one sentence, and nothing
is written; dream the day again.

## The dream learns (dream-day/4)

RFC 0043 slice B ([the Day page and its rhythm](https://github.com/bighydro/logbook/blob/main/rfcs/0043-the-day-page.md),
§4.3–4.8, §6, §7, §12, §13.2–13.4). The prompt's parts, in order, each a list of segments with evidence:

| Part | What | The code's rule |
|---|---|---|
| `story` | the goodnight story: five or six sentences, second person, past tense, calm, concrete, ending where the day ended | at most six kept; its last line is the reader's, `Tomorrow: two entries, the first at 09:00.`, from the next day's timed calendar entries, or nothing; never the model's |
| `lens:<id>` | one answer to each lens (`"ask": "day"` in `policy/questions.json`, [RFC 0027](rfcs/0027-reflection.md), at most five) | one segment per lens; a lens answered without evidence is dropped, and a lens with no segment is printed by the reader, `— the day doesn't answer this` |
| `threads` | the threads the day moved | as before |
| `learned` | what the day shows was learned | |
| `decision` | what the day shows was decided | |
| `ideas` | an idea the day moved, with `entity` its id | dropped unless the id is an idea of the material's `named`; kept under `extra.ideas`, `{segment, entity}` |
| `questions` | one question for the reflection | the first kept; dream-day/3 asked two |
| `people`, `promises` | as before | |
| `photo` | the photo of the day: the owner's own camera first, the starred first, with a one-line reason | one, resting on exactly one photo of the material, else dropped |

Beside them, `events` as before and `links` (`draft/v1` amendment 2): a line of the day that belongs
to an idea or an org of `named`, `{kind: link, entity, text, evidence, note?}`, four at most; one that
names an id the material did not give, has no text or no evidence of the day is dropped and counted
under `extra.dropped_links`. An event whose title, or a link whose text or note, puts a number beside a
canonical person's name is dropped too, never kept, and counted as `a number beside a person` under
`extra.dropped` (an event) or `extra.dropped_links` (a link). A link is numbered after the events among the draft's `proposals`, so an
event's number, and the `raw_id` it is accepted under, is what it would be without it. Keeping a link,
a sentence or the photo of the day (as a star with its note) is RFC 0043 slice C: this slice writes
none of them.

Every rule of the evidence rule holds, and the 30 % refusal is counted over what is kept. The number
rule of the journey and the week now holds for a day too (`dream.hold_numbers`): a figure a sentence
writes that the items it cites do not give marks it unsupported, counted under `extra.marked` (a
note's and a promise's own figures count, as a stay's do). And, as for a month and a chapter, no number
stands beside a person, pencil included (`dream.hold_names`): a sentence that names a canonical person
(the full name, or the first name) and writes a figure, whatever its evidence and whether or not the
number rule marked it already, is **held**: its words are dropped before the line is written, its slot
stays as an unsupported segment whose text is the reason, `held: a number beside a name`, the evidence
it cited, when it cited any, is kept under `extra.held` (`{segment, evidence}`, the segment's place from
1), and it is counted under `extra.marked` as `a number beside a person` (a sentence the number rule
marked first is counted under both keys; the 30 % refusal counts it once). A model's sentence that
reads as the reason itself is held the same way, never kept as prose. No reader prints the model's
words, since the line does not hold them: `day`, the Day page and `export site --with-drafts` show `~ held: a number
beside a name  unsupported` in their place. The draft's tier is the highest among every line it read:
the day's, and the chapter, goal and entity lines it was given, so a tier-3 goal makes a tier-3 draft
(when the entry lets tier 3 cross at all). The prompt carries RFC 0043 §7's voice rules word for word (without the RFC's `[main]` mark), and
`--show-prompt` prints it.

Where this slice and RFC 0043 as written differ, the RFC is a draft and this page is what the code does:
the parts are §13.4's with `photo` last (§13.4 has no photo part; §12 proposes the photo of the day); a
link is `{entity, text, evidence, note?}`, where §13.3 has `{entity, ref, evidence}`, so slice C finds
the observed reference from the evidence line when it keeps one; and *not yet kept* is matched both
ways: a proposal of the standing draft by its `raw_id`, as `--accept` writes it, and one of any other
draft of the day by its fields, an event's title and span, a link's entity and evidence, as §6 rule 5
says, since a `raw_id` names its own draft. Either way the proposal carries `kept` and `confirmed`, the
line that kept it, so `--accept` refuses it (`confirmed already`) and the page shows it confirmed.

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

**One stale question a week.** Beside what the model writes, the code asks at most one question a
week about the stalest holding or idea (RFC 0037 §10.6): an org or an idea whose status has aged
past the reader's limit as of the Sunday (`hold` over three years and `exploring` over two by default,
and any status `stale_days` in `policy/entities.json` names), its last touch counted as the Manifest
and the Ideas shelf count it, so an org that mailed you last month is not stale. The stalest is
asked:

```
    ? question  Harbour Map App: still exploring? Nothing since May 2023.  asked once
```

It is a proposal kept in the week's draft (`extra.question`: the entity, its label, its status and
the status line, since when, the text, the lines it read), never a sentence of the draft, never a line of its own and
never a status: your answer, if you give one, is `logbook status idea "Harbour Map App" …`, which
restarts the clock, and nothing else happens when you do not. It is asked once: an entity a draft of
another week asked about, under the status it still stands at, is passed over for the next stalest;
when nothing is stale, nothing is asked. It never names an entity above the draft: only one whose
status line, entity lines and touches are under the `dream` entry's ceiling and at or below the tier
the week's own reading gave the draft is a candidate, so an org, whose status is tier 3, is asked
about only in a week whose draft is tier 3 already. Nothing of it is sent to the model. The lines it
read are named in the question (`read`) and kept out of `extra.read_ids_sha256`, so answering it, or
naming an entity, never sends the week to the model again by itself; a `policy/entities.json` that
does not read asks nothing, and the week is dreamed as ever.

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

## Months

`logbook dream month [YYYY-MM]` drafts a calendar **month** once it is over (unit `month`, subject
`2026-06`), under the same `dream` entry, the same endpoint and the same evidence rule as the week; with
no month named, the last month that is over. A month whose last day is today or later is refused (`which
is not over`).

**Told from the days you signed.** The month's paragraph is told from the days you signed (`day sign`)
and from nothing else of the record's words: each signed day's standing draft the entry allows, its
supported sentences only, given as a model's words with the lines they rest on, and your own words on
the day, its reflections (`day reflect`) and the note you signed it with. A raw line's text the day
drafts did not use is never sent. A day you did not sign is not told; the month says how many you
signed of how many days. A month with no signed day under the ceiling has nothing to tell: `dream
month` refuses it and `--catch-up` counts it `empty`.

It writes:

- `month`: the month told back, a short paragraph;
- `where`: where it went, from figures the code computes from the month's lines: the places with their
  hours and days (the week's count), the nights by class (`home`, `away`, `aboard`, `in transit` as the
  year's poster classes them, and `unknown` for a night of a day the record holds nothing of; `no data`
  when the month has no stay at all), and the people **in the order of the time spent together** (the
  days the with module puts them at your stays, then their contacts): **names only**. No count is given
  beside a person, none is kept in the line, a day draft's sentence that puts one beside a name is not
  passed on, and a sentence of the month that writes a figure where it names a person is held, whatever
  it cites: its words are dropped and its slot reads `held: a number beside a name`, unsupported
  (`a number beside a person` under `extra.marked`);
- `goals`: for each goal open on the month's last day or reviewed in it, what the month shows, from
  what the code computed: your reviews dated in the month, the standing verdict on the last day, and the
  days a line of the month **touched** the goal, as dates and never a count (a goal's words may name a
  person): a contact with a person, or a stay at a named place,
  that the goal's own words name ("Keep the berth in Vollen, as agreed with Ola Nordmann" is touched by
  the call and the dinner with Ola Nordmann). Kept under `extra.numbers.goals`; the month proposes no
  verdict, `goal review` is yours;
- `next_month`: one proposal for next month, never more (a second is dropped and counted);
- `question`: one question about the month for you to answer, never more.

```
$ logbook dream month 2026-06
2026-06: dreamed as #5620 draft/v1 · model:qwen2.5-7b-instruct · tier 2 · 1188 lines read at 4f0c2a91 · 6 segments
    month     A month at home and at the office, with Zürich in the middle.  [9c1f04a2]
    where     173.8 hours at Home.  [0b44e1d0]
    where     Mostly with Ola Nordmann, then Kari Nordmann.  [5d2e8a17]
    goals     The berth came up on the call and at the dinner.  [77a0c3e9]
    proposal  Send Kari Nordmann the harbour map.  [9c1f04a2]
    question  Is the berth in Vollen still what you want for next summer?  [9c1f04a2]
    signed    3 of 30 days
    hours     Home 173.8 h · Office 58.0 h
    nights    home 12 · away 3 · unknown 15
    with      Ola Nordmann · Kari Nordmann
    goal      “Keep the berth in Vollen, as agreed with Ola Nordmann.” · touched on 2026-06-11, 2026-06-16
  a draft is a proposal: your signatures, your notes, your reviews and your chapters are the facts
```

`read_count` is the month's lines under the ceiling and the signatures of its days; the day drafts and
the goals and reviews dated before the month are read beside them, toward the tier and the digest. The
promises, the people who moved and the stale question of the week are not read: each walks more of the
record than a month.

## Chapters

`logbook dream chapter [ID]` drafts a **chapter** you named (`chapter open`, [RFC 0036's chapter
profile](https://github.com/bighydro/logbook/blob/main/rfcs/0036-chapter-v1.md)), open or closed (unit
`chapter`). `ID` is the id of any of its lines, its seq (`12` or `#12`) or its name, as `chapter list`
prints them; with none, the chapter yesterday was in, else the one that closed last. An open chapter,
or one closed ahead of its last day, is read up to yesterday.

**From the drafts it spans, never the raw lines.** A chapter may run for years, so it is never read line
by line. It reads the chapter as you named it (its name, its stretch and its `rules`, your words on what
it is for), then the **month drafts** for the months it spans, and, for a month no month draft covers,
the **week drafts** of its weeks (at most 24 months and 12 weeks, the latest), each draft's supported
sentences only, and a sentence only when every line it rests on is a line of the chapter's days under
the ceiling and it puts no figure beside a person (a week's `people` sentence does): a June draft given to a chapter that began on the 20th gives only what rests on the 20th
and after. It writes:

- `arc`: the chapter's arc, in the order it was lived, from the months and the weeks;
- `rule`: what it was for, said back from its rules, never judged against them;
- `held`: what it held, from figures the code computes: its days, the days you signed, the months and
  weeks drafted;
- `closed`: what it closed: the goals you reviewed `done`, `let go` or `superseded` on one of its days,
  and its own close.

The same rules hold: every sentence cited or marked, more than 30 % unsupported refused, no figure the
items do not give, no figure beside a person (the sentence held, its words dropped). A chapter is a tier-2 line, so under a ceiling of 1 it
is refused before anything is read. Its `subject` is the ids of its lines, the standing one first, so
`dream chapter --json` and a later page find the draft by any of them; closing a chapter writes a new
line, which is a change, so the chapter is dreamed again. A chapter no month or week draft says anything
of is refused (`dream month` or `dream week` first) and counted `empty` by the catch-up.

**The catch-up.** After the days, the weeks, the calls and the journeys, `dream --catch-up` looks at
each month whose last day is among the days it looks at, so **the first 06:00 close of a month dreams
the month before**, then at each chapter whose last day, or the line that closed it, is among them, so a
chapter is dreamed **when it closes**, and at each closed chapter that spans the month it looks at, so
a chapter dreamed from its week drafts is dreamed again from its month draft once that exists. A
chapter whose line is above the entry's `max_tier` is held back there (`empty`, never `refused`): the
policy doing its job is not a failed close. After that each is left alone while it is
unchanged and dreamed again, superseding its draft, by the week's rule: what it would read today is not
what it read (a day signed since, a day or a month dreamed again), the draft above the entry's
`max_tier` today, or dreamed under another version of the entry. An open chapter is never caught up,
only dreamed on demand.

```
$ logbook dream --catch-up
2026-06-30  dreamed   #5618 · no draft yet · 3 segments
2026-06  dreamed   #5620 · its last day is over, no draft yet · 6 segments
chapter Ashore, fixing things  dreamed   #5621 · closed, no draft yet · 4 segments
```

**JSON.** `dream month --json` and `dream chapter --json` print the standing draft after the write as a
reader shows it (`draft`, or `draft_withheld` when the entry no longer allows its tier), its segments
with their parts and evidence and, under `numbers`, what the code computed; under `--dry-run`, the
payload that would have been written. No page shows them yet: the timeline's month and life zooms will,
after the 1.0 tag.

## What a morning looks like

```
$ logbook dream --catch-up
2026-06-12  unchanged since #5431
2026-06-13  dreamed   #5440 · 3 lines now, 2 when last dreamed · 6 segments, 1 unsupported
2026-06-14  dreamed   #5441 · no draft yet · 5 segments
2 dreamed · 1 unchanged
```

Then `logbook day 2026-06-14` shows the draft above the timeline; read it, write your own note, and
sign the day, with `--accept N` for each proposed event that happened. With the schedule installed ([the schedule](schedule.md)), the 06:00 close runs it for you.
