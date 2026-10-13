### Added
- `goal add TEXT --horizon life|year|quarter [--from DAY] [--until DAY] [--supersedes GOAL]` writes one
  `goal/v1` line (RFC 0036) in your words, tier 2 and source `manual`; a goal reworded is a new goal that
  supersedes the old, and the chain is one goal. `goal review GOAL advancing|stalled|done|let-go|superseded
  [--note TEXT] [--at DAY|RFC3339] [--period day|week|month|quarter|year]` writes your verdict as one
  `review/v1` line on the day it is about, `recorded_at` saying when you wrote it; one verdict per goal,
  period and day, never in the future or before the goal's first day. `goal list [--open] [--json]` lists
  every standing goal with its latest review. `goal import FILE` is the first backfill: one goal per line of
  a text file (`text | horizon | from`), and `--review let-go --at 2026-08-31` applies one verdict to all of
  them, every line checked before any is written (docs/goals.md).
- `chapter open NAME [--from DAY] [--to DAY] [--rules TEXT]`, `chapter close [--to DAY]` and `chapter list
  [--json]`: a named stretch of your life as one `chapter/v1` line, tier 2; chapters do not overlap, the same
  name from the same day is written once, and closing writes the chapter again with its last day.
- Every one of these writers holds the writer lock for its whole run and reads the head again before it
  appends: a head that moved under it writes nothing, exit 2; `--no-wait` refuses while another command writes.
- The Day names the chapter a day is in, in its header after the signed state, lists a row per goal review on
  the day the verdict is about with the goal's current text and `written <when>` when it was written later,
  and lists the goal and chapter lines written on the day, marked when superseded; under `--json` as
  `chapter`, `reviews`, `goals` and `chapters`, each only on a day that has one. `show` and the `serve` Day
  page show the same; under a ceiling of 1 none of it is there.
