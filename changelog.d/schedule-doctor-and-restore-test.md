### Added
- The schedule runs `doctor` and says when something is wrong (docs/schedule.md). `sync --scheduled` is
  what `sync --install-schedule` now installs: `sync --all`, the restore test on the first Sunday of the
  month, then `doctor`, the outcome in `state/last-run.json` (when, the lines per source, the doctor's
  counts and the names of the checks that warned or failed, the first failing line). `doctor` gains a
  `last-run` line (a warn when the last scheduled run is older than 26 hours or failed) and a
  `restore-test` line (a pass when a restore test passed within 35 days, a warn otherwise saying what to
  do, a fail when the last test failed). With `LOGBOOK_NOTIFY_TELEGRAM_TOKEN` and
  `LOGBOOK_NOTIFY_TELEGRAM_CHAT` in `~/.config/logbook/sync.env`, the scheduled run sends one Telegram
  message only when a source failed or `doctor` warned or failed, and once a week on Sunday evening with
  the week's counts; counts, source names and check names only, never content; without the variables
  nothing is sent and nothing is said.
- `backup --restore-test [DEST] [--to DIR]`: the latest snapshot of the last backup restored into a
  temporary folder, verified there (every sealed line opened, when the record seals), compared with
  what the record said when the backup was taken (`state/last-backup.json`, which `backup DEST` now
  writes) and with the live chain, deleted again, and the outcome in `state/last-restore-test.json`.
  Skipped, with the line that enables it, when no backup is recorded or a sealed record's identity is
  not in the agent's environment; never a prompt.
