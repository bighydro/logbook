# Screen Time: which app, from when to when

`logbook add screentime` writes one `app-use` line per stretch an app was in use, from the stores
Apple keeps for Screen Time: a Mac's `knowledgeC.db` (sessions) and an iPhone backup's
`RMAdminStore-Local.sqlite` (hourly totals). `logbook rollup attention` then reads the year back as
hours by app and by category. No window title, no URL and no web domain ever reaches a line: the
record says *Safari, 25 minutes, on the Mac*, never what was read in it.

```bash
logbook add screentime --mac                       # this Mac's own store (Full Disk Access, below)
logbook add screentime --mac ~/copies/knowledgeC.db   # a copy, or another Mac's store
logbook add screentime --backup ~/Library/Application\ Support/MobileSync/Backup/<udid>   # the phone's store, copied out of the backup
logbook add screentime --mac --dry-run             # count against the record; write nothing
logbook add screentime <knowledgeC.db | RMAdminStore-Local.sqlite>   # either store by path; `logbook add <path>` sniffs them too
logbook import-backup <backup> --only screentime   # the same phone store, as one source of the backup
logbook rollup attention --year 2026               # hours by app and by category, the year as one period
logbook rollup attention --year 2026 --by month    # … per calendar month; --by week for ISO weeks
```

## Full Disk Access, on the Mac

The Mac keeps its knowledge store at `~/Library/Application Support/Knowledge/knowledgeC.db` (the
system's is at `/private/var/db/CoreDuet/Knowledge/knowledgeC.db`). macOS protects both: a terminal
that has not been granted **Full Disk Access** cannot open them, whatever the file's permissions
say. Grant it once — *System Settings → Privacy & Security → Full Disk Access*, add Terminal (or
the terminal you run `logbook` from) — then run the command again. Without it `add screentime --mac`
stops with one line that names the setting; it never asks for a password and never tries another
way in. A copy of the store made by a process that has the access (`cp` from such a terminal) can
be read from anywhere with `--mac <copy>`.

The store is opened read-only and immutable: nothing is written to it, not even a journal beside it.

## The line

Kind `app-use`, tier 2 (what you did with your time; `--tier` overrides for a whole run), source
`screentime`, `at` the start and `end` the end of the span in UTC, `tz` the record's zone. The
payload is `event/v1` (RFC 0009's shape): `title` the app's name when known, else its bundle id;
`calendar` `{"id": "screen-time", "name": "Screen Time"}`; `all_day` false; the app under `extra`:

| `extra` | What it holds |
|---|---|
| `bundle_id` | the app's bundle identifier, as the store names it (`com.apple.Safari`) |
| `app` | the app's name, when the built-in table (`logbook/apps.py`) or the phone's own app table names it; absent otherwise, and the line is counted "without an app name" |
| `device` | `mac` for this Mac's own sessions; a device identifier for a session another device synced into the Mac's store, and for the phone's store; `iphone` when the phone's store has no device table |
| `device_name` | the phone's name for itself (`iPhone`), when the store has it |
| `duration_s` | the span's length in seconds |
| `observed` | `session` (the Mac: one row of the `/app/usage` stream) or `hourly_total` (the phone: one app's total for one hour, laid from the top of the hour) |
| `stream` | the Mac: `/app/usage`, the one stream read |
| `block_s` | the phone: the block's length, 3600 |
| `apple_category` | the phone: Screen Time's own category for the app (`Social`, `Productivity & Finance`) |

`raw_id` is `<device>:<bundle id>:<start>`: one line per app per start per device, so running the
command again appends nothing (ADR 0017), and the same session written twice in a store (a re-sync)
is one line, counted "already seen".

A synthetic example, the Oslo persona's Mac:

```json
{"at":"2026-06-08T07:00:00Z","end":"2026-06-08T07:25:00Z","tz":"Europe/Oslo","source":"screentime","kind":"app-use","tier":2,
 "payload":{"schema":"event/v1","raw_id":"mac:com.apple.Safari:2026-06-08T07:00:00Z","title":"Safari",
 "calendar":{"id":"screen-time","name":"Screen Time"},"all_day":false,
 "extra":{"bundle_id":"com.apple.Safari","app":"Safari","device":"mac","duration_s":1500,"observed":"session","stream":"/app/usage"}}}
```

`logbook show` prints such a line as an `app-use` row from `screentime`: `Safari · 25 min · mac`.

## The Mac's store: sessions

`knowledgeC.db` is CoreDuet's knowledge store, a Core Data SQLite file. The adapter reads one
table, `ZOBJECT`, and one stream of it, `/app/usage`: a row per session with the bundle id
(`ZVALUESTRING`), the start and the end (`ZSTARTDATE`, `ZENDDATE`, seconds since 2001-01-01 UTC),
and the source row (`ZSOURCE`), whose `ZDEVICEID` is empty for this Mac and names the device for a
row another of your devices synced in. The other streams are never queried. `/app/activity` carries
window titles and content URLs under `ZSTRUCTUREDMETADATA`; `/app/inFocus` says which app had the
focus; neither becomes a line, and a test holds the adapter to it on a store whose activity row
carries a title and a URL.

A session with nothing in it (an end at or before its start), a row with no start and a row with no
bundle id are skipped and counted. A session another device synced into the Mac's store keeps that
device's identifier, so it is a different line from the Mac's own; if you also import that device's
own store, the two will both be in the record, the synced copy as sessions and the phone's as hourly
totals, and `rollup attention` counts both — import one or the other.

## The phone's store: hourly totals

An iPhone does not back up `knowledgeC.db`. It backs up Screen Time's own store, HomeDomain
`Library/Application Support/com.apple.remotemanagementd/RMAdminStore-Local.sqlite`, which keeps
**hourly blocks** (`ZUSAGEBLOCK`, each starting on the hour), a category per block
(`ZUSAGECATEGORY`, Apple's own names) and under each the apps timed in that hour
(`ZUSAGETIMEDITEM`: the bundle id and the seconds). There are no sessions to read; each app's hour
is one line laid from the top of the hour for its seconds, marked `observed: hourly_total`, so the
hours add up and nobody reads the span as a sitting. The phone names itself through `ZUSAGE →
ZCOREDEVICE` (`device`, `device_name`) and, when the store has `ZINSTALLEDAPP`, names its apps too.

`ZUSAGETIMEDITEM` also carries Safari's time **per web domain** (`ZDOMAIN`, no bundle id). Those rows
are skipped and counted "per-site web time (the domain is never kept)": the Safari total is there as
Safari's own row, the sites are not. `ZUSAGECOUNTEDITEM` (notifications and pickups) is not read.

`add screentime --backup DIR` finds the store through the backup's `Manifest.db`, copies it with its
`-wal`/`-shm` into `inbox/ios-backup-<udid>/screentime/`, records the copy in `copies.json` and runs
the adapter on the copy, exactly as `import-backup --only screentime` does; the backup itself is
only read. An encrypted backup is unlocked with `LOGBOOK_BACKUP_PASSWORD`, as `import-backup` does.
A backup with no store is said so, and the command exits 1.

## Schema drift

Every table's columns are confirmed with `PRAGMA table_info` before a read. A column the adapter
does not need may be missing or renamed and the rows still read: a knowledge store without `ZSOURCE`
reads with every session local; a phone store without `ZCOREDEVICE` reads as one `iphone`; without
`ZINSTALLEDAPP`, the built-in table names what it can. A table or a column the adapter needs that is
not there is one error naming the store (`knowledgeC.db is neither …`, `RMAdminStore-Local.sqlite:
ZUSAGETIMEDITEM has no …`), never a traceback. `sniff` takes a SQLite file with `ZOBJECT` and its
stream column, or with the three usage tables, and nothing else.

## Hours by app and by category: `rollup attention`

`logbook rollup attention [--year YYYY | --since YYYY-MM-DD --until YYYY-MM-DD] [--by month|week] [--json]`
sums the `app-use` lines standing (a retracted line is out; so is one another app-use line
`supersedes`) per calendar year — or per calendar month or ISO week with `--by` — as hours by app
and by five categories: **communication**, **browser**, **media**, **work**, **other**.

```
attention 2026-06-08 – 2026-08-20 · by year
  2026  7.2 h · communication 0.7 h · browser 2.5 h · media 0.8 h · work 3.0 h · other 0.2 h
        Xcode                    3.0 h · work · 2 sessions · com.apple.dt.Xcode
        Safari                   2.0 h · browser · 2 sessions · com.apple.Safari
        Music                    0.8 h · media · 1 session · com.apple.Music
        Messages                 0.7 h · communication · 2 sessions · com.apple.MobileSMS
        Safari                   0.5 h · browser · 1 session · com.apple.mobilesafari
        org.example.puzzle       0.2 h · other · 1 session · org.example.puzzle
```

An app is its bundle id, so the Mac's Safari and the phone's are two rows, the same name on both.
Under `--json` each app carries `bundle_id`, `app` (null when nothing names it), `category`,
`hours`, `seconds`, `sessions`, `devices` (seconds per device) and `lines` (the ids of the lines
summed); each period `hours`, `seconds` and `by_category` (every category, a category with no app
at zero), and `null` with no apps for a period the window touches with no line at all — in text an
em dash, never a zero per category. The window is clipped to the first and last day with an
`app-use` line, read through the index alone: no reading of the track. The text lists the top
twenty apps of a period and counts the rest. Nothing is written.

### Naming and sorting the apps: `policy/apps.json`

A small built-in table (`logbook/apps.py`, `BUILT_IN`) names and sorts the common apps under both
their Mac and their iOS bundle ids: Messages, Mail, WhatsApp, Slack, Teams and Zoom under
communication; Safari, Chrome, Firefox, Arc under browser; Music, TV, Podcasts, Photos, Spotify,
YouTube, Netflix, Instagram under media; Xcode, Terminal, VS Code, Pages, Notes, Calendar, Notion
under work. An app the table does not know is sorted by a word in its bundle id (`mail`, `chat`,
`music`, `game`, `code`, …) and otherwise `other`, under its bundle id when the store did not name it.

Your own table lives in the record, `policy/apps.json`, and wins over the built-in one:

```json
{
  "com.apple.dt.Xcode": "other",
  "org.example.puzzle": {"name": "Puzzle", "category": "media"}
}
```

A bare string is a category; an object gives a name, a category or both. The categories are the
five above; anything else, or a file of another shape, stops the rollup naming the file. Nothing
writes the file — it is yours — and a record without it reads with the built-in table alone. The
names and categories are applied when the rollup reads, never written into a line, so renaming an
app re-sorts every year without a new line.

## What never enters the record

Window titles, document names, URLs and web domains: the adapter reads the one stream and the one
item kind that carry none of them, and the per-domain rows of the phone's store are skipped with
the domain unread. Notification and pickup counts are not read. Nothing is sent anywhere; the
adapter opens no network connection.
