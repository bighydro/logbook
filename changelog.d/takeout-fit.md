### Adapters
- `google-takeout-fit` (`takeout-fit`), the `Fit/` folder of a Google Takeout → `health-sample/v1` (RFC 0014) at tier 3,
  with the types and units `apple-health` writes, every line naming the device and the app Fit recorded it from
  ([page](docs/adapters/takeout-fit.md)). `All Data/`: steps and distance summed into quarter-hour buckets per device,
  heart rate at its own resolution capped at one reading a minute, weight, body fat, and sleep stages as spans (light as
  `core`); the raw streams of a type Google also merged are counted, not read twice; calories, activity segments and the
  other streams the profile has no type for are counted, never mapped to a near type. `All Sessions/`: one `workout` span
  per session with its aggregates under `extra`, a sleep session as the night in bed. `Daily activity metrics/`: a day's
  quarter-hour file as buckets, and a day-long `steps` and `distance` span for a day no stream touched, the day's
  calories, Heart Points, Move Minutes and heart-rate figures under `extra`; the coordinate columns never read. The
  `Fit/` folder, each subfolder and any one file are sniffed; `Activities/` (TCX) is not read. A quarter hour Apple
  Health also counted stays a second line under its own source: nothing dedupes across sources yet. Synthetic fixture.
