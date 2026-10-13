### Added
- `day_start` (RFC 0036): `logbook setup day_start 06:00` writes `"day_start": "06:00"` to
  `logbook.json`, and from then on a line whose local clock is before 06:00 belongs to the day
  before. Every reader that puts a line on a day goes by it, from one rule: the index, `show`, `day`
  and `days`, the nights before and after a day, `trips`, `doctor sources --gaps`, the digest, the
  signed day's page and the crossing of signed days, promises, the rollups, the Year, people, the
  vault, the printed pages, the shared page, the MCP tools' days and `serve`'s pages, `/today`
  included. The comparison is on the wall clock, so the night the clocks change moves no line; no
  line, hash or month file changes. The Day's header says `06:00 to 06:00 the next day` and its JSON
  carries `day_start` when the day does not begin at midnight, and only then. Setting it rebuilds an
  index that exists and counts the signed days whose page moved; a value that is not a clock `HH:MM`
  is refused by every reader that groups by day, naming it (docs/settings.md).
- `logbook doctor` has a `day-start` line when the day does not begin at midnight, warns when the
  index was built under another boundary, and fails a value that is not a clock.
- The schedule runs four times a day: `sync --scheduled` at 00:00, 12:00 and 18:00 local, and `sync
  --scheduled --close` at 06:00, which runs `dream --catch-up` after the sync when this version has
  the dream and `policy/crossing.json` a `dream` entry (else one line saying why not), then the rest
  of the run and one summary line. Two launchd agents or two systemd user timers; `sync
  --install-schedule --system` writes daemons or system units for a machine nobody logs in to and
  prints the two sudo commands that install them, as `serve --install-service --system` does.
  Installing again moves a schedule of two runs to the four; `--uninstall-schedule` removes them all.
  The Sunday message comes from the 18:00 run.
