### Fixed
- One writer at a time (#234): `append` and `append_many`, and `add`, `sync` and `import backup` for
  the whole of their run, hold `state/writer.lock` in the record folder, so a `sync`'s walk is inside
  it. A second writer prints `another logbook command is writing to this record (<command>, since
  <time>); waiting` and waits, or with the global `--no-wait` refuses with exit 2; a lock whose
  process is gone is taken over with one line saying so; a reader never takes it. The guard behind
  the courtesy: before every batch is written, `append_many` reads `logbook.json` again and refuses
  (`HeadMoved`, one sentence, exit 2, nothing written) when the head moved since the batch was
  computed, so a batch chained from a stale head can never reach the files. A long `sync` whose
  head another command had moved past used to lose its batch with `sqlite3.IntegrityError: UNIQUE
  constraint failed: lines.seq` from the index, after the month files had taken it.
