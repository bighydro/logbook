### Added
- The Night line: `day` has a `night` row under the night before when a night ends on the day,
  `slept 23:10–06:40 · 7 h 20 min · training 45 min`, derived at read time from the
  `health-sample/v1` lines already in the record (sleep stages and workouts); nothing is written. A
  night is one device's asleep stages with no gap over two hours, on the local day its last stage
  ends in under `day_start`, so a night across a 06:00 boundary is one night, never split; the
  longest device, never a sum. Training is the union of the day's workout spans. The JSON carries
  `night` only on such a day. The Day's text says the sleep once, on that row: the health row keeps
  the steps and the resting heart rate, and `sleep_h` stays in the JSON (docs/day.md).
- `day` says the weather in short beside the place of the night after, `Home · home · 4° · rain`.

### Changed
- `logbook sync weather` asks nothing unless `LOGBOOK_WEATHER=1` is set, by name as in `sync --all`:
  it is the source's one setting. Unset, the command says so and exits 2 without a request. The
  first run asks about yesterday alone, no longer the record's whole history (`--since` backfills),
  and the week's lookback never reaches before the first day a run covered (docs/adapters/weather.md).

### Fixed
- The health row lost the record's `day_start` for every line read after the first sleep stage.
- Under a `day_start`, the Day showed no weather: a weather line starts at midnight, on the page of
  the day before. The Day now takes it by its own day.
