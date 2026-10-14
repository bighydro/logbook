### Fixed
- `dream --catch-up`, which the 06:00 close runs, synthesizes only the calls of the last 7 days (by the
  call's own start on the record's `day_start`), never a record's whole backlog of transcripts at once:
  an older call without a synthesis is counted and named in one line (`N calls before DAY not
  synthesized; run …`) and sent only when you ask, with `dream --catch-up --since DAY` or `transcript
  synthesize --day DAY`. The close never passes `--since`; the days it dreams are unchanged (the last
  14). `doctor` has a `synthesis` line counting the calls without a synthesis inside the week, before it
  and above the `dream` entry's ceiling ([the synthesis of a call](docs/transcript-synthesis.md)).
