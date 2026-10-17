### Fixed
- The Day shows a Notion row once when `sync notion --relations-backfill` saw it again: the backfill's
  `relations` line folds into the page's own line on the day, which stands for both (`--json` lists
  both ids under `lines`, `notion` its one source). It showed as two rows in `day` and on the Day page
  of `logbook serve`, and counted twice in a stay's attachments under `days`. `show` lists both lines,
  as it lists every line ([the Day](docs/day.md)).
