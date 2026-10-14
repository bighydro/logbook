### Fixed
- A crash between the fsync of an appended line and the replacement of `logbook.json` (SPEC §3, write
  order) left the files one line ahead, which `verify` reported; the recovery this documented, `repair
  index` then append, then wrote a second line of the same seq, the index refused it with `UNIQUE
  constraint failed: lines.seq`, and the record held a fork. `append` and `append_many` now refuse under
  the writer lock while the files end past `logbook.json`, or at its seq under another head, in one
  sentence naming `logbook repair tail`, and write nothing. `repair tail` checks every line past the head
  as `verify` does (envelope, seq, prev, hash, timestamps, a sealed line opened when the identity is here)
  and only then sets `logbook.json` to the last of them and extends the index, in that order; `--dry-run`
  lists the tail and what would be done; a line that does not verify, the files behind `logbook.json`, or
  the same seq under another head makes it refuse with the first failing line and change nothing. The
  gate of `key seal --all` and `repair migrate` checks timestamps too now, as `verify` reports them.
