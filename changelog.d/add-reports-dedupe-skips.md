### Fixed
- `logbook add` says how many of an export's rows the record already held (same source and `raw_id`) beside what it
  added, where it skipped them silently before: `added 0 lines from dawarich` is followed by `40 already in the record
  (same source and raw_id), nothing written twice` (#79).
