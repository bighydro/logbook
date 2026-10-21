### Added
- The timeline: `/timeline` in the Library and `logbook show timeline [--day | --week | --month | --year |
  --life] [--json]`, the record's moments beside the map at five zooms. A moment is a stay of note with
  its place, time, the people confirmed apart from the proposed (each with its reason), its photos, what
  passed during it and, at tier 3 only, what was paid; the month and the year count the nights by class,
  and all years lists each place and vessel with who was there, by name only ([the timeline](docs/timeline.md),
  RFC 0043 §11-12).
- `logbook setup places class NAME CLASS`: a place's class (`home`, `family`, `aboard`, `away`), the colour
  of its nights on the timeline, kept in `places.json` under a key only the timeline reads.
