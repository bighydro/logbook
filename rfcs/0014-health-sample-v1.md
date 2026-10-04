# RFC 0014 — payload profile `health-sample/v1`

Status: draft · 2026-10-01 (body composition, energy intake and relayed readings added the same day) · comment period: two weeks

One measurement the body made and a device recorded: a count of steps in a quarter of an hour, one
heart-rate reading, a stage of one night's sleep, a weight, a workout. The line records what the
store said — a number, its unit, the span it covers and the device that measured it — and never
what it means: no "good night", no "active day", no target. Interpretation is an engine's job
(ADR 0013).

## Line

`kind` MUST be `health`. `tier` SHOULD be 3: SPEC §4 lists health under tier 3, and a step count,
a heart rate and a night's sleep are the owner's body, the class of fact the spec keeps most
private, however harmless one reading looks. An adapter MAY let the owner lower it (`logbook add
--tier`); the profile does not. `at` is the sample's start in UTC; `end` is its end when the sample has
a span (a bucket, a sleep stage, a workout), `null` for an instant (a heart-rate reading, a weight).
`tz` is the zone the device recorded the sample in when the store keeps it, else the record's.
`source` is the adapter: `apple-health`, …

## Payload

| Field | Type | Req | Meaning |
|---|---|---|---|
| `schema` | `"health-sample/v1"` | MUST | |
| `raw_id` | string | MUST | `<type>:<data_id>` for a sample the store keeps as one row; `<type>:<bucket start>:<device>` for an aggregated bucket (rule 2). The dedupe key: re-importing the same store appends nothing |
| `type` | string | MUST | what was measured, one of the table below |
| `value` | number | MUST | the measurement in `unit` |
| `unit` | string | MUST | the unit `value` is in, fixed per `type` (below) |
| `stage` | string | `sleep` only | `in_bed`, `asleep`, `awake`, `core`, `deep`, `rem` — as the source spells its own stages, mapped to these tokens |
| `device` | string | SHOULD | the device that measured it, as the store identifies it (a product type such as `Watch7,1`, `iPhone14,2`); absent when the store does not say |
| `source_name` | string | MAY | the name the store shows for the source (`Apple Watch`, a third-party app) |
| `supersedes` | string | MAY | the `id` of the line this one corrects (SPEC §3, RFC 0003 rule 2); written by `logbook repair`, and by an adapter only for a sample a later export of the same account changed (rule 12), never otherwise |
| `extra` | object | MAY | anything else the source reports: `samples` in a bucket, `activity` and `activity_type` of a workout, `energy_kcal`, `distance_m`, the sample's `original` quantity and unit |

Types and their units:

| `type` | `unit` | shape |
|---|---|---|
| `steps` | `count` | bucket |
| `distance` | `m` | bucket |
| `active_energy` | `kcal` | bucket |
| `basal_energy` | `kcal` | bucket |
| `flights_climbed` | `count` | bucket |
| `heart_rate` | `bpm` | instant |
| `resting_hr` | `bpm` | instant |
| `hrv` | `ms` | instant (SDNN) |
| `weight` | `kg` | instant |
| `body_fat_pct` | `%` | instant; body fat as a share of weight |
| `fat_mass` | `kg` | instant |
| `fat_free_mass` | `kg` | instant |
| `muscle_mass` | `kg` | instant |
| `bone_mass` | `kg` | instant |
| `body_water` | `kg` | instant; total body water as the scale estimates it |
| `bmi` | `kg/m2` | instant; as the source computed it, never recomputed here |
| `vo2_max` | `mL/kg/min` | instant |
| `energy_intake` | `kcal` | instant (or a day's span when the source keeps no time); one logged food or meal |
| `sleep` | `s` | span, with `stage` |
| `workout` | `s` | span; `value` is the workout's duration |

## Rules

1. **One line per sample, except where the source is a firehose.** A heart-rate reading, a sleep stage, a weight, a workout: one row in the store is one line.
2. **High-frequency counts are bucketed.** `steps`, `distance`, `active_energy`, `basal_energy` and `flights_climbed` are summed into buckets of 15 minutes aligned to the UTC hour (`:00`, `:15`, `:30`, `:45`), one bucket per device; `at` is the bucket's start, `end` its end, `value` the sum of the samples whose start falls inside it, `extra.samples` how many there were. A phone that counts steps for a day writes at most 96 lines of them. `raw_id` is `<type>:<bucket start RFC3339>:<device>`, so a re-import of the same store gives the same lines. A bucket is written once: samples for that bucket that reach the store after it was imported are not added (a later backup is taken days later; the store's own sync lag is hours).
3. **Heart rate is capped at one reading per minute per device.** The first reading in a UTC minute is the line; later ones in that minute are skipped and counted. A chest strap that reports every second still gives 1,440 lines a day.
4. **Sleep stages are spans.** One line per stage segment as the source stores it, `value` the segment's length in seconds, `stage` the token. `in_bed` and `awake` are lines too: they are what the device observed. A reader summing a night adds `asleep`, `core`, `deep` and `rem` and never `in_bed` or `awake`; it takes, per device, the union of those spans, not their sum — a source may write the same night twice (an app that syncs a night again, two overlapping sets of stages from one phone) — and then the longest device (rule 5).
5. **Two devices are two observations.** When a watch and a phone both count the same quarter hour, both lines are written, each with its `device`. The profile does not choose between them; a reader that wants one number takes, per bucket, the device with the larger count (the source's own display rule, approximately). A line never sums across devices.
6. **Units are the profile's, converted from the source's canonical unit by the adapter** and stated in the adapter's documentation; the source's own quantity and unit, when it keeps them, go under `extra.original` so the conversion can be checked later.
7. **Timestamps are the source's.** The adapter converts the source's epoch to UTC and does not "correct" it. Rows dated before 1900 are placeholders, not samples, and are skipped and counted (RFC 0012 rule 4).
8. **A sample of a type this profile does not name is skipped and counted, never mapped to a near type.** A later profile version adds types; a reader that meets a `type` it does not know keeps the line and shows nothing.
9. **Body composition is one line per quantity.** A smart scale reports a weight and, with it, fat mass, muscle mass, bone mass, water and a BMI from one standing; each is its own line with the same `at`, and a reader groups them by `at` and `device`. Percentages are written as the source gives them (`body_fat_pct`), never derived from the masses here.
10. **A logged food is `energy_intake`.** One line per food or meal entry, `value` its energy in kcal as the source computed it from its portion and quantity, with the meal's name, the food's description and the portion under `extra`. A source that keeps the day but not the clock writes the entry as a span over that local day (`at` midnight, `end` the next) with `extra.all_day` true; nothing is invented about when it was eaten. A daily total the source keeps beside the entries is derived and is not written (rule 2 and the note on daily totals).
11. **A reading relayed from another app is not this source's.** A health app that mirrors another app's data (Withings reading Apple Health, which carries a watch's readings) is a second copy, not a second device; an adapter skips rows whose source is another app and counts them (`skipped_relayed`), so that the record gets them once, from the adapter of the app that made them.
12. **A later export that changes a sample is a correction, never a rewrite.** An account's export is a snapshot keyed by the sample's instant, so a weight re-measured or a meal re-logged comes out of the next export under the same `raw_id`; appended as it is, it would be deduped and the record would keep the old number. The adapter, given the record's standing line for the key (`logbook add` passes `existing`), writes the changed sample with `raw_id` suffixed `:v2` (`:v3` … when corrected before; the suffix `logbook repair health-units` also uses, so the dedupe key never takes it for the old line) and `supersedes` the id of the line it replaces, the latest version standing. A sample equal to what stands is appended by nothing; the old line is never touched; a reader that follows `supersedes` (rule under `health.standing`) sees the correction only. Sources: `withings` and `myfitnesspal` from their exports.

## Example (synthetic)

```json
{"at":"2026-03-02T07:00:00Z","end":"2026-03-02T07:15:00Z","tz":"Europe/Oslo","source":"apple-health","kind":"health","tier":3,
 "payload":{"schema":"health-sample/v1","raw_id":"steps:2026-03-02T07:00:00Z:Watch7,1","type":"steps","value":250,"unit":"count",
 "device":"Watch7,1","source_name":"Apple Watch","extra":{"samples":3}}}
```

```json
{"at":"2026-03-01T23:30:00Z","end":"2026-03-02T00:30:00Z","tz":"Europe/Oslo","source":"apple-health","kind":"health","tier":3,
 "payload":{"schema":"health-sample/v1","raw_id":"sleep:1042","type":"sleep","value":3600,"unit":"s","stage":"deep","device":"Watch7,1"}}
```

## JSON Schema

```json
{"$schema":"https://json-schema.org/draft/2020-12/schema","title":"health-sample/v1","type":"object",
 "required":["schema","raw_id","type","value","unit"],
 "properties":{
  "schema":{"const":"health-sample/v1"},
  "raw_id":{"type":"string","minLength":1},
  "type":{"enum":["steps","distance","active_energy","basal_energy","flights_climbed","heart_rate","resting_hr","hrv","weight","body_fat_pct","fat_mass","fat_free_mass","muscle_mass","bone_mass","body_water","bmi","vo2_max","energy_intake","sleep","workout"]},
  "value":{"type":"number"},
  "unit":{"enum":["count","m","kcal","bpm","ms","kg","%","kg/m2","mL/kg/min","s"]},
  "stage":{"enum":["in_bed","asleep","awake","core","deep","rem"]},
  "device":{"type":"string","minLength":1},
  "source_name":{"type":"string","minLength":1},
  "supersedes":{"type":"string","minLength":1},
  "extra":{"type":"object"}},
 "additionalProperties":false}
```

## Notes

- **Units as the store keeps them (`apple-health`, checked against a real store on 2026-10-01).** HealthKit does not keep every quantity in one canonical unit per dimension, so the adapter's conversions were checked type by type against `quantity`, `original_quantity` and `unit_strings` in a real `healthdb_secure.sqlite`: heart rate (data type 5) is stored in count/s, its original in count/min, so the adapter multiplies by 60; resting heart rate (118) is stored in count/min already (its original, where kept, in count/s), so it is not rescaled — an earlier ×60 made resting rates read in the thousands; HRV SDNN (183) is stored in ms already, not rescaled — an earlier ×1,000 made it read in the hundreds of thousands; body mass (3) in kg, its original in g; walking and running distance (8) in m; active and basal energy (9, 10) in kcal; steps (7) and flights (12) as counts; sleep stages and workouts as seconds. A record the adapter wrote before this check carries `resting_hr` sixty times and `hrv` a thousand times too large; the lines are not rewritten (nothing ever is), and a re-import appends nothing (`raw_id`). The migration is `logbook repair health-units`: for every standing `apple-health` `resting_hr` or `hrv` line it appends the corrected line — the same fields, `value` divided by 60 or 1,000, `raw_id` suffixed `:u2` so the dedupe key does not take it for the old line, `supersedes` the old line's `id` — and then a retraction of the old line (RFC 0003, `source` `logbook`); `--dry-run` prints the counts and writes nothing, and a second run finds nothing to repair. A reader that follows RFC 0003 then sees the corrected lines only.
- **Why buckets and not the raw samples.** A watch writes a step sample every few minutes and an energy sample every minute; a year of that is over a million lines, none of which anyone reads. A quarter hour is fine enough to see a walk and coarse enough to keep the record small; the store keeps the raw rows if anyone ever needs them.
- **Why the device is on the line.** Health data is the one source where two devices legitimately report the same thing; a reader cannot dedupe without knowing which device said what.
- **Why no daily totals here.** "8,412 steps on Tuesday" is derived: an engine (or `logbook stats --health`) sums the buckets. Writing the total as a line would make a re-import with one more bucket a contradiction.
- **What is not a health sample.** A workout's route is `location/v1`; a medication and a symptom are not this profile; a lab result is a document, another profile. A meal is here only as the energy the source assigned it (`energy_intake`, rule 10): what was eaten is under `extra`, and nothing about nutrition beyond kilocalories is a type.
- **Sources.** `apple-health` (an iPhone's Health store), `withings` (the Withings app's own stores: the scale's weight and body composition, the app's heart-rate readings; and the account's data export: the same, with the cuff's pulse — the pressures under `extra`, blood pressure being no type here —, the nights as `in_bed` spans and the tracker's stages, heart rate, steps, distance and calories, the activities as `workout`), `myfitnesspal` (logged foods as `energy_intake`, weights, exercise as `workout`; from the account's CSV export one `energy_intake` per meal per day, the macros and water under `extra`), `google-takeout-fit` (the `Fit/` folder of a Google Takeout, `source` `google-takeout` as every Takeout product: the streams as buckets, readings and sleep stages, the sessions as workouts, and a day-long `steps` or `distance` span, `extra.period` `day`, for a day only the daily sheet has — the one span of a bucketed type longer than a quarter hour, so a reader keying buckets by `at` meets it as that day's first bucket). `docs/adapters/health.md` has the exports' files and columns.
