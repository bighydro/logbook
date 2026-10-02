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
passage, an anchorage. The asset's movement never fragments the stay. The rule is below, under
*Aboard an asset*.

## What it shows, in order

1. **Header** — the date and weekday; the night before and the night after (a named place,
   `aboard <asset>` with the asset's position that night, or the coordinates; `home` when the stay
   lies in a place of kind `home` or within 400 m of one — the night then names that place — else
   `away`; `in transit` when no stay reaches the minimum); the country, from the night's position
   by the same rule `rollup countries` uses (a place's own country, else the nearest large
   airport's zone), from the longest stay of the day when the night is in transit; the day's
   all-day calendar entries.
2. **Timeline** — one row per stay, stop, move and flight that touches the day, in time order.
   A stay that began the evening before shows from `00:00` and one that runs on shows to `24:00`;
   the duration printed is the part on the day, and `--json` keeps the real span beside it. An
   unnamed stay at an airport is the airport's code and city (`ZRH, Zurich`: within 3.5 km of the
   reference point of an airport with scheduled traffic, 2 km of any other); else its coordinates,
   with `near <place>, x km` for the nearest named place within 5 km (`59.9200,10.7400 near Home,
   1.0 km`), else the city of the nearest large airport within 30 km in parentheses
   (`53.5998,10.0130 (Hamburg)`), the `trips` route's rule. A stop with nothing attached says so.
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
  night after   aboard Solvind · 59.8500,10.6000 · away
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

## Aboard an asset

A stay aboard an asset is a **container**. `derive stays` finds it and `day` shows it; the rule is
the stays engine's (`logbook/stays.py`), and `trips`, `days` and the rollups read what it finds.

- **Boarding is twenty minutes.** You are aboard an asset when its own location lines (`subject` =
  the asset's id, from `sync ais`, `sync adsb` or a saved stream) lie within the stay radius
  (`radius_m`, 150 m) of your points for `aboard_min_s` — 20 minutes by default, a setting in
  `policy/stays.json` — or longer. At anchor that is the asset's fixes inside the radius of your
  stay's centre, first to last; under way it is your points within the radius of the asset's
  position at that instant, read between the asset's two fixes around it when they are at most
  twice `aboard_window_s` apart (an AIS fix every ten minutes places a boat under way well enough),
  else from the nearest fix within the window. A boat that passes the quay once while you sit at
  the cafe does not board you; your own boat alongside for the afternoon does.
- **The run is one stay.** Consecutive stays and moves aboard one asset fold into one stay
  `aboard <asset>`, from the first's start to the last's end; the run is inside it, and the
  asset's movement never fragments it. Its centre is the inner stay you spent longest at (the
  anchorage of the night, not the berth of the morning), and that is the coordinate in its id.
  A single move aboard with no stay either side (a ferry walked on and off) stays a move.
- **The night names the asset.** The overnight rule counts the stay aboard whole, so a passage
  through the night is a night aboard, never a night in transit, and the night carries the asset's
  position: the inner stay that held the longest part of the night window. The header reads
  `night after   aboard REDUCE · 59.3400,10.5500 · away`; the country is that position's.
- **Downstream.** `days` prints the night as `aboard <asset>`; `trips` makes a night aboard a route
  element `aboard <asset>` and counts the trip's nights aboard per asset; `rollup places` has an
  `aboard` section, one stay per run aboard with the run's whole hours, while the berths and
  anchorages inside it are still unnamed places of their own, each marked `aboard`, and a night
  aboard counts at the anchorage the asset lay at; `rollup nights` counts nights aboard per asset.

The test fixture is the yacht REDUCE (MMSI 970123456, which does not exist), which weighs anchor
at 22:30 and motors 40 km south through the night with the persona aboard, at anchor again by
03:00: the Friday is one stay aboard with the first anchorage, the passage and the second
anchorage inside it, and the night is `aboard REDUCE` at the second anchorage. In the control
case the persona spends the same night at a cabin 3 km from the first anchorage while the boat
moves without them: the night is at the cabin's coordinates, the boat's passage is the boat's
own, and nothing says aboard.

## The JSON

`--json` prints one object: `day`, `weekday`, `tz`; `nights.before` and `nights.after` (`where`,
`home`, `aboard`, `in_transit`, `position` — the night's `lat` and `lon`, the asset's for a night
aboard — the stay's id and its first and last location line); `country`
(`code`, `method`, `by`, `from`); `all_day`; `timeline`, one entry per row — a stay, stop or move
as `derive stays --json` gives it plus `within_day` (the part on the day), `gap`, `attached`
(`events`, `transcripts`, `notes`, `mail`, `calls`, `keepers` with their line ids; `messages` and
`photos` as counts with their line ids) and `with` (`confirmed`, `proposed`, each person with their
sources, reasons and lines); an `aboard` entry adds `asset` and `inside`; a `flight` entry carries
the flight line's fields and `line`; a move lists the `flights` that cover it — then `flights`,
`unplaced`, `health` (with the ids of the lines each number came from) and `sources`.

## A window of days

`logbook days --from YYYY-MM-DD --to YYYY-MM-DD [--json]` reads a window back one line per day,
composed from the Day of each: the date and weekday; where the night was spent (the night after,
as the Day's header has it: a named place, `aboard <asset>`, the home place a night within 400 m
of it lies by — the night rule, whatever the place's radius — or the coordinates with `near
<place>, x km` for a named place within 5 km or the city of the nearest large airport, and the
country when the night is away; `in transit` when no stay reaches the minimum; `no location` when
the day has no location line at all, since nothing then says the owner moved); the kilometres
moved (every move that started on the day, the flights'
included, and aboard an asset its passages); the flights (`XY 561 OSL→ZRH`); the stays — a stay
or a run aboard an asset; a stop is not one — with how many lines are attached across the day's
rows; the people confirmed present (`with 2`; a proposed face is not counted); the health triple
when the day has one; and a gap marker. Both bounds default to the days the owner's track covers.

```bash
logbook days --from 2026-06-08 --to 2026-06-21          # the persona's fortnight, as text
logbook days --from 2026-01-01 --to 2026-12-31 --json   # a year, one JSON object per line
logbook days                                            # the whole record
```

The fortnight of the test persona, who does not exist:

```
2026-06-08  Mon  Home                             1.2 km  3 stays
2026-06-09  Tue  Home                             1.2 km  3 stays
2026-06-10  Wed  Home                             4.4 km  5 stays (2 attached) · with 1
2026-06-11  Thu  Home                             1.3 km  3 stays (2 attached) · with 1
2026-06-12  Fri  Home                             1.2 km  3 stays
2026-06-13  Sat  aboard Solvind NO               11.1 km  2 stays (2 attached) · with 1
2026-06-14  Sun  Home                            11.1 km  2 stays
2026-06-15  Mon  47.3769,8.5417 (Zurich) CH     1,471 km  XY 561 OSL→ZRH · 4 stays (1 attached)
2026-06-16  Tue  47.3769,8.5417 (Zurich) CH       0.0 km  1 stay (2 attached) · with 1
2026-06-17  Wed  47.3769,8.5417 (Zurich) CH       0.0 km  1 stay
2026-06-18  Thu  Home                           1,471 km  XY 562 ZRH→OSL · 4 stays
2026-06-19  Fri  Home                             1.2 km  3 stays
2026-06-20  Sat  Home                             1.2 km  3 stays
2026-06-21  Sun  Home                             0.0 km  1 stay
```

The **gap marker** names every usual source with no standing line on the day — `gap dawarich`
when the tracker said nothing all day, `gap apple-health, dawarich` on a day with nothing logged
(the line then reads `no location` and `nothing logged`). A source is usual when it has a line on
at least four in five of the window's days that have any line: the tracker, the watch, the boat's
AIS, the messages; not the photos or the notes, which come every other day, and not a calendar
that spoke once. The share is counted on the index in one aggregate (`Index.source_days`),
nothing read from the files, before the first line is printed.

Every number is the Day's: the night is `nights.after`, the country is the Day's, the flights are
the Day's flight rows, the stays and their attachments are its timeline rows, the people are the
union of its rows' confirmed company, the health row is its health line. What the window clips is
a stay's start, and the night's stay id carries it: a hotel stay of three nights starts, in a
reading that opens on its second day, at that day's midnight, as it does for `day` of that day.

Under `--json` the output is JSON Lines — one object per day per line, so a year streams as text
does: `day`, `weekday`, `night` (`where`, `home`, `aboard`, `in_transit`, `stay`), `country` (the
code), `moved_m`, `flights` (`carrier`, `number`, `from`, `to`, `evidence`, `line`), `stays`
(`count`, `attached`, `with_attachments`), `people` (`confirmed`, `names`), `health` (as the Day's,
with its line ids), `sources` (as the Day's) and `gaps`.

## Performance

A Day is located through `index.sqlite`: one reading of the day and the day before (the night
before is that day's night), the retraction and resolution lines, and the health lines of the two
days, each by an indexed column. A record of millions of lines reads a day in the time that day's
lines take; the files are never swept.

`days` reads the window in chunks of a month through one reading each — the chunk's days and the
day before, so the first day has its night before, and the chunk's health lines in one indexed
query — and asks that reading for each day in turn: a year is a dozen readings, never one per
day, and the lines stream out as each chunk is read. A year of the demo record (`logbook demo
--days 365`, 155,000 lines) prints in seconds, the first line within one.

## What it is not

Not a narrative: no title, no summary, no score. The reader never writes a note, a confirmation or
a naming; those are yours, and when you make one it is a line in the record that the next Day reads.
