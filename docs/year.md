# The Year

`logbook year YYYY [--html PATH] [--json]` reads one calendar year back from the record: the days
per country, the nights home, away and aboard each asset, the trips in order with their nights and
companions, the flights and their kilometres, the places by nights, the people by days together,
the health lines by month, the weather of the year when the record has it (`adapters/weather.md`),
the keepers by month, and twelve picks, **one day each**: for every
month, the day with the most evidence, rendered with the day reader. It is a reader (ADR 0013): a
function of the record at its head, composed from the readers that already exist — `rollup`,
`trips`, `day` — over one reading of the year's days, derived every time and never written.

```bash
logbook year 2026                      # the year as text
logbook year 2026 --html ~/2026.html   # one self-contained page: inline CSS, no script, no asset; prints
logbook year 2026 --json               # the same Year as one JSON object, the picks' Days inside
```

## What a Year is

The window is the year's days the owner's track covers — the first to the last day with a
location line, clipped to the year, as `rollup --year` clips it — so a day the record knows
nothing about is nothing: not a night in transit, not a zero, not a pick. A year the record has
no day in says so and the page is empty.

One `reading.read` of the window serves every section, and each section is the reader it names,
for that year:

1. **Countries** — days per country from the overnight stay, in transit and unknown apart
   (`rollup countries`, and its rule: a place with a country in `places.json`, else the nearest
   large airport's zone).
2. **Nights** — home, away, in transit, and the nights aboard each asset (`rollup nights`).
3. **Trips** — every run of nights away from home, in order (`trips`): the dates, the nights
   (`aboard <asset>` for an asset trip), the route, the flights in and out, the named places
   visited and the people confirmed present.
4. **Flights** — the count, the kilometres, the long-haul count and the count by evidence, then
   every flight (`rollup flights`).
5. **Places, by nights** — every named place and asset, then the top unnamed clusters, each with
   its nights, stays, hours and the people confirmed there (`rollup places`), ordered by nights
   and then hours; the page says `0 nights` for an office, since that is the point.
6. **People** — by days together: days, nights, the last real contact and the places shared
   (`rollup people`, the confirmed set only; a tagged face is a proposal and not a day together).
7. **Health, by month** — sleep, steps, resting heart rate and HRV (`rollup health --by month`);
   a field no day of the month has a line for is an em dash, never a zero.
8. **Keepers, by month** — the `keeper/v1` lines standing (RFC 0024), by lane, for every month
   the window touches.
9. **One day each** — twelve picks, one per month, each rendered with the day reader exactly as
   `logbook day` prints it, the night before included.

## The pick

The evidence of a day is counted from its Day: the **attachments** across its rows — events,
transcripts, notes, mail threads, calls, messages, photos and keepers, as the Day counts them —
plus the **people confirmed** present (never a proposal), plus **one** when the day has a flight
or a new place. A new place is a named place not stayed at earlier in the year, or an unnamed
stay further than 300 m (the distance `places propose` groups by) from every earlier unnamed stay
of the year; home is never new, and a stay counts on the day it began.

```
score = attachments + people confirmed + (1 if a flight or a new place)
```

For each month, the pick is the day with the highest score; of equals, the day with more lines
logged; of equals still, the earlier day. A month with no line is no pick (`no days`), and a month
whose days have lines but no evidence shows its fullest day. Under `--json` every day of the window
is listed under `scored` with its evidence, so the choice can be checked.

On the persona's fortnight (`tests/persona.py`, nobody in it is real), the Wednesday lunch — an
event and a photo, Kari confirmed, the cafe a new place — scores four, and so does the Saturday
aboard Solvind — a note and a photo, Ola confirmed, the marina and the anchorage new; the Saturday
has the boat's own track in the record too, so it has more lines, and it is June's pick. The
Monday flight to Zürich scores two: the calendar entry attached to the move, and the flight; the
new places that day are not a second one.

## A synthetic example

The demo record (`logbook demo --days 365 --seed 7`), whose Oslo persona does not exist, read for
2026 — the record starts on 1 June, so the window is June to December and the first five months
have no days:

```
2026  2026-06-01 – 2026-12-31 · 214 days
  countries     NO 176 days · CH 24 days · DK 14 days · in transit 0
  nights        122 home · 92 away · 0 in transit · 46 nights aboard Nordlys
  trips         31 trips · 92 nights away
    2026-06-06 – 2026-06-06  1 night · route Cabin · places Cabin · with Ola Nordmann
    2026-06-08 – 2026-06-10  3 nights · route 47.3769,8.5417 (Zurich) · in XY 561 OSL → ZRH · out XY 562 ZRH → OSL · with Marta Keller, Jonas Weber
    2026-06-15 – 2026-06-20  6 nights aboard nordlys · route 59.8500,10.6000 → 59.4300,10.4800 (Sandefjord) → … → Marina · places Marina · with Anders Vik, Ola Nordmann
    …
  flights       30 flights · 30,050 km · 0 long-haul · declared 7, inferred 8, tracked 15
    2026-06-08  XY 561  OSL → ZRH · 1,426 km · tracked
    2026-06-11  XY 562  ZRH → OSL · 1,426 km · inferred
    …
  places        by nights
    Home (home)                                 122 nights · 123 stays · 1,887 h
    Cabin (other)                               8 nights · 8 stays · 208 h · with Ola Nordmann
    Marina (asset-berth)                        7 nights · 23 stays · 194 h · with Anders Vik, Ola Nordmann, Sigrid Moen
    Office (other)                              0 nights · 91 stays · 672 h · with Liv Berg, Per Hansen
    Nordlys (nordlys) (yacht)                   46 nights · 62 stays · 963 h · with Anders Vik, Ola Nordmann, Sigrid Moen
    unnamed:
    47.3769,8.5417 (Zurich)                     24 nights · 24 stays · 468 h · with Marta Keller
    …
  people        by days together
    Liv Berg                                    61 days · 0 nights · last 2026-12-25 · Office
    Per Hansen                                  61 days · 0 nights · last 2026-12-25 · Office
    Ola Nordmann                                24 days · 8 nights · last 2026-12-28 · Cabin, Marina
    …
  health        by month
    2026-06  sleep 6.8 h (29 nights) · 8,425 steps (30 days) · resting 57 bpm (52–61, 30 days) · hrv —
    …
  keepers       by month
    2026-06  9 (8 memory, 1 art)
    …

  one day each
  January       no days
  …
  June          2026-06-03 · 10 attachments, 1 person, a new place
    2026-06-03  Wednesday
      night before  Home · home
      night after   Home · home
      country       NO (place Home)

      00:00–07:25  stay   Home · 7 h 25 min
      07:25–07:45  move   643 m · 20 min · walk
      07:45–11:45  stay   Office · 4 h · 1 event
          event        One to one 09:00–09:45
          with         Liv Berg (calendar)
      …
```

## The page

`--html PATH` writes the same Year as one HTML file and prints `year 2026: wrote PATH`. The page
is self-contained: its CSS is inline, it has no script, loads no font, image or stylesheet, and
links nowhere, so it reads the same in twenty years and offline, and it prints: the sections have
tables whose headers repeat on every sheet, the picks start on a fresh sheet and none of them is
split across two. Everything the record says is escaped; a note that reads `<b>` stays text. The
picks are the day reader's rows, in a monospace block, so the page shows exactly what the terminal
does.

`--html PATH --print` writes the paper edition instead — a cover, a contents page and one spread
per month with the facts, a map drawn from the location lines and the keepers as hero photos, for
A4 and US Letter — and [On paper](print.md) says how to make the PDF.

The Year also prints: `--html PATH --print` is the paper edition (a cover, contents, a spread a
month) and `--poster` one sheet, A2 or A3, a square a day in the ink of its night — both in
[On paper](print.md).

## The JSON

`--json` prints one object: `year`; `window` (`since`, `until`, `days`; `null` for a year the
record has no day in); `head`, the chain head the Year was read at; `warnings` (the trips reader's,
when `places.json` names no home); `countries` (`countries` as `{country, days}`, `in_transit`,
`unknown`); `nights` (`home`, `away`, `in_transit`, `aboard` as `{asset, name, nights}`); `trips`,
each as `trips --json` gives it with `people` as names and without the line ids; `flights`
(`count`, `km`, `long_haul`, `unmeasured`, `by_evidence`, `flights`); `places` (`places`, `assets`,
`unnamed`, each entry with `nights`, `stays`, `hours`, `first`, `last` and `people` as names; an
unnamed cluster with its `id`, the stay id `places name` takes, `label`, `lat`, `lon`, `aboard`
and `city`); `people` (`id`, `name`, `days`, `nights`, `stays`, `last_contact`, `places`,
`confirmed`); `health`, one entry per month with the rollup's `sleep`, `steps`, `resting_hr` and
`hrv`, their line ids inside; `keepers`, one entry per month with `count`, `memory` and `art`;
`picks`, twelve entries of `month`, `day`, `evidence` (`attachments`, `people`, `flight`,
`new_place`, `lines`, `score`) and `page`, the Day as `logbook day --json` gives it; and `scored`,
the evidence of every day of the window. Nothing is written.

## One trip

`logbook trip <id-or-date> [--html PATH] [--json]` reads one trip back the same way: one of the
runs of nights away that `trips` lists, named by its derived id (`trip:2026-06-15:2026-06-20`, the
last part of every `trips` row) or by any day inside it, the return day included. It is a reader
too (ADR 0013, ADR 0019): composed from `trips`, `days`, `rollup health`, the keepers and the
transaction lines over one reading of the days around the trip — a week either side, widened
while the run of nights away touches the window's edge, so a week is read from a month and never
from a year — derived every time and never written.

```bash
logbook trips --year 2026                            # every trip of the year, its id last on the row
logbook trip trip:2026-06-15:2026-06-20              # the yacht week as text
logbook trip 2026-06-17 --html ~/yacht-week.html     # the same trip, named by a day inside it, as one page
logbook trip 2026-06-17 --json                       # the Trip as one JSON object
```

The sections, in order:

1. **Route** — the stays slept at, in night order, each with its nights and dates: a named place,
   else the coordinates labelled as the Day labels them (the airport, `near <place>, x km`, the
   city in parentheses). A week aboard is its anchorages, one stay each, with the asset beside
   them — where `trips` folds the week into `aboard Nordlys`, the page says where the boat lay
   each night. Consecutive nights at one point (within 200 m) are one stay; a night in transit is
   a stay with no place. The **legs** between consecutive located stays carry their great-circle
   kilometres, and a leg that crosses a night in transit says so.
2. **Flights** — in (dated the leaving day) and out (dated the return day), as `trips` has them.
3. **People** — the people confirmed present at the trip's stays (the calendar, a transcript, a
   note, a resolved face), and apart the ones only *proposed* (a tagged face the record does not
   confirm, an all-day entry's attendee); someone confirmed at one stay is never a proposal at
   another.
4. **Nights aboard** — per asset, when any night was spent on one; an asset trip says so in the
   header (`6 nights aboard Nordlys`).
5. **Days** — from the leaving day to the return day, one line each exactly as `logbook days`
   prints it: the night, the kilometres moved, the flights, the stays and what attached, the
   people, the health triple, the gaps.
6. **Keepers** — per day of the span, by lane, with the photos' names (RFC 0024).
7. **Health** — sleep, steps, resting heart rate and HRV over the span as one period, the
   `rollup health` rule; a field no day has a line for is an em dash, never a zero.
8. **Spend** — every `transaction/v1` line (RFC 0021) dated inside the span, summed per currency
   with a minus sign for money that left (`−119 NOK (1 transaction)`), then each transaction with
   its merchant and category. The section is there only when the record holds a transaction in
   the span.

On the demo record's yacht week (`logbook demo`; nobody in it is real):

```
trip:2026-06-15:2026-06-20  2026-06-15 – 2026-06-20 · 6 nights aboard Nordlys · until 2026-06-21
  route
     1  2026-06-15               1 night   59.8500,10.6000 · aboard Nordlys
     2  2026-06-16               1 night   59.4300,10.4800 (Sandefjord) · aboard Nordlys
     3  2026-06-17 – 2026-06-18  2 nights  59.0500,10.0300 (Sandefjord) · aboard Nordlys
     4  2026-06-19               1 night   59.8500,10.6000 · aboard Nordlys
     5  2026-06-20               1 night   Marina · aboard Nordlys
  legs          1 → 2 47 km · 2 → 3 49 km · 3 → 4 95 km · 4 → 5 9.7 km
  flights       none
  with          Anders Vik, Ola Nordmann
  aboard        6 nights aboard Nordlys
  days
    2026-06-15  Mon  aboard Nordlys NO               11.1 km  2 stays (2 attached) · with 2 · sleep 6.2 h · 6,671 steps · resting 54 bpm · gap immich
    2026-06-16  Tue  aboard Nordlys NO               47.2 km  1 stay (4 attached) · sleep 6.2 h · 5,978 steps · resting 56 bpm
    …
    2026-06-21  Sun  Home                             1.4 km  2 stays (3 attached) · sleep 7.5 h · 6,703 steps · resting 55 bpm
  keepers       3 (3 memory, 0 art)
    2026-06-16  1 memory  IMG_06161730.HEIC
    …
  health        sleep 6.7 h (7 nights) · 6,417 steps (7 days) · resting 56 bpm (52–61, 7 days) · hrv —
  spend         −119 NOK (1 transaction)
    2026-06-18  Havnekiosken  −119 NOK  groceries
```

A day whose night was at home names no trip (`no trip on 2026-06-02: the night was at home`);
an id that names none says which trip its first day belongs to; without a place of kind `home`
in `places.json` nothing is away, as `trips` says.

### The trip page

`--html PATH` writes the Trip as one HTML file and prints `trip <id>: wrote PATH`. Like the
Year's it is self-contained — inline CSS, no script, no font, image or stylesheet fetched, nothing
linked — and prints with table headers on every sheet. Its route section opens with a **map**:
an inline SVG drawn from the stays' coordinates in an equirectangular projection about the
route's mean latitude (longitude scaled by the cosine of it, so a kilometre is the same length
either way), one `path` per leg — dashed when a night in transit lies between — one mark per
point with the numbers of the stays at it (a bay slept in on the way out and the way back is
one mark, `1, 4`), and a scale bar in whole kilometres. No tiles and no external map: the page
shows the shape of the trip, and the table under it says where each point is. A single stay is
still a map, drawn at a twentieth of a degree across. Everything the record says is escaped.

### The trip JSON

`--json` prints one object: `id`, `start`, `end`, `until` (the return day), `nights`,
`in_transit`, `asset` (the asset every night was aboard, else `null`) and `nights_aboard`
(`{asset, name, nights}`); `head`, the chain head it was read at; `window`, the reading's days;
`warnings`; `route`, one entry per stay with `n`, `first`, `last`, `nights`, `label`, `place`,
`lat`, `lon`, `aboard`, `asset`, `stay` (the stay id) and `in_transit`; `legs` (`from`, `to`, `km`,
`through_transit`); `places`; `days`, one object per day as `days --json` gives it; `flights_in`,
`flights_out` and `flights`; `people` (`confirmed` and `proposed`, each `id`, `name`, `status`,
`confidence`, `sources`, `lines`); `keepers` (`count`, `memory`, `art`, and `days` with each day's
counts and `photos`); `health` (`sleep`, `steps`, `resting_hr`, `hrv`, the rollup's shape with
line ids); `spend` (`by_currency` as `{currency, amount, count}` and `transactions` with `date`,
`merchant`, `amount`, `currency`, `category`, `provider`, `line`; `null` when there is none); and
`lines`, the trip's line ids. Nothing is written.
