# The rollups

`logbook rollup <kind> [--year YYYY | --since YYYY-MM-DD --until YYYY-MM-DD] [--json]` sums the
record up over a window of days. Every rollup is a reader (ADR 0013): a function of the record at
its head, derived every time and never written, and under `--json` every number carries the ids of
the lines it came from. The window is the whole record unless `--year` or `--since`/`--until` narrow
it, and it is clipped to the days the rollup's own lines cover, so a day the record knows nothing
about is nothing, not a night in transit and not a zero.

```bash
logbook rollup countries --year 2026    # days per country from the overnight stay; in transit apart
logbook rollup flights                  # count, km, long-haul, by evidence, from the flight lines standing
logbook rollup nights                   # home, away, in transit, nights aboard, the longest trip
logbook rollup places                   # stays, hours, first and last, people, per named place and per asset
logbook rollup people                   # days together, last real contact, places shared, per resolved person
logbook rollup health --by week         # sleep, steps, resting heart rate, HRV, per month or ISO week
```

## Per year: countries, flights, nights, places, people

These five read the owner's track through one reading of the window (`reading.read`): the stays
`derive stays` finds, the night of each day, the flight lines standing, and the people the with
module places at each stay. They answer per calendar year.

- **countries** — days per country from the overnight stay; nights in transit and nights whose
  country is unknown listed apart; the method printed with the numbers (a place's own `country`,
  else the nearest large airport's zone within 300 km, coarse near borders).
- **flights** — count, kilometres between the airports table's coordinates, long-haul flights
  (over 3,500 km), flights whose airport the table does not know (`unmeasured`), and counts by
  evidence (`tracked`, `inferred`, `declared`), each flight listed with its route.
- **nights** — home, away and in-transit nights, nights aboard each asset, and the longest trip
  (the longest run of consecutive nights not at home). Without a place of kind `home` every night
  is away, and the rollup says so.
- **places** — per named place and per asset: stays, hours, first and last visit, an asset's
  nights aboard, and the people confirmed present.
- **people** — per resolved person: days together, the last real contact, the places shared,
  confirmed and proposed evidence; names that resolve to no person apart, under `unresolved`.

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
