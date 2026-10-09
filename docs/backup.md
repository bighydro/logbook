# Backup

`logbook backup DEST` copies the record to another disk, verifies the copy there, and prints its head,
which is the head of the live record or the command fails. Every snapshot is a complete record of its
own that `logbook verify` accepts and `logbook backup restore` brings back; a file that did not change
since the last snapshot is a hard link to it, so the second snapshot and every one after costs only the
bytes that changed.

```bash
logbook backup /Volumes/Backup/Logbook                 # one snapshot, verified
logbook backup /Volumes/Backup/Logbook --keep 14       # then prune to the newest fourteen
logbook backup /Volumes/Backup/Logbook --verify        # also hash every attachment against its name
logbook backup list /Volumes/Backup/Logbook            # what is there, with lines, head and size
logbook backup restore /Volumes/Backup/Logbook/<owner_id>/2026-06-02T071500Z ~/Records/Logbook
```

```
backup: 2026-06-03T071500Z → /Volumes/Backup/Logbook/019cadd3-6bc0-7dcd-9133-000000000010/2026-06-03T071500Z
  214 files, 1.2 GiB: 3 copied (4.1 MiB), 211 linked to 2026-06-02T071500Z
  valid — 12,772 lines, head 53d39fda0b2c9e1f…
  kept 14 snapshots; pruned 2026-05-20T071500Z
```

## What a snapshot holds

`DEST/<owner_id>/<timestamp>/`, the record's files at their own paths and nothing else:

| In the snapshot | Left out |
|---|---|
| `logbook.json` | `index.sqlite` — a derived locator; the next reader rebuilds it (ADR 0007) |
| `logbook/<YYYY>/<MM>.jsonl`, the record | `inbox/` — copies of exports, not the record |
| `policy/` — crossing ceilings, disabled sources, the owner's aliases | `state/` — sync watermarks, bookkeeping; a restored record syncs again from the start and appends nothing twice |
| `places.json`, `assets.json` | `export/`, `logbook-0.1/`, anything else |
| `attachments/` — content-addressed, write-once | a file whose name begins with `.` (an attachment still being written) |
| `notes/` | |

The timestamp is UTC, `2026-06-02T071500Z`, so snapshots sort by name on any filesystem (no colon; Windows
refuses one). Two snapshots in the same second get `-2`, `-3`. `<owner_id>` is the record's, from
`logbook.json`, so one backup disk can hold several records without the snapshots mixing, and `--keep`
only ever counts one owner's.

## Hard links

The second snapshot links against the first: a file whose size and modification time are those of the same
path in the previous snapshot becomes a hard link to it, the way `rsync --link-dest` does it, and only a
file that changed is copied. A month file grows as the month goes on and is copied until the month closes;
`logbook.json` changes with every line; an attachment never changes, so the store, which is where the
gigabytes are, is copied once. Every snapshot is still a whole record: a hard link is the same bytes under
two names, each name as good as the other, so pruning one snapshot never touches another, and `restore`
copies, never links, so the restored record is independent of the backup disk.

A filesystem that refuses the link (exFAT, a network share, a snapshot on another volume) gets a copy, and
the command says how many files were linked and how many copied. The copy is pure Python and streams: a
file is read a chunk at a time, never whole, and nothing is shelled out to.

## Verified, every time

The copy is written under `.<timestamp>.partial`, then `logbook verify` runs on it, by the files alone, and
its head must be the head `logbook.json` named when the copy began. Only then is the directory renamed to
`<timestamp>`. A copy that does not verify, or whose head is not the live head, is removed and the command
exits 1 saying why; `backup list` never shows a dotted directory. So a crash leaves at most a `.partial`
directory you can delete, and a directory that looks like a snapshot is one that verified.

A line appended while the copy ran makes the month files run ahead of the copied `logbook.json`
(SPEC §3, write order); that copy does not verify and the command says `the record changed while it was
copied; run the backup again`. A scheduled backup at a quiet hour never meets this.

`--verify` also hashes every file in the copy's `attachments/` against its name (SPEC §1.1: a file whose
bytes do not match its name is an error). It reads every attachment, so it costs what the store weighs;
without it the chain is verified and the attachments are copied as they are. The chain covers lines, not
bytes, so a corrupt attachment on the live disk is caught only by `--verify`, and then before the snapshot
is kept: run it now and then, and always before trusting a disk you are about to retire.

## Where a backup may go

The destination is refused, before anything is written, when it is inside the record (a backup goes to
another disk) or under a folder a sync client owns, by the same detection `logbook doctor` uses for the
record itself: iCloud Drive, Dropbox, OneDrive, Google Drive, by any part of the path, its resolved path, or
the `OneDrive` variable Windows sets. A sync client keeps the backup on someone else's server and may evict
it; back up to a plain local disk or a drive you plug in. A folder that is a file is refused too.

## Restore

`logbook backup restore SNAPSHOT TARGET` copies the snapshot — never links — to a folder that does not
exist yet or is empty, verifies the result and prints its head. It never writes over anything, the record
included: to replace a damaged record, move it aside first. A target under a sync client's folder is refused
as above, and a code checkout is never empty, so that rule covers it. The restored record has no
`index.sqlite`; the next reader builds it, or run `logbook index`. Point `LOGBOOK_HOME` at it.

A snapshot is an ordinary record: `logbook verify --root SNAPSHOT` checks it where it lies, and
`LOGBOOK_HOME=SNAPSHOT logbook day 2026-06-02` reads one day from the backup disk without restoring
anything (the reader builds its locator in your cache directory, keyed by the record's `owner_id`; nothing is
written into the snapshot). Never append to a snapshot; the next backup links against its files.

## `backup list`

```
019cadd3-6bc0-7dcd-9133-000000000010
  2026-06-01T071500Z  12,760 lines  head 9a0e4c31d2b7…  1.2 GiB (1.2 GiB new)
  2026-06-02T071500Z  12,768 lines  head 7c15e0aa94d3…  1.2 GiB (3.9 MiB new)
  2026-06-03T071500Z  12,772 lines  head 53d39fda0b2c…  1.2 GiB (4.1 MiB new)
```

One owner per block, snapshots oldest first, each with the lines and head its `logbook.json` claims (what
was verified when it was written; `list` reads the file, it does not verify again), the size of the whole
snapshot, and in parentheses how many of those bytes are its own — not shared, by a hard link, with an
earlier snapshot in the list. The last number is what deleting the snapshot would free. A directory whose
`logbook.json` cannot be read is listed as not readable, with the reason, and the listing goes on. `list`
needs no record and can run on the backup disk from any machine.

## A schedule

`logbook backup` is a one-shot command, so the machine's own scheduler runs it the way `logbook sync
--install-schedule` runs `sync --all` (README, "Two ways in"). Once a day at 03:00, after the evening sync,
keeping two weeks:

**macOS, launchd.** `~/Library/LaunchAgents/org.logbook.backup.plist`, with the Python that has `logbook`
installed (`which logbook` tells you the path to put in place of `/usr/local/bin/logbook`):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>org.logbook.backup</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/logbook</string>
    <string>backup</string>
    <string>/Volumes/Backup/Logbook</string>
    <string>--keep</string><string>14</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict><key>LOGBOOK_HOME</key><string>/Users/ines/Records/Logbook</string></dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>3</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/Users/ines/Library/Logs/logbook-backup.log</string>
  <key>StandardErrorPath</key><string>/Users/ines/Library/Logs/logbook-backup.log</string>
</dict>
</plist>
```

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/org.logbook.backup.plist
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/org.logbook.backup.plist   # to remove it
```

A drive that is not mounted at 03:00 makes `/Volumes/Backup` a plain folder on the system disk, and the
backup lands there: give the agent a path only the mounted drive provides, or a `.plist` whose
`ProgramArguments` runs `/bin/sh -c 'test -d /Volumes/Backup/Logbook && exec logbook backup …'`.

**Linux, a systemd user timer.** `~/.config/systemd/user/logbook-backup.service` and `.timer`:

```ini
# logbook-backup.service
[Unit]
Description=logbook backup: one verified snapshot, keep fourteen
# the backup disk is a mount: nothing runs when it is not there
ConditionPathIsMountPoint=/mnt/backup

[Service]
Type=oneshot
Environment=LOGBOOK_HOME=%h/Records/Logbook
ExecStart=/usr/local/bin/logbook backup /mnt/backup/Logbook --keep 14
```

```ini
# logbook-backup.timer
[Unit]
Description=logbook backup at 03:00 local

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
Unit=logbook-backup.service

[Install]
WantedBy=timers.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now logbook-backup.timer
systemctl --user list-timers logbook-backup.timer      # the next run
journalctl --user -u logbook-backup.service -n 20      # the last run's output
systemctl --user disable --now logbook-backup.timer    # to remove it
```

`Persistent=true` runs a missed night the next time the machine is up; `ConditionPathIsMountPoint` skips a
night the disk is not plugged in rather than writing to the mount point's empty folder. Either scheduler
prints the same four lines the command prints by hand, to the log file or the journal, and a backup that
did not verify is an exit status 1 there and no new directory under `DEST`.

## What it does not do

It does not encrypt: a snapshot is the record as it is, plain, and the disk it is on needs the protection
the record's own disk has (FileVault, LUKS, a drive in a drawer). It does not go to a server, a bucket or a
sync folder, and refuses the last. It does not keep `state/`, so a restored record's next `sync` reads each
live source from its start; `append_many` skips what is already in the log, so nothing doubles. And it does
not replace `logbook verify` on the live record: a backup of a broken record is refused, not repaired, and
the command says to run `logbook verify` ([When verify fails](recovery.md) says what each failure means).
