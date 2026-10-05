### Fixed
- `show` orders a day by the instant of `at`, then `seq` (SPEC §3.2), never by the text of `at`: a line at `10:00:00.5Z`
  sorted before one at `10:00:00Z`. logbook-ts already ordered by the instant (#123).
