### Added
- The Library's Life door, `/life` (RFC 0047 §4.2), which the header's Life door now opens: the chapter you
  are in and its rules, the year's goals and those for life with their last review, then one timeline of
  your life at five zooms (Life, Year, Month, Week, Day) or one trip, your ideas as a band on it, the
  chapters not yet placed, and the Volumes, the years as spines. Every zoom and move is a link
  (`/life?at=2026-06-15&zoom=week`, `/life?trip=FIRST/LAST`), no script, no number beside a name, held to
  the page's tier. Its bounds are `life` in `logbook.json`, `{"from", "to"}`, else the record's first day
  to the end of next year ([settings](docs/settings.md#your-life-life)). Every old address works as it did.
