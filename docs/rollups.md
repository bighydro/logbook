# The rollups

`logbook rollup <kind> [--year YYYY | --since YYYY-MM-DD --until YYYY-MM-DD] [--json]` sums the
record up over a window of days. Every rollup is a reader (ADR 0013): a function of the record at
its head, derived every time and never written, and under `--json` every number carries the ids of
the lines it came from. The window is the whole record unless `--year` or `--since`/`--until` narrow
it, and it is clipped to the days the rollup's own lines cover, so a day the record knows nothing
about is nothing, not a night in transit and not a zero.

```bash
logbook rollup countries --year 2026   # days per country from the overnight stay; in transit apart
logbook rollup flights                 # count, km, long-haul, by evidence, from the flight lines standing
logbook rollup nights                  # home, away, in transit, nights aboard, the longest trip
logbook rollup places                  # nights, stays, hours, people per named place and asset; the top unnamed clusters
logbook rollup places --with           # the place × person table: stays, days and nights at each place per person
logbook rollup people                  # days and nights together, last real contact, places shared, per person
logbook rollup health --by week         # sleep, steps, resting heart rate, HRV, per month or ISO week
logbook rollup listen --year 2026       # listens, hours, skips, the top artists by hours, hours by month
```

The window is `--year`, or `--since` and `--until`, clipped to the days the owner's track covers
(the first to the last day with a location line; for flights, with any line), so a day outside
them is nothing, not a night in transit. Without either, the whole record.

## Places

`rollup places` is the year per place. For every named place in `places.json`: the **nights**
whose overnight stay is there, the **stays**, the **hours**, the **first and last** visit (the first
stay's start day, the last stay's end day), and **with**, the people confirmed present through the
with module, most days first. Then **aboard**, the same per asset in `assets.json`: a stay aboard
is one run of your stays and moves aboard it, whatever the asset did inside it ([docs/day.md](day.md),
*Aboard an asset*), its hours the run's whole span, its nights the nights whose overnight stay was
aboard. Then the **unnamed** places: your stays at no named place — the berths and anchorages
inside a stay aboard among them, each marked `aboard <asset>` — grouped as `places propose` groups
them (within 300 m of a group's first stay) and ranked by hours, the top five of the year, each
under the stay id `places name` takes, so a hotel you keep returning to is one line and one command
away from a name. A night aboard counts at the anchorage the asset lay at.

```
places 2026-06-01 – 2026-06-30
  2026
        Home (home)                                 18 nights · 19 stays · 273.5 h · 2026-06-01 – 2026-06-30
        Office (other)                              14 stays · 107 h · 2026-06-01 – 2026-06-30 · with Per Hansen, Liv Berg
        Marina (asset-berth)                        1 night · 3 stays · 26.8 h · 2026-06-13 – 2026-06-21 · with Anders Vik, Ola Nordmann, Sigrid Moen
        Cabin (other)                               1 night · 1 stay · 25.9 h · 2026-06-06 – 2026-06-07 · with Ola Nordmann
        aboard, by hours (a stay is one run aboard, whatever the asset did inside it):
        Nordlys (nordlys) (yacht)                   6 nights · 3 stays · 148.4 h · 2026-06-13 – 2026-06-21 · with Anders Vik, Ola Nordmann, Sigrid Moen
        unnamed, by hours (the ids `places name` takes):
        47.3769,8.5417 (Zurich)                     3 nights · 3 stays · 58.5 h · 2026-06-08 – 2026-06-11 · with Marta Keller   stay:owner:20260608T0830Z@47.3769,8.5417
        59.0500,10.0300 aboard nordlys (Sandefjord) 2 nights · 2 stays · 40.7 h · 2026-06-17 – 2026-06-19   stay:owner:20260617T1200Z@59.0500,10.0300
        59.8500,10.6000 aboard nordlys              2 nights · 2 stays · 40 h · 2026-06-15 – 2026-06-20   stay:owner:20260615T1100Z@59.8500,10.6000
        55.6850,12.5500 (Copenhagen)                2 nights · 2 stays · 33.1 h · 2026-06-25 – 2026-06-27 · with Freja Lund   stay:owner:20260625T1630Z@55.6850,12.5500
        59.4300,10.4800 aboard nordlys (Sandefjord) 1 night · 1 stay · 17.9 h · 2026-06-16 – 2026-06-17   stay:owner:20260616T1300Z@59.4300,10.4800
```

An unnamed place reads as its coordinates; `aboard <asset>` when the stays were aboard one;
`near <place>, x km` for a named place within 5 km; else the city of the nearest large airport
within 30 km in parentheses, the rule `trips` and `day` label an unnamed stay by. A place's nights
are printed when there are any; an asset's always, since zero nights aboard a car is the point.

Under `--json`, each year has `places`, `aboard` and `unnamed`; each place, asset and unnamed
cluster carries `stays`, `hours`, `nights`, `first`, `last`, `people` and `lines`; an asset also
`asset`, `name` and `kind`; an unnamed cluster also `id`, `lat`, `lon`, `label`, `aboard`,
`nearest` (`{name, kind, metres}`, the closest named place whatever the distance) and `city`. Each
person under `people` carries their `stays`, `days` and `nights` at that place and the `lines`
that put them there. `unnamed_top` says how many clusters a year lists.

### Who, where: `--with`

`rollup places --with` turns the same reading into the place × person table: one row per person
per place, the places in the order the rollup lists them, the people by days there.

```
places 2026-06-01 – 2026-06-30 · with
  2026
        place                        person                   stays  days nights
        Office                       Per Hansen                  10    10      0
        Office                       Liv Berg                     9     9      0
        Marina                       Anders Vik                   2     2      0
        Marina                       Ola Nordmann                 2     2      0
        Marina                       Sigrid Moen                  1     1      0
        Cabin                        Ola Nordmann                 1     2      1
        Nordlys (nordlys)            Anders Vik                   2     2      0
        Nordlys (nordlys)            Ola Nordmann                 2     2      0
        Nordlys (nordlys)            Sigrid Moen                  1     1      0
        47.3769,8.5417 (Zurich)      Marta Keller                 1     1      1
        55.6850,12.5500 (Copenhagen) Freja Lund                   1     1      1
```

- **stays**: the stays at the place the person was confirmed at.
- **days**: the distinct local days of the evidence that put them there.
- **nights**: the nights at the place on a day they were there. A night counts for a person when
  the evidence that put them at the stay is dated the night's day: dinner on the 16th is the night
  of the 16th together, not every night of a four-night stay.

Under `--json` each year carries the rows under `with`: `place` (the place's name, the asset's id
or the unnamed cluster's stay id), `label`, `kind` (`place`, `asset`, `unnamed`), `id` and `name`
of the person, `stays`, `days`, `nights`, `lines`. `--with` goes with `places` only.

## People

`rollup people` is the year per person, from the **confirmed** set of the with module only: an
attendee of a timed calendar entry held at the stay, a participant of a transcript recorded inside
it whom the record resolves to a person, a note written inside it that says `with <name>`. A
tagged face and an all-day entry's attendee are proposals, and a proposal is not a day together:
it is not counted, not listed and not among the lines, so a person the record knows only by a face
does not appear here (the Day and the pages still show them as proposed). You are never your own
company (`present.owner_of`).

```
people 2026-06-01 – 2026-06-30
  2026
        Per Hansen               10 days · 0 nights · last 2026-06-30 · Office · 11 confirmed
        Liv Berg                 9 days · 0 nights · last 2026-06-29 · Office · 10 confirmed
        Ola Nordmann             3 days · 1 night · last 2026-06-15 · Cabin, Marina · 4 confirmed
        Anders Vik               2 days · 0 nights · last 2026-06-15 · Marina · 2 confirmed
        Jonas Weber              1 day · 0 nights · last 2026-06-09 · 47.3700,8.5300 (Zurich) · 1 confirmed
        Marta Keller             1 day · 1 night · last 2026-06-09 · 47.3700,8.5300 (Zurich), 47.3769,8.5417 (Zurich) · 2 confirmed
```

Per person: **days** together (the distinct local days of the confirmed evidence, by the
evidence's own day), **nights** together (the nights whose overnight stay they were confirmed at
on that day, the `--with` rule), the **last** real contact (the last such day), the **places**
shared (a named place, `aboard <asset>`, else the unnamed place's label) and the **confirmed**
evidence count. Under `--json` each carries `stays` (the stays shared) and `lines` too. A
confirmed name the record resolves to no person — an attendee with a display name and no
resolution line (RFC 0006) — is listed apart, under `unresolved`, so that a resolution can be
written for them.

## How it reads

Both rollups come from one `reading.read` of the window: the lines through the index
(`Index.between`, one sweep of the files), one `stays.derive`, the night of each day. The company
of a stay is read from `present.Evidence`, the window's evidence lines bucketed by every local day
their span touches, so each stay looks at the lines of its own days and nothing is read per place.
Nothing is written, not even `policy/stays.json`.

## Countries, flights, nights

`countries`: days per country per year from the overnight stay, by a place's own `country` else
the nearest large airport's zone; in-transit nights and nights whose country is unknown apart; the
method printed with the numbers. `flights`: count, kilometres between the airports table's
coordinates, long-haul (over 3,500 km), unmeasured, by evidence (`tracked`, `inferred`,
`declared`), from the flight lines standing (RFC 0013 rule 4). `nights`: home, away and in-transit
nights, nights aboard each asset, the longest run of nights not at home. A home region is a place
of kind `home`; a night whose stay centre is within 400 m of one is home whatever that place's
radius. Without a home place every night is away, and the rollup says so.

## Per month or week: health

`logbook rollup health [--year YYYY | --since YYYY-MM-DD --until YYYY-MM-DD] [--by month|week] [--json]`
sums the `health-sample/v1` lines (RFC 0014) up per calendar month, or per ISO week with `--by
week`. It reads the health lines of the window through the index and nothing else: no reading of
the track, so a record of health lines alone rolls up, and the window is clipped to the first and
last day with a health line.

Per period:

- **sleep** — the mean of the nights' hours, and how many nights had a line. A night is the one
  that ends on the day: its asleep stages (`asleep`, `core`, `deep`, `rem`; never `in_bed`, never
  `awake`), per device the union of their spans, so a night a source wrote twice counts once (rule
  4), and the longest device taken, never a sum across devices (rule 5).
- **steps** — the mean of the days' counts, and how many days. A day's count is the larger device
  per quarter hour, summed (rule 5).
- **resting** — the mean, lowest and highest of the days' resting heart rates in bpm, and how many
  days; a day's rate is the mean of its readings.
- **hrv** — when the record has any: the mean of the days' heart-rate variability (SDNN) in ms, and
  how many days.

The rules the numbers follow:

- **The latest correction wins.** A line another health line `supersedes` (a correction, such as
  the one `logbook repair health-units` writes) is out and the correction stands; when a line was
  corrected more than once, the latest correction stands and the earlier ones are out with it. A
  retracted line is out.
- **Units as stored.** A value is read in the unit its line states. A resting heart rate in
  `count/s` is multiplied by 60 to read in bpm; one in `bpm` or `count/min` is taken as it is.
  Sleep is the span's seconds in hours; steps are counts; HRV is milliseconds.
- **Missing is missing.** Every month or week the window touches is a row, including one with no
  line at all. A field no day of the period has a line for prints an em dash (`—`) and is `null`
  under `--json`; it is never a zero, because a zero would be a measurement.

```
health 2026-06-01 – 2026-08-20 · by month
  2026-06  sleep 6.5 h (2 nights) · 2,125 steps (2 days) · resting 57 bpm (54–60, 2 days) · hrv 45 ms (1 day)
  2026-07  sleep — · steps — · resting — · hrv —
  2026-08  sleep — · 5,000 steps (1 day) · resting — · hrv —
```

A week is an ISO week, `2026-W23`, Monday to Sunday, and belongs to the ISO year, so the first days
of January can fall in the old year's last week. A period at the window's edge is the part of it
inside the window, and `first` and `last` say which days under `--json`.

### The JSON

`--json` prints one object: `kind` (`health`), `window` (`since`, `until`, `days`), `by` (`month`
or `week`) and `periods`, one entry per period in order — `period` (`2026-06` or `2026-W23`),
`first` and `last` (its days inside the window), then `sleep` (`mean_h`, `nights`, `lines`),
`steps` (`mean`, `days`, `lines`), `resting_hr` (`mean`, `min`, `max`, `days`, `lines`) and `hrv`
(`mean_ms`, `days`, `lines`), each `null` when no day of the period has a line for it. Under
`lines` are the ids of the health lines each number came from: the asleep stages of the nights, the
winning quarter hours, the readings.

The same day rows feed `stats --health` and the health line of the [Day](day.md), so the three
agree on every day.

## Listening

`rollup listen` is the year per `listen/v1` line standing (RFC 0019), whichever adapter wrote it:
`spotify`, `apple-music`, `shazam`, `apple-podcasts`. Per year: the **listens**, the **hours** played
(`played_s` summed; a line with no playhead is a listen with no hours, counted under `untimed`), the
**skipped** lines, the lines per **service**, the podcast **episodes** with their hours, the **top
artists** by hours played then listens (ten, the performers as the services spell them, never
resolved), and **by month** every month the window touches with its hours, listens and skips — a
month with no listen is an em dash, never a zero. The window is clipped to the days the listen
lines cover; a correction that `supersedes` a line wins and a retracted line is out. It lives in
`logbook/listen_rollup.py`, beside `rollup.py` and in its manner. The adapters and the rollup are
described in [adapters/listen.md](adapters/listen.md).
