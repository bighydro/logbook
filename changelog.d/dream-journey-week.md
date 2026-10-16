### Added
- `dream journey ID` drafts a journey once it has come home, and the first 06:00 close after it does
  dreams it: the trip as a whole, its days, places with their hours, who was on it, what was decided
  and promised, the photos it would star and one name it proposes. `show trips` and `show trip` carry
  the draft (`draft` or `draft_withheld` under `--json`, when it has one).
- `dream week [DAY|YYYY-Www]` drafts an ISO week from its seven days and their drafts once its Sunday is
  over, and the close of each Sunday dreams it: the time by place, person and thread, sleep and training
  when the health lines cross (else no data), who moved against the week before, the promises open both
  ways, a review proposed for each open goal, one proposal for next week and a personal part. Every
  figure is computed from the lines, with their ids; a sentence that writes another is marked
  unsupported. `day` of a Sunday carries it (`week`, `week_draft`, `week_draft_withheld` under `--json`).
- Both follow the `dream` entry as a day's draft does: read under its ceiling, the version recorded,
  withheld by the readers when the entry no longer allows them, dreamed again by `--catch-up` when their
  lines or the entry change.
