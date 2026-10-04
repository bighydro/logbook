# Health: Apple Health, Withings, MyFitnessPal, Google Fit

Four adapters write `health-sample/v1` (RFC 0014): one measurement the body made and a device
recorded — a weight, a heart-rate reading, a quarter hour of steps, a stage of one night's sleep, a
logged meal — with its number, its unit, the span it covers and the device, never what it means.
Every line is tier 3 (`logbook add --tier` lowers it). Interpretation is a reader's job: `logbook
stats --health`, `rollup health` and the Day sum the lines up.

```bash
logbook import-backup ~/backup --only health,withings,myfitnesspal   # the apps' own stores, from an iPhone backup
logbook add withings ~/Downloads/data_KN_1718000000             # the Withings data export, the folder as unzipped
logbook add withings ~/Downloads/data_KN_1718000000/weight.csv  # or one of its files
logbook add myfitnesspal ~/Downloads/Nutrition-Summary-2026-06-08-to-2026-06-14.csv
logbook add withings ~/Downloads/data_KN_1718000000 --dry-run   # what would be added, what the record has; nothing written
```

| Source | What it reads | What it writes |
|---|---|---|
| `apple-health` | `healthdb_secure.sqlite` from an encrypted iPhone backup | steps, distance, energy and flights in quarter-hour buckets per device; heart rate capped at one reading a minute; resting heart rate, HRV, weight; sleep stages and workouts as spans |
| `withings` | the app's per-profile stores from a backup, **or the account's data export** (below) | weight and body composition, one line per quantity; heart rate; from the export also sleep, steps, distance, calories and workouts |
| `myfitnesspal` | the app's `maindb.sqlite` from a backup, **or the account's CSV export** (below) | logged foods or meals as `energy_intake` in kcal; from the store also weights and exercise |
| `google-takeout-fit` | the `Fit/` folder of a Google Takeout ([page](takeout-fit.md)) | steps and distance in quarter-hour buckets per device, or per day where only the daily sheet has them; heart rate capped at one reading a minute; weight and body fat; sleep stages and workouts as spans; `source` is `google-takeout` |

The stores are what `import-backup` copies out of a phone backup; the adapters' module docstrings
have the tables. Google Fit comes only as a Takeout folder and has its own page; a phone running Fit
and a watch feeding Apple Health count the same quarter hour twice, and the record keeps both lines,
each under its source and device (rule 5), for a reader to choose between. This page is about the exports, which hold the whole history where a phone keeps
weeks, and about what happens when a later export changes a number.

## The Withings data export

*Settings → Download my data* on the Withings site sends a zip; unzip it and add the folder.
`logbook add <folder>` recognises it without the adapter's name. The files read, by name — any other
file of the export is left alone — and the columns found by header, so a column the reader does
not need may be missing or renamed; a file without one it needs is counted (`CSV files without
the columns this reader needs`), never a traceback:

| File | Lines |
|---|---|
| `weight.csv` | one standing per row: `weight`, `fat_mass`, `bone_mass`, `muscle_mass`, `body_water` (the export's *Hydration*), each its own line at the same instant (rule 9), and `body_fat_pct` or `bmi` when the export carries them; a mass in pounds is converted to kg with the entered value under `extra.original`; a comment under `extra.comment` |
| `bp.csv` | the cuff's pulse as `heart_rate` (`raw_id` `heart_rate:bp:<at>`) with the pressures beside it, `extra.systolic_mmhg` and `extra.diastolic_mmhg`: blood pressure is no type of the profile (rule 8), and `extra` is what else the source reports; a row without a pulse is counted |
| `sleep.csv` | one `in_bed` span per night, `from` to `to`, the totals the export computed (light, deep, REM, awake seconds; the night's average, lowest and highest heart rate) under `extra`; a reader never sums `in_bed` (rule 4) |
| `raw_<device>_sleep-state.csv` | the stages: one `sleep` span per run of equal states — 0 `awake`, 1 (light) `core`, 2 `deep`, 3 `rem` — with the device (`tracker`, `bed`); a state this version does not know is counted |
| `raw_<device>_hr.csv` | `heart_rate` in bpm, the first reading of each minute per device (rule 3); the rest counted |
| `raw_<device>_steps.csv`, `…_distance.csv`, `…_calories-earned.csv` | `steps`, `distance` (m), `active_energy` (kcal), summed into quarter hours aligned to the UTC hour, one bucket per device (rule 2), `extra.samples` how many samples went in |
| `activities.csv` | one `workout` span per activity, `value` its duration in seconds, the type under `extra.activity`, the steps, calories and distance the row's `Data` carries under `extra`, `tz` the row's zone |
| `height.csv`, `raw_*_elevation.csv` | counted, `of a type this version does not know` |
| `aggregates_*.csv` | the export's daily totals, derived data: counted, `daily totals` |

The raw files hold one row per run of samples: `start` with its offset, then `duration` and
`value` as lists, one sample per pair, each starting where the one before ended; the reader walks
them out. A naive clock (`weight.csv`, `bp.csv`: `2026-06-08 07:12:33`) is the account's local time
and is read in the record's zone; a stamp with an offset is taken as it says. `tz` is the record's
zone, since an offset names no zone. `device` is the export's own word for it (`tracker`, `bed`) on
the raw files' lines, and absent on the scale's and the cuff's, which the export does not name.

`raw_id` is the instant: `weight:2026-06-08T05:12:33Z`, `heart_rate:tracker:…`,
`steps:<bucket start>:tracker`, `sleep:night:<from>`. A later export of the same account gives the
same keys, so adding it again appends nothing — unless a sample changed (below).

## The MyFitnessPal export

*Settings → Export data* on the MyFitnessPal site mails a zip with `Nutrition-Summary-<from>-to-<to>.csv`
(one row per meal per day: date, meal, calories, then the macros and a note). `logbook add
myfitnesspal <file>`, or `logbook add <file>`, writes one `energy_intake` line per row (rule 10):

- `value` the calories as the export summed them, unit `kcal`; `source_name` `MyFitnessPal`.
- A span over that local day in the record's zone — `at` midnight, `end` the next midnight —
  with `extra.all_day` true: the export keeps the day and never the clock, and nothing is invented
  about when it was eaten.
- `extra.meal` the meal; every other numeric cell under `extra` keyed by its header slugged —
  `fat_g`, `carbohydrates_g`, `protein_g`, `sodium_mg`, and `saturated_fat`, `fiber`, `sugar`,
  `cholesterol`, `potassium`, `vitamin_a` … unitless as the export leaves them; `water_ml` when the
  export carries water; the note under `extra.note`. Nothing about nutrition beyond kilocalories
  is a type of the profile, so the macros and the water ride on the meal's line.
- `raw_id` `energy_intake:<date>:<meal>` (`energy_intake:2026-06-08:breakfast`), the same in every
  later export.

`Date`, `Meal` and `Calories` are the columns it needs; a file without them is counted. A row with
no number in `Calories` is counted (`without a value`), one whose date will not parse too (`with an
unusable date`). The exercise and measurement summaries the same zip may hold are not read yet.

## When a later export corrects a sample

An export is a snapshot. A weight re-measured, a meal re-logged, a night the app re-scored comes
out of the next export under the same date, so the same `raw_id` — and appending it would be deduped
against the line already there, keeping the old number. Instead `logbook add` hands the adapter the
record's standing line for each key (one batched lookup through the index per round, never one per
line), and a draft whose sample differs from what stands — `value`, `end`, `stage`, `device`, `unit`
or `extra` — is written as a correction: `raw_id` suffixed `:v2` (`:v3` … when corrected before) and
`supersedes` the id of the line it replaces. The old line stays, as every line does; a reader that
follows `supersedes` (`health.standing`: `stats --health`, `rollup health`, the Day) sees the
correction only, the latest when there are several. `add` says `1 corrected` beside what it added.
A draft equal to what stands appends nothing; adding the first export again after a correction
writes it as the next version, since the record's latest number is not the one it carries.

This is the one place an adapter writes `supersedes` (RFC 0014's payload table); `logbook repair
health-units` is the other writer, with the same suffix rule.

## `--dry-run`

`logbook add <adapter> <path> --dry-run` runs the adapter and prints what would be added, how many of
its lines the record already has (the dedupe `append_many` would do, asked of the index in one
batch) and what was skipped, and writes nothing — not a line, not a correction. It goes with a file
or folder, never a sentence.
