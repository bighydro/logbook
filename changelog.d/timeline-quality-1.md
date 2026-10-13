### Fixed
- `day` and `serve` show one calendar entry once when two calendars carry it (`ios-calendar` and
  `ics`, or two calendars `gcal` writes as `ics`): starts less than a minute apart, the same duration
  or one side all-day, the same title or flight. The richest line stands and names the others,
  `×2 sources (ics, ios-calendar)`; the fold is at read time, every line stays (docs/day.md).
- A move names an airport pair (`OSL → ZRH`) only when it is a flight: its speed and distance are a
  flight's, or a flight line covers it. A car move between two points near an airport no longer
  prints `ZRH → ZRH`.

### Added
- `doctor` warns on lines dated outside their source's plausible range (calendars 1970 to now plus
  5 years, mail 1990 to now plus 1 day, the rest 1970 to now plus 1 day), per source with the
  earliest and the latest; `doctor --implausible` lists the line ids; `policy/plausible.json`
  overrides a range per source. Nothing is deleted or hidden (docs/doctor.md).
