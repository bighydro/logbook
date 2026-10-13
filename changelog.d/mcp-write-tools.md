### Added
- `logbook serve mcp` gains two write tools that the owner allows by name (ADR 0022): `sign_day` signs a day as
  `logbook day sign` does, through the same code, the same checks and supersession, writing the same line byte
  for byte; `note_day` appends one `note/v1` line to a day, tier 2, source `mcp`, at most 4000 characters, its
  `kind` (`note`, `proposal`, `reflection`) in `labels`. Both are refused unless the `mcp` entry of
  `policy/crossing.json` names them under `"write": ["sign_day", "note_day"]`; an expired entry allows none, a
  day outside `write_window_days` (default 60) is refused, and `--allow-tier-3` has no effect on them. Both hold
  the writer lock without waiting and log the tool, the day and counts, never text. `logbook doctor` shows the
  write tools on its crossing line, and `serve mcp --inspect` lists them. RFC 0034 amendment 3.

### Changed
- `logbook day sign` reads the page and appends under one hold of the writer lock and re-reads the head before
  it appends, refusing when another writer moved it.
