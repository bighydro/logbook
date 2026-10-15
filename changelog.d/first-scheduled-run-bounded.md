### Fixed
- A source's first scheduled run reads its last 14 days, not its whole history. A live source added
  to the schedule started from nothing, so the first `sync --scheduled` walked everything it held (a
  Drive activity walk of 1.25 million entries spent the account's API quota for the day). Now a source
  with no watermark yet reads the record's last 14 local days on its first scheduled run, keeps its
  watermark, and says so in one line with the `logbook sync <source> --since <date>` that reads the
  rest. The next scheduled runs carry on from the watermark, or from the same instant while there is
  none, so nothing is skipped or written twice. `sync <source>` and `sync --all` by hand start where
  they always did, and `--since` always wins. `doctor` notes `first run bounded to 14 days; history
  not read` on the source's `sync:` line until a run reads back past it (`--since`, `--restart`)
  ([the schedule](docs/schedule.md#a-sources-first-scheduled-run)). `ais`, `adsb`, `telegram` and
  `weather` read no history and are never bounded.
- A dry run stops on one line at the source's quota or rate limit instead of waiting it out:
  `sync: drive: dry run stopped at the source's limit after 0 lines: HTTP 429: …`, exit 1, nothing
  written. The Google sources, `notion`, `github`, `granola` and `adsb` say so; a run that writes
  waits the limit out as before.
- `sync mail --since` on a folder with no mark yet and no message from that day on marks the folder
  at its last message, so the next run no longer reads the whole folder; `sync github --since` marks
  a repo with nothing from then on at that time, so the next run no longer reads it from its
  beginning; a first `sync gmail --since` that finds nothing keeps its time as the newest date, so a
  later list by date (after Gmail drops the history id) starts there, not at the first message.
