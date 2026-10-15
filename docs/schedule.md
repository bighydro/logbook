# The schedule

`logbook sync --install-schedule` makes the machine run the record four times a day, at 00:00, 06:00,
12:00 and 18:00 local: `logbook sync --scheduled` at 00:00, 12:00 and 18:00, and `logbook sync
--scheduled --close` at 06:00, the run that closes the day (below). That is two jobs: two launchd agents
on macOS (`~/Library/LaunchAgents/org.logbook.sync.plist` and `org.logbook.sync.close.plist`), two
systemd user timers on Linux (`~/.config/systemd/user/logbook-sync.timer` and `logbook-sync-close.timer`,
each with its service). The plists or units are printed before they are written, nothing is written
outside that directory, and `--uninstall-schedule` removes them again, all four runs. The agents run the
Python that installed them and point at the record found at install time; the keys your sources need
they read from `~/.config/logbook/sync.env` (`KEY=value` lines, mode 600), which you write and the
command never does.

```bash
logbook sync --install-schedule                   # 00:00, 06:00, 12:00 and 18:00 local
logbook sync --install-schedule --system          # a machine nobody logs in to: prints two sudo commands
logbook sync --scheduled                          # what the schedule runs, by hand
logbook sync --scheduled --close                  # what it runs at 06:00
logbook doctor                                    # the last-run and restore-test lines
logbook sync --uninstall-schedule [--system]
```

A schedule installed before the four runs (one agent or timer at 07:00 and 19:00, under the same name)
moves to them when you run `logbook sync --install-schedule` again: the files are written over, the
agents loaded again, and a timer restarted so it takes the new times. `--uninstall-schedule` removes it
whichever it is.

## The four runs, and the 06:00 close

The day ends at your `day_start` (midnight unless you set one, [the record's settings](settings.md)). The
06:00 run is the one after it for most settings, so it closes the day: `sync --scheduled --close` is the
scheduled run below with one step more, in this order:

1. **the sync**: `sync --all`, as at every run;
2. **the dream's catch-up**: `dream --catch-up`, when this version of logbook has the dream command and
   `policy/crossing.json` has a `dream` entry (sending a day to a model is a crossing like any other):
   the drafts of the last 14 days that have none or whose lines changed, then the synthesis of each call
   of the last 7 days that has none ([the synthesis of a
   call](transcript-synthesis.md#the-week-the-close-covers)). When it has not, one line says why
   (`dream: this version has no dream command; nothing to catch up`, or `dream: policy/crossing.json has
   no dream entry; nothing to catch up`) and the run goes on: absence is not an error. The close passes
   nothing after `--catch-up`, never a `--since`, so an older call is never sent by the schedule however
   many the record holds: the catch-up counts them in one line (`3 calls before 2026-10-07 not
   synthesized; run …`), `doctor` on its `synthesis` line, and they wait for you to send them by hand. A
   draft is a proposal, so what the dream does never changes the run's exit status;
3. **the rest of the run**: the restore test on the first Sunday of the month, `doctor`, the outcome
   in `state/last-run.json`, the message when something is wrong;
4. **one summary line**: `scheduled run, the close (dream caught up): clean; state/last-run.json`, or
   `(no dream command)`, `(no dream entry)`, `(dream --catch-up exit 1)`.

The runs at 00:00, 12:00 and 18:00 never dream. If your day begins later than 06:00, the close still
runs at 06:00: the catch-up drafts the days that have ended, and the one that has not waits for the
next morning.

## On a machine nobody logs in to: `--system`

An agent runs while you are logged in. The record's home (ADR 0022) is often a machine nobody logs in to,
where an agent never loads. `--system` writes the schedule for the system domain instead, as `logbook
serve --install-service --system` does for the pages: two launchd daemons (`UserName` you, `HOME` your
home directory) or two pairs of system units (`User=` you, `EnvironmentFile=` your `sync.env` by its
path), with the same four times, written to your home directory, and the two `sudo` commands that copy
them into `/Library/LaunchDaemons` (or `/etc/systemd/system`) and start them printed, never run:

```
$ logbook sync --install-schedule --system
…
written: 2 files for the system domain, running as ines from boot: …; nothing runs until you install
them, as an administrator:
  sudo cp /Users/ines/org.logbook.sync.plist /Users/ines/org.logbook.sync.close.plist /Library/LaunchDaemons
  sudo launchctl bootstrap system /Library/LaunchDaemons/org.logbook.sync.plist /Library/LaunchDaemons/org.logbook.sync.close.plist
```

Installing again over copies already there prints the commands that stop and replace them; run as root,
it is refused (the jobs would run as root, with root's home). `--uninstall-schedule --system` removes the
copies in your home directory and prints the commands that stop the jobs and remove the system's.
Moving from the agents to the daemons, remove the agents (`--uninstall-schedule`): with both, every run
happens twice, and `doctor` says so.

## What the scheduled run does

`sync --scheduled` is `sync --all` followed by `doctor`, and nothing you could not run by hand (the 06:00
run adds the dream's catch-up after the sync, above):

1. **`sync --all`**: every configured live source in turn, each from its own watermark, a failure in one
   never stopping the next, printed exactly as `sync --all` prints it ([the tour](tour.md#keep-it-flowing)),
   except that a source with no watermark yet reads its last 14 days and not its whole history
   ([below](#a-sources-first-scheduled-run)).
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

## A source's first scheduled run

A live source you add to the schedule has no watermark yet, and a run that starts from nothing walks the
source's whole history: every activity Google keeps for a Drive, twenty years of a mailbox, a photo
library. That is a backfill, and a backfill is something you ask for, not something a timer does: one
first scheduled walk of 1.25 million Drive activities used up the account's API quota for the day. So
the scheduled run reads a new source's **last 14 days** and no more, and says so in one line:

```
drive: first scheduled run read from 2026-09-25; for the history run `logbook sync drive --since <date>`
```

- **Which run.** `sync --scheduled` (and `sync --scheduled --close`), the command the installed agents or
  timers run and that nothing else passes; typing it yourself is the same run. `logbook sync drive` and
  `logbook sync --all` by hand start where they always did: from the watermark, or from the beginning
  for a source that has none. `--since` always wins.
- **Which source.** One with nothing in `state/<name>.json`: no watermark, no marks of its own (`mail`
  and `gmail` keep theirs under `resume`), no walk under way. A source you synced by hand before carries
  on from where it is. A source whose record already holds lines (an export imported, which `sync`
  resumes from) starts from its newest line, less the source's lookback, when that line is inside the 14
  days, and from the 14 days when it is older. A record restored from a snapshot has no `state/`, so
  every source is new to it: each reads its last 14 days, and a `--since` from before the snapshot's day
  reads what lies between. `ais`, `adsb` and `telegram` have no history to read (a stream, the present,
  the day of updates a bot keeps) and are never bounded, and `weather` asks about yesterday alone on its
  first run whatever runs it.
- **The 14 days** are the record's local days, today included, from your `day_start` (midnight unless
  you set one), taken once per run from its own clock and the same for every source in it. They are
  counted in the source's own clock, as the watermark is: for a calendar, the events changed in those
  days; for Drive, the activity in them. The watermark after the run is what the run saw, as after any
  run, and the next scheduled run carries on from it.
- **The mark.** Before it pulls, the bounded run writes `"first_run": {"from": "2026-09-24T22:00:00Z",
  "day": "2026-09-25"}` in the source's state file, and a run from it that finishes adds `"complete":
  true`. A run that fails or is interrupted, or one that found nothing in the window and so left no
  watermark, is followed by runs from that same instant, never from a window that slid on: nothing
  after it is skipped, an interrupted walk (`immich`) resumes, and the record refuses what a failed run
  already wrote. `mail` and `gmail` carry on from their own marks once a run from it has finished.
- **The history** is yours to read when you want it: `logbook sync drive --since 2020-01-01T00:00:00Z`
  (an instant in UTC, as every `--since` but weather's, earlier than the day the line names: a day
  before it is always enough), or
  `--restart` for a source that walks a library (`immich`, `mail`, `gmail`). The record refuses the two
  weeks it already holds, the watermark never moves back, and the mark goes. Until then `doctor` says
  so on the source's own line —
  ``pass  sync:drive  configured (LOGBOOK_DRIVE_SA_KEY, LOGBOOK_DRIVE_USER); first run bounded to 14 days;
  history not read (before 2026-09-25: `logbook sync drive --since <date>`)`` — a note on a pass: nothing
  is broken, and a warn would send the message at every run for a history you may never want.

A dry run never waits out a source's quota or rate limit either: the first such answer (a 429, Google's
rate-limit and quota 403s, GitHub's hourly limit) ends it on one line, exit 1, nothing written —
`sync: drive: dry run stopped at the source's limit after 0 lines: HTTP 429: Quota exceeded for quota
metric 'Queries' and limit 'Queries per day' …`. A run that writes waits the limit out as it always
did.

## What `doctor` says about it

Two lines, in every `logbook doctor`, wherever it runs:

```
pass  last-run      2026-10-08 18:00 (2 h ago): immich 12, gcal 3 lines; doctor 14 pass, 0 warn, 0 fail
pass  restore-test  passed 2026-10-04 (2026-10-04T030000Z, 12,772 lines)
```

- `last-run` is a **warn** when the last scheduled run is older than 26 hours (the schedule runs four
  times a day, so a day and a little means the machine was off or the agents are gone), or when
  it failed (a source failed, or a check failed), with the first failing line. The run is the record's
  `state/last-run.json`, read the same whichever install wrote it: your agents or timers, the system's
  daemons or units (`--system`), or a schedule on another machine. No scheduled run yet is a pass on a
  machine with no schedule, saying how to install one, and a warn where one is installed and has not run.
  Both installed at once — the agents and the daemons, the user timers and the system's — is a warn
  whatever the run said, since every run then happens twice: keep one (`--uninstall-schedule`, or
  `--uninstall-schedule --system` for the system's).
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
- **it is Sunday evening** (the 18:00 run, or any run on a Sunday at or after 18:00 local in the
  record's timezone), once a week, with the week's counts.

Nothing is sent when nothing is wrong and it is not Sunday evening. The format is fixed. The first block
is the alert, the second the week; both in one message when both apply:

```
logbook 2026-10-08 18:00: something is wrong
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
(the project's rule: never a network call on a default path). Installing the schedule is that ask:
`sync --install-schedule`, run by you, is the explicit command that authorises the scheduled run's one
request to the Telegram Bot API when the variables are set. `sync --all` by hand sends nothing, `doctor`
sends nothing, and `--uninstall-schedule` ends it. A test points the request at a local server through
`LOGBOOK_NOTIFY_TELEGRAM_API`; you never need to set it.

A message the API refuses, or an endpoint that cannot be reached, is one line on stderr
(`notify: telegram: …`) and never changes the run's exit status or what was written: the outcome is on
disk before the message goes.
