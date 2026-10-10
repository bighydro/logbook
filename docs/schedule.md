# The schedule

`logbook sync --install-schedule` makes the machine run `logbook sync --scheduled` at 07:00 and 19:00
local: a launchd agent on macOS (`~/Library/LaunchAgents/org.logbook.sync.plist`), a systemd user timer
on Linux (`~/.config/systemd/user/logbook-sync.timer`). The plist or unit is printed before it is
written, nothing is written outside that directory, and `--uninstall-schedule` removes it again. The
agent runs the Python that installed it and points at the record found at install time; the keys your
sources need it reads from `~/.config/logbook/sync.env` (`KEY=value` lines, mode 600), which you write
and the command never does.

```bash
logbook sync --install-schedule                   # 07:00 and 19:00 local, by launchd or systemd
logbook sync --scheduled                          # what the schedule runs, by hand
logbook doctor                                    # the last-run and restore-test lines
logbook sync --uninstall-schedule
```

## What the scheduled run does

`sync --scheduled` is `sync --all` followed by `doctor`, and nothing you could not run by hand:

1. **`sync --all`**: every configured live source in turn, each from its own watermark, a failure in one
   never stopping the next, printed exactly as `sync --all` prints it ([the tour](tour.md#keep-it-flowing)).
2. **The restore test**, on the first Sunday of the month, once that day: the latest snapshot of the last
   backup is restored into a temporary folder, verified there, compared with what the record said when
   the backup was taken, and deleted again ([the monthly restore test](backup.md#the-monthly-restore-test)).
   A record that seals tiers 2 and 3 needs its identity to open them: put
   `LOGBOOK_IDENTITY_FILE=<path>` in `sync.env` or the test is skipped, and `doctor` says how to enable it.
3. **`doctor`**: every check, printed as by hand.

The outcome goes to `state/last-run.json`, bookkeeping beside the sync watermarks, never in the chain
and never in a backup:

```json
{
  "at": "2026-10-08T17:00:12Z",
  "sources": {"immich": {"result": "ok", "lines": 12}, "gcal": {"result": "failed (status 1)", "lines": 0}},
  "doctor": {"pass": 12, "warn": 1, "fail": 0, "warned": ["sync:gcal"], "failed": []},
  "first_failing": "gcal  failed (status 1)",
  "clean": false,
  "week": [{"at": "2026-10-08T17:00:12Z", "clean": false, "lines": {"immich": 12}}],
  "weekly_sent": "2026-10-04"
}
```

`at` is when the run began. `sources` has one entry per source `sync --all` listed, with the lines it
appended. `doctor` is the counts and the names of the checks that warned or failed. `first_failing` is
the first line that was wrong, as the run printed it: a source's summary line, else the first doctor
line that is not a pass. `clean` is no source failed and the doctor had nothing to say. `week` is one
short entry per run of the last seven days, for the Sunday message. The file is written twice: once
after the sync, so the doctor's own `last-run` line reads this run, and once at the end.

The exit status is 1 when a source failed or a check failed, as `sync --all` and `doctor` would exit.
The run never prompts: a source that needs a value it does not have is skipped and said so, a sealed
record without its identity skips the restore test, and the scheduler's log holds the output
(`~/Library/Logs/logbook-sync.log` on macOS, `journalctl --user -u logbook-sync.service` on Linux).

## What `doctor` says about it

Two lines, in every `logbook doctor`, wherever it runs:

```
pass  last-run      2026-10-08 19:00 (2 h ago): immich 12, gcal 3 lines; doctor 14 pass, 0 warn, 0 fail
pass  restore-test  passed 2026-10-04 (2026-10-04T030000Z, 12,772 lines)
```

- `last-run` is a **warn** when the last scheduled run is older than 26 hours (the schedule is twice a
  day, so a day and a little means a run was missed: the machine was off, or the agent is gone), or when
  it failed (a source failed, or a check failed), with the first failing line. No scheduled run yet is a
  pass on a machine with no schedule, saying how to install one, and a warn where one is installed and
  has not run.
- `restore-test` is a **pass** when a restore test passed within 35 days (the first Sundays of two
  months are at most five weeks apart), a **warn** when there has been none, the last is older, or it
  was skipped, each saying what to do, and a **fail** when the last test failed, with the reason.

## What it tells you, and when

The scheduled run can send one Telegram message. It is off unless both variables are set, in
`~/.config/logbook/sync.env` beside the sources' keys:

```
LOGBOOK_NOTIFY_TELEGRAM_TOKEN=<the bot's token, from BotFather>
LOGBOOK_NOTIFY_TELEGRAM_CHAT=<your chat id with the bot>
```

Without them nothing is sent and nothing is said about it. With them, the run sends **one message, and
only when**:

- **something is wrong**: a source failed, or `doctor` warned or failed; or
- **it is Sunday evening** (the 19:00 run, or any run on a Sunday at or after 12:00 local in the
  record's timezone), once a week, with the week's counts.

Nothing is sent when nothing is wrong and it is not Sunday evening. The format is fixed. The first block
is the alert, the second the week; both in one message when both apply:

```
logbook 2026-10-08 19:00: something is wrong
sync: 5 sources: 3 ok, 1 failed (gcal), 1 skipped
doctor: 12 pass, 1 warn, 1 fail; fail: record; warn: sync:gcal

logbook week to 2026-10-11: 14 runs, 13 clean
lines: immich 1,204, gcal 31; 1,235 in all
doctor: 13 pass, 1 warn, 0 fail
restore test: passed 2026-10-04
```

A message carries counts, source names and check names, and nothing else: never a line's content,
never a name from the record, never a check's detail (the detail is in `state/last-run.json` and in
`logbook doctor`, on the machine). The token is never printed, not in the log either. A standing warn
(an extra not installed, a source whose key is missing) is a message every run until it is fixed at its
source: disable the source in `policy/import.json`, install the extra, or set the key. That nagging is
the point: the earlier set-up had weekly dumps and monitors that spoke up when something broke, and the
record has had the pieces without anything running them or saying so.

**Who authorised the call.** No `logbook` command talks to a third party unless you ask it to by name
(CLAUDE.md: never a network call on an adapter's default path). Installing the schedule is that ask:
`sync --install-schedule`, run by you, is the explicit command that authorises the scheduled run's one
request to the Telegram Bot API when the variables are set. `sync --all` by hand sends nothing, `doctor`
sends nothing, and `--uninstall-schedule` ends it. A test points the request at a local server through
`LOGBOOK_NOTIFY_TELEGRAM_API`; you never need to set it.

A message the API refuses, or an endpoint that cannot be reached, is one line on stderr
(`notify: telegram: …`) and never changes the run's exit status or what was written: the outcome is on
disk before the message goes.
