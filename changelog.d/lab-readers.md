### Added
- The lab (`docs/labs.md`, `logbook/labs/`): readers still finding their shape, run as `logbook lab <reader>`; read-only,
  no network, not in SPEC §3.2, their JSON free to change. `logbook lab introductions [--json]`: for every person the
  record confirms present at a stay with the owner, the first day it does, where and by which source, and who else
  was confirmed present that day — those known before as the likely introducers, those also new as met together,
  each marked `same_stay` — with the line ids; the blind spots (the record's first weeks, proposals that do not
  count, co-presence as a guess) are printed with the rows and carried under `blind_spots`. `logbook lab chapters
  [--min-trip-nights N] [--min-gap-days N] [--min-home-nights N] [--json]`: the record cut into chapters by
  home-region changes (a home entry in `places.json` may now carry `since` and `until`; without dates the nights
  decide), runs of days with no location line, and trips of 21 nights or more, printed as a table of contents with
  dates, nights, the top places and the top people per chapter. Synthetic fixtures only; nobody in them exists.
