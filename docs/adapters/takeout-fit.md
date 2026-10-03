# Takeout: Fit → `health-sample/v1`

`Takeout/Fit/` is what Google Fit kept of the owner's body: the raw streams a phone, a watch and a
scale wrote, the workouts the owner started, and a daily sheet. The adapter is `google-takeout-fit`
(`takeout-fit`); `logbook add` recognises the `Fit/` folder, each of its three subfolders and any
one of their files:

```bash
logbook add ~/Takeout/Fit
logbook add takeout-fit ~/Takeout/Fit/"All Sessions" --dry-run
logbook add takeout-fit ~/Takeout/Fit/"Daily activity metrics"/"Daily activity metrics.csv"
```

Every line is `health-sample/v1` (RFC 0014) at tier 3 (`--tier` lowers it), `source`
`google-takeout`, `kind` `health`, with the same types and units `apple-health` writes, so `logbook
stats --health`, `rollup health` and the Day read them without knowing which phone they came from.

## The three families

| Folder | Files | Lines |
|---|---|---|
| `All Data/` | one JSON per data source: `{"Data Source": …, "Data Points": [...]}`, every point with its type, nanosecond start and end, value and the source that measured it | `steps` and `distance` in quarter-hour buckets per device; `heart_rate` at its own resolution, one reading a minute per device; `weight`, `body_fat_pct`; `sleep` stages as spans |
| `All Sessions/` | one JSON per workout: activity, start, end, duration, aggregates, the app | one `workout` span each; a `sleep` session is the night in bed |
| `Daily activity metrics/` | `Daily activity metrics.csv`, one row per day; `<YYYY-MM-DD>.csv`, the same figures per quarter hour of that day | the fallback: buckets from a day's quarter hours, a day-long `steps` and `distance` span for a day no stream touched |

`Activities/` (one TCX per workout, the route inside) is not read.

### The streams

| `dataTypeName` | Type | Unit | Shape |
|---|---|---|---|
| `com.google.step_count.delta` | `steps` | `count` | summed into 15-minute buckets aligned to the UTC hour, one per device (rule 2), `extra.samples` how many points went in; `raw_id` `steps:<bucket start>:<device>` |
| `com.google.distance.delta` | `distance` | `m` | the same |
| `com.google.heart_rate.bpm` | `heart_rate` | `bpm` | one line per reading, at most one per UTC minute per device, the rest counted (rule 3); `raw_id` `heart_rate:<start nanos>:<device>` |
| `com.google.weight` | `weight` | `kg` | one line per point |
| `com.google.body.fat.percentage` | `body_fat_pct` | `%` | one line per point |
| `com.google.sleep.segment` | `sleep` | `s` | one span per segment, Fit's stage as the profile's: 1 `awake`, 2 `asleep`, 4 (light) `core`, 5 `deep`, 6 `rem`; 0 (unspecified) and 3 (out of bed) counted (rule 4) |

Any other stream is counted, one per file, and never mapped to a near type (rule 8):
`com.google.calories.expended` counts the basal rate in, so it is neither `active_energy` nor
`basal_energy`; `com.google.activity.segment` is what the sessions already say; active minutes,
Heart Points, height and speed have no type. When the export holds Google's own merged stream of a
type (`derived:com.google.step_count.delta:…:merge_step_deltas`), the raw streams of that type are
the same points before merging and are counted (`raw stream files whose points the merged stream
carries`), so a reading is written once; each merged point still names the source that measured it.

`device` is the manufacturer and model that source names (`Google Pixel 8`, `Fossil Gen 6`,
`Withings Body+`), `source_name` the package of the app that recorded the point
(`com.google.android.gms`, `com.google.android.apps.fitness`, a third-party app). A device uid is
never written. Timestamps are the export's, converted from nanoseconds to UTC and never corrected;
`tz` is the record's zone, since Fit keeps offsets and an offset names no zone. A point without a
start, or with one at or before 1970, is counted. The streams are read one point at a time (`ijson`),
whatever their size.

### The sessions

One `workout` span per session file: `at` and `end` its start and end, `value` the duration in
seconds (the file's `duration`, else the span), `source_name` the app (`application.packageName`),
`raw_id` `workout:<id>` when the session has one, else `workout:<start>:<activity>`. Under `extra`:
`activity` in the vocabulary `apple-health` uses (`biking` → `cycling`, `strength_training` →
`traditional_strength_training`, `interval_training.high_intensity` → `hiit`; an activity with no
such name keeps Fit's own), `activity_type` as Fit spells it, and the aggregates as `steps`,
`distance_m`, `energy_kcal`, `heart_points`, `move_minutes`; the session's `name` when the owner gave
it one. A session whose activity is `sleep` is the night in bed: a `sleep` span with stage `in_bed`,
`raw_id` `sleep:session:<start>`, the stages coming from the stream; a reader never sums `in_bed`
(rule 4). A session that ends before it starts is counted.

### The daily CSVs

The quarter-hour file of a day (`2026-06-12.csv`: `Start time`, `End time`, `Step count`,
`Distance (m)`, …) is read as a stream would be: each window's steps and distance go into the
buckets, with no device (`-` in the `raw_id`). `Daily activity metrics.csv` is read last, and only
for a day that no stream and no window touched, per type, in the record's zone: one `steps` and one
`distance` line spanning that local day, `raw_id` `steps:day:2026-06-10`, `extra.period` `day`.
The day's figures the profile has no type for — `calories_kcal`, `heart_points`, `move_minutes`,
`heart_rate_avg_bpm`, `heart_rate_max_bpm`, `heart_rate_min_bpm` — ride under `extra` of that
day's `steps` line (the `distance` line when the day has no step count); they are Fit's own
derived totals and are not written for a day the streams cover. A day the streams cover is counted
(`daily rows for days the quarter-hour streams already cover`); a row with neither steps nor
distance too. The latitude, longitude, speed and weight columns are never read: a day's bounding
box is a location, and the daily weight is derived from the stream. Columns are found by what the
header says, so a renamed or missing one still reads; a CSV without a `Date` or `Start time` column,
or without any of the step, distance, Heart Points and Move Minutes columns, is counted.

## Beside Apple Health

A phone that runs Fit and a wrist that runs Apple Health count the same quarter hour twice, and the
record keeps both: an `apple-health` bucket and a `google-takeout` bucket with the same `at`, each
naming its device (rule 5). Nothing here dedupes across sources, and `raw_id`s are keyed per source,
so re-adding either export appends nothing and adding both appends both. A reader that wants one
number takes, per bucket, the larger device, as `logbook stats --health` does; a day-long Fit span
beside a day of Apple Health buckets is one more "device" at that day's first bucket, and the
reader's rule takes the larger. Choosing between the two for the same quarter hour is a reader's
decision the record does not make yet.

The fixture is `tests/fixtures/takeout/Fit/`, a synthetic week of the Oslo persona, who does not
exist: a phone and a watch counting the same morning, a scale, one night's stages, three sessions
and the daily sheet, with a TCX under `Activities/` to show what is left alone.
