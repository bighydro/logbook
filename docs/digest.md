# The digest

`logbook digest [YYYY-MM-DD] [--json | --markdown]` is the day in at most 25 lines: what the owner
reads of it in the evening, not the Day itself. Its shape in three lines, the flights, the open
promises due within the week, the usual sources that had nothing to say, what the calendar holds
for tomorrow, and one closing question the owner can answer in a word. It is composed from the
readers that already exist — the Day, the promises, `sources --gaps` — and derives nothing of its
own; it writes nothing, not even the settings file a reader would create, and it sends nothing.
Who delivers it, and where, is a later decision; this command only says what the message would be.

```bash
logbook digest                       # today, as text
logbook digest 2026-06-10            # a Wednesday
logbook digest 2026-06-10 --markdown # the same lines as Markdown, for a message that renders it
logbook digest 2026-06-10 --json     # the whole sets behind the lines, every row with its line ids
```

## What it says, in order

1. **where** — the stays of the Day's timeline in order (a run aboard an asset as `aboard <asset>`,
   an unnamed stay as its coordinates with the nearest large airport's city), the first six and
   `…`, then where the night after was spent: `night at Home`, `night away, aboard Solvind`,
   `night in transit`. A day with no line at all is `nothing logged`.
2. **with** — the people the Day confirms present (declared in a note, speaking in a transcript,
   attending a timed calendar entry at the stay); never the owner, never a face in a photo or an
   attendee of an all-day entry, who are only proposed — `(1 proposed)` says how many are. A
   person proposed at one stay and confirmed at another is confirmed.
3. **attached** — how many of each kind attached across the day's rows (`1 event, 1 note, 3
   photos`), and how many lines fell inside no row (`2 unplaced`).
4. **flight** — the flights of the day from the `flight/v1` lines standing, as the Day lists them:
   `XY 561 OSL→ZRH  07:05–09:15`, with the evidence when it is not tracked; three at most, then
   `+N more flights`.
5. **due** — the open promises due on the day or within seven days after it, from the promises
   reader: the sentence as written, who said it (`you` for the owner), the due day and the phrase
   it was read from; three at most, then `+N more due this week`. A promise closed with
   `promises done` is out. A promises reader that judges its proposals (a model that reads them
   after the rules) puts the ids it holds to be promises on its report as `judged`; when that set
   is there, only those count. The rules do not judge, so today every open proposal counts.
6. **gaps** — the usual sources with no line on the day, one line: `dawarich: usual, no line`. A
   source is usual when it has a line on four in five of the logged days of the fortnight ending
   on the day (the `days` rule, `days.usual_sources`); it is missing when `sources --gaps`, asked
   from the day with those sources expected, counts the day among its missing days or holds no line
   of it at all. A note written once in the fortnight is not usual, so it is never missed.
7. **tomorrow** — the timed calendar entries of the next local day, from the `event/v1` lines
   standing (retracted lines out; an entry several calendars carry is one, `×N sources`, as the Day
   folds them), with the attendees the record names: `12:00–13:00  Lunch · with Kari Nordmann`.
   An all-day entry is not timed and is not here. Three at most, then `+N more entries`.
8. **The question**, last, after a blank line. One, chosen by the first rule that applies, so that
   the owner can answer in a word and the day closes itself (ADR 0005: one nudge, one channel):

   | when | the question |
   |---|---|
   | no line at all, and a usual source is missing | `Was dawarich switched off?` |
   | no line at all | `Where were you?` |
   | the night after is in transit | `Where did you sleep?` |
   | a person is proposed and confirmed nowhere | `Was Kari Nordmann with you?` |
   | a calendar entry fell inside no row | `Did “Lunch” happen?` |
   | a usual source is missing | `Was apple-health switched off?` |
   | a promise is due on the day or before | `Is “I'll send the photos by Friday.” done?` |
   | otherwise | `Anything to add?` |

   The answer is the owner's to write — a note, a `promises done`, a confirmation — and the digest
   never writes it for them.

## The limit

Twenty-five lines is a hard limit, not a target. The parts are capped as above, so a day with six
flights, eight promises and nine meetings tomorrow still fits with room over; should a day ever not,
`digest.fit` cuts lines from the middle for one `…` row and keeps the header and the question. The
JSON is never cut: it holds the whole sets, and `lines` says how many lines the text has. The
digest is never a list of everything — that is what `logbook day` is for.

## A synthetic example

The Oslo persona of the test suite, who does not exist, on a Wednesday with a lunch at an unnamed
cafe, a promise made the evening before, and two entries in tomorrow's calendar:

```
2026-06-10  Wednesday
  where      Home → Office → 59.9200,10.7400 → Office → Home · night at Home
  with       Kari Nordmann
  attached   1 event, 1 photo
  due        “I'll send Ola the mooring photos by Friday.”  you, 2026-06-12 (by Friday)
  tomorrow   09:00–09:30  Standup
  tomorrow   12:00–13:00  Lunch · with Kari Nordmann

Anything to add?
```

The Monday they fly to Zürich:

```
2026-06-15  Monday
  where      Home → OSL, Oslo → ZRH, Zurich → 47.3769,8.5417 (Zurich) · night away, 47.3769,8.5417 (Zurich)
  with       nobody confirmed
  attached   1 event
  flight     XY 561 OSL→ZRH  07:05–09:15
  tomorrow   19:00–21:00  Dinner · with Ola Nordmann

Anything to add?
```

A day the record holds nothing for:

```
2026-06-10  Wednesday
  where      nothing logged
  with       nobody confirmed
  attached   nothing

Where were you?
```

`--markdown` prints the same lines as a heading, a bulleted list with the labels in bold, and the
question in bold on its own:

```markdown
## Saturday 13 June 2026
- **where** Home → aboard Solvind · night away, aboard Solvind
- **with** Ola Nordmann
- **attached** 1 note, 1 photo

**Anything to add?**
```

## The JSON

`--json` prints one object: `day`, `weekday`, `tz`; `shape` (`where`, the stays in order; `night`
with `where`, `home`, `aboard`, `in_transit`; `with` with `confirmed` and `proposed` as names;
`attached` as `count` and `noun` pairs; `unplaced`); `flights`, the Day's own with their line ids;
`promises` (`within_days`, `judged`, and `open`, every proposal as `promises --json` prints it);
`gaps` (`usual` and `missing`); `tomorrow` (`day` and `entries`, each with `title`, `start`, `end`,
their local forms, `with`, `sources` and `lines`); `unplaced`, the Day's list; `sources`, the names
with a line on the day; `question` (`about`, the rule that chose it, and `text`); and `lines`.

## What it does not do

It does not send anything, schedule anything or remember what it said: a delivery layer that takes
the text, picks the channel and keeps to one message a day is the next decision, not this command.
It does not read a day that has not come: a day after today in the record's zone is refused. It does
not derive anything the Day, the promises reader and `sources --gaps` do not already derive, so a
change in their rules is a change here, and nothing here is a setting of its own.
