# The Day

`logbook day YYYY-MM-DD [--json]` reads one calendar day back from the record: where you slept
either side of it, which country it counts for, how you moved and where you stayed, what attached
to each stay and who was there, the flights, the night's sleep and the day's steps, and which
sources spoke. It is a reader (ADR 0013): a function of the record at its head, derived every time
and never written. Nothing is appended, and not even `policy/stays.json` is created by it.

```bash
logbook day 2026-06-13          # a Saturday, as text
logbook day 2026-06-13 --json   # the same Day as one JSON object, every row with its line ids
logbook day                     # today
```

## What a Day is

The record's atom is the line. The reader's atom is the **stay**: a span at one place, as
`derive stays` finds it. A **Day** is the ordered list of stays and moves between 00:00 and 24:00
in the record's zone, with everything else — calendar entries, transcripts, notes, mail, calls,
messages, photos, keepers — attached to the stay or move it falls inside. The **night** of a day is
the longest stay in the night window (22:00 to 08:00 by default), and it decides home or away; a
night with no such stay is in transit.

Aboard an asset (a boat, an aircraft, a car registered in `assets.json`) the grammar nests: when
your position matches the asset's own track, the run of stays and moves aboard it is one stay
`aboard <asset>`, and inside it the same grammar runs on the asset's position — a berth, a
passage, an anchorage. The asset's movement never fragments the stay.

## What it shows, in order

1. **Header** — the date and weekday; the night before and the night after (a named place,
   `aboard <asset>` or the coordinates; `home` when the stay lies in a place of kind `home`, else
   `away`; `in transit` when no stay reaches the minimum); the country, from the night's stay by
   the same rule `rollup countries` uses (a place's own country, else the nearest large airport's
   zone), from the longest stay of the day when the night is in transit; the day's all-day
   calendar entries.
2. **Timeline** — one row per stay, stop, move and flight that touches the day, in time order.
   A stay that began the evening before shows from `00:00` and one that runs on shows to `24:00`;
   the duration printed is the part on the day, and `--json` keeps the real span beside it. An
   unnamed stay is its coordinates, with the city of the nearest large airport within 30 km in
   parentheses when it is at no airport and near no named place (`53.5998,10.0130 (Hamburg)`, the
   `trips` route's rule). A stop with nothing attached says so.
   A move prints its distance, duration and mode (walk, car, train, boat, flight), with the
   airports when it is a flight between two. A move with no points that lasts a silence or more
   (`merge_gap_s`) and is not a flight is a **gap**: the tracker did not see it, so it places
   nothing. Flights come from the `flight/v1` lines standing — the merged set `infer flights`
   maintains, one line per flight — with their evidence: `tracked`, `inferred` or `declared`; the
   move a flight covers names it under `--json`.
   Under each row: its attachments, named for events (with their time; an entry several calendars
   carry — the same start and end, the same flight or the same title, case and accents aside — is
   one event, `×N sources`), transcripts, notes (the first line), mail threads (with the message
   count), calls and keepers, and counted for messages and photos; then **with**, the people there, split into **confirmed** — declared in a note
   (`with <name>`, only a name the record's resolution lines make a person: `with US` names
   nobody), speaking in a transcript, attending a timed calendar entry that overlaps the
   stay — and **proposed** — a face the photo library tagged, an attendee of an all-day entry. The
   owner is never their own company. A move carries attachments but no company.
3. **Unplaced** — the day's events, transcripts, notes, mail and calls that fall inside no stay or
   move: what the calendar planned where the track has nothing, or what happened while the tracker
   was silent.
4. **Health** — the night's sleep in hours (the asleep stages of the night that ends on the day,
   per device the union of their spans, the longest device), the day's steps (the larger device per
   quarter hour, summed), the resting heart rate (the day's mean), from the `health-sample/v1`
   lines standing. A correction that `supersedes` a line wins over it.
5. **Sources** — every source with a line on the day, how many, and its newest line's time, so a
   tracker that fell silent in the afternoon is seen to have.

## A synthetic example

The Oslo persona of the test suite, who does not exist, spends a June Saturday aboard the yacht
Solvind. The owner's position matches the boat's AIS track from the marina out to the anchorage, so the
day is one stay aboard, with the berth, the passage and the anchorage inside it, a note that
declares who was there, and the night aboard:

```
2026-06-13  Saturday
  night before  Home · home
  night after   aboard Solvind · away
  country       NO (nearest airport OSL)

  00:00–09:00  stay   Home · 9 h
  09:00–09:15  move   1.4 km · 15 min · walk
  09:15–24:00  aboard Solvind (yacht) · 14 h 45 min · 1 note, 1 photo, 1 keeper
      09:15–10:00  stay   Marina · 45 min
      10:00–12:00  move   9.7 km · 2 h · boat
      12:00–24:00  stay   59.8500,10.6000 · 12 h
      note         Anchored in the bay with Ola Nordmann. Grilled.
      keeper       IMG_131730.HEIC (memory)
      with         Ola Nordmann (note)

  health        no lines
  sources       dawarich 888 lines, last 23:58 · immich 1 line, last 19:30 · keeper-inference 1 line, last 19:30 · manual 1 line, last 19:00
```

A Thursday whose tracker was silent from nine to five, with a lunch in the calendar during the
silence and an all-day entry, and the night's sleep, the steps and a resting reading (corrected
once) in the record:

```
2026-07-02  Thursday
  night before  Home · home
  night after   Home · home
  country       NO (nearest airport OSL)
  all day       Kari in town

  00:00–09:00  stay   Home · 9 h
      with         proposed Kari Nordmann (calendar)
  09:00–17:00  gap    8 h · no points · 6.3 km
  17:00–19:00  stay   59.9600,10.8199 · 2 h
      with         proposed Kari Nordmann (calendar)
  19:00–19:30  move   6.4 km · 30 min · car
  19:30–24:00  stay   Home · 4 h 30 min
      with         proposed Kari Nordmann (calendar)

  unplaced      12:00–13:00  event  Lunch

  health        sleep 7.0 h · 3,250 steps · resting 56 bpm
  sources       dawarich 191 lines, last 23:55 · apple-health 6 lines, last 17:00 · ios-calendar 2 lines, last 12:00
```

The gap is a row, said so; the lunch is unplaced rather than attached to it, because the track
says nothing about where the owner was; the all-day entry proposes its attendee at every stay and
confirms Kari at none.

## The JSON

`--json` prints one object: `day`, `weekday`, `tz`; `nights.before` and `nights.after` (`where`,
`home`, `aboard`, `in_transit`, the stay's id and its first and last location line); `country`
(`code`, `method`, `by`, `from`); `all_day`; `timeline`, one entry per row — a stay, stop or move
as `derive stays --json` gives it plus `within_day` (the part on the day), `gap`, `attached`
(`events`, `transcripts`, `notes`, `mail`, `calls`, `keepers` with their line ids; `messages` and
`photos` as counts with their line ids) and `with` (`confirmed`, `proposed`, each person with their
sources, reasons and lines); an `aboard` entry adds `asset` and `inside`; a `flight` entry carries
the flight line's fields and `line`; a move lists the `flights` that cover it — then `flights`,
`unplaced`, `health` (with the ids of the lines each number came from) and `sources`.

## Performance

A Day is located through `index.sqlite`: one reading of the day and the day before (the night
before is that day's night), the retraction and resolution lines, and the health lines of the two
days, each by an indexed column. A record of millions of lines reads a day in the time that day's
lines take; the files are never swept.

## What it is not

Not a narrative: no title, no summary, no score. The reader never writes a note, a confirmation or
a naming; those are yours, and when you make one it is a line in the record that the next Day reads.
