### Added
- `logbook lab hold census files PATH…`, `senders` and `drive`: Hold v0, read-only censuses of what
  you hold ([Hold](docs/hold.md), RFC 0042 draft). `files` walks the folders you name, never through a
  link and never into a system or Claude folder: counts and sizes by type and year, duplicates by
  SHA-256, the 50 largest, folders untouched for two years. `senders` reads the record's mail lines:
  senders by count and last seen, the ones never answered, newsletters when a line holds the
  List-Unsubscribe header. `drive` reads the record's Drive lines. Each writes a report under
  `state/hold/`; the names stay in it, the terminal gets counts, and nothing is moved, renamed,
  deleted or appended.
