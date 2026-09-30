# Logbook

**A diary that writes itself.**

Your life already gets recorded — by your phone, your photos, your calendar, your messages. Logbook writes it all down once, in one folder that only you hold, and reads it back to you as days. You hand a page to someone you care about; they hand one back.

It is the opposite of social media: no feed, no followers, no likes, no counts. Reveal, never reward. Nothing leaves without a name.

![How Logbook works](https://raw.githubusercontent.com/bighydro/logbook/main/docs/how-it-works.svg)

![Sixty seconds with Logbook](https://raw.githubusercontent.com/bighydro/logbook/main/docs/demo.gif)

## Sixty seconds

```bash
pipx install openlogbook        # or: pip install .
logbook init                    # creates ~/Logbook and your key
logbook add "had lunch with a friend by the lake"
logbook add ~/Downloads/takeout.zip     # any export, no flags
logbook show today
logbook stats                   # what the record holds: counts by kind, source and year
logbook derive stays --day 2026-09-30   # the day read back: stays, stops, moves, where you slept
logbook verify                  # the chain is intact
```

Docker: `docker build -t logbook . && docker run --rm -v ~/Logbook:/data logbook show today` — the image keeps the record in the `/data` volume (`LOGBOOK_HOME=/data`).

Nix: `nix run github:bighydro/logbook -- --version`, or `nix develop` in a clone for a shell with Python 3.12 and uv.

That is the whole product. Everything else is a layer somebody plugs in.

## Sixty seconds with an iPhone backup

Plug the iPhone into a Mac, select it in Finder and press *Back Up Now*. The backup lands in
`~/Library/Application Support/MobileSync/Backup/<udid>` (on Windows under
`%APPDATA%\Apple Computer\MobileSync\Backup\`). Then:

```bash
export LOGBOOK_DIAL_PREFIX=47                       # your country code, for numbers saved without one
logbook import-backup ~/Library/Application\ Support/MobileSync/Backup/<udid> --dry-run   # what is there, how big
logbook import-backup ~/Library/Application\ Support/MobileSync/Backup/<udid>
logbook import-backup <the same> --only contacts,whatsapp        # just some of it
```

One command reads the backup's `Manifest.db`, finds the six stores the adapters know — Contacts, WhatsApp's
contacts and chats, Messages, Calendar, Notes — copies each one with its `-wal`/`-shm` siblings and its media
folder into `inbox/ios-backup-<udid>/<source>/`, checks every copy against the stored blob, and runs the adapters on the copies:
contacts first, so the chats that follow already have their people. The backup itself is only ever read. Per
source it prints found or not found, the lines added and what was skipped, and it ends with `verify`.
Re-running it appends nothing already logged. `inbox/ios-backup-<udid>/copies.json` lists every copy. The
manifest's `Size` is what a file measured on the phone and can be stale against the stored blob; a copy that
matches the blob but not `Size` is one warning naming the file and both sizes, recorded in `copies.json`, never an error.

**An encrypted backup** (*Encrypt local backup* ticked in Finder) holds more than an unencrypted one: Health,
the call log and Safari's history are only ever backed up encrypted. `import-backup` reads one with the
`encrypted` extra and the password in one environment variable, never a flag:

```bash
pip install "openlogbook[encrypted]"        # or: uv tool install "openlogbook[encrypted]"
read -s LOGBOOK_BACKUP_PASSWORD && export LOGBOOK_BACKUP_PASSWORD   # typed once, never echoed
logbook import-backup ~/Library/Application\ Support/MobileSync/Backup/<udid>
```

The keybag in `Manifest.plist` is unlocked first, so a wrong password fails on one line before any file is
touched; then `Manifest.db` is decrypted into the inbox folder and every file is decrypted a chunk at a time
on its way to the same `inbox/ios-backup-<udid>/<source>/` layout, so the adapters run unchanged. The
password is never printed, never written anywhere, and never part of an error. `copies.json` records
`encrypted: true` and each file's protection class. The stores only an encrypted backup carries come along:
the call log (`ios-calls/CallHistory.storedata`) runs through its adapter like the others; Health
(`health/healthdb_secure.sqlite`, `healthdb.sqlite`) and Safari (`safari/History.db`) are copied out beside
them and reported as *copied, no adapter yet*; `--only calls,health` names them too. Without the extra
installed the command prints the `pip install` line and exits 2; without the variable it says which one to set.

## Where to keep the record

Never in a folder that iCloud Drive, Dropbox, Google Drive or OneDrive syncs. Those services evict files to the
cloud and fetch them back on demand, so reads stall on files that are not really there, and the record ends up
on someone else's server. Keep it in a plain local folder and point `LOGBOOK_HOME` at it:

```bash
logbook init ~/Records/Logbook           # once
export LOGBOOK_HOME=~/Records/Logbook    # in your shell profile, so every command finds it
```

Back it up with Time Machine or an equivalent that copies the folder as it is.

## Implementations

| Implementation | Language | Status |
|---|---|---|
| [openlogbook](https://github.com/bighydro/logbook) (this repo) | Python | reference |
| [logbook-ts](https://github.com/bighydro/logbook-ts) | TypeScript | independent |

Both reproduce the conformance head `53d39fda…088e6` from `conformance/sample-logbook` (`conformance/expected.json`). SPEC §6 requires two independent implementations to agree before v1.0 is frozen; that is now true for `verify` and `append`.

## Upgrading

0.3.0 changes how lines are hashed (format `logbook/0.2`, SPEC §3.1). A record written by 0.1.0 or 0.2.0 is refused until it is migrated. Back up first, then migrate once:

```bash
cp -a ~/Logbook ~/Logbook.bak    # or wherever LOGBOOK_HOME points
logbook migrate                  # same lines, new hashes; keeps the old files at logbook-0.1/
```

## What is in the folder

```
~/Logbook/
  logbook/          the record. one file per month. append only. never edit.
    2026/09.jsonl
  inbox/            drop anything here. it gets read, then moved to done/.
  notes/            what you write. plain Markdown, one file per day.
  logbook.json      who this is, your timezone, the chain head.
  policy/           crossing.json: the highest tier each circle member may receive. yours to edit.
                    stays.json: how long a stay is, how far a place reaches. yours to edit.
  assets.json       the boats, aircraft and cars whose tracks the record keeps (ADR 0018). yours to edit.
  places.json       optional: names for the places `derive stays` finds (lat, lon, radius_m).
  state/            where each live source left off. bookkeeping, not the record.
  exports/          crossing.json: where the last crossing to each member ended. bookkeeping.
```

Nothing here needs the app to make sense. Open the files in any editor twenty years from now.

If you also keep a clone of this repository, set `LOGBOOK_HOME` to your record's folder and pass that path to `logbook init`. On a case-insensitive disk (macOS by default) `~/Logbook` and a clone named `~/logbook` are the same folder; `init` refuses a folder that contains `pyproject.toml`, `.git` or `logbook/__init__.py`, and the CLI never picks such a folder as your record.

## Sources

Two ways in. `add` reads a file you already hold; `sync` asks a service you run for what is new.

```bash
logbook add ~/Downloads/dawarich-export.json      # any export the adapters recognise, or a folder
logbook add ~/Takeout/"Location History (Timeline)"/Records.json   # Google Takeout; Timeline.json works too
logbook add ~/Takeout/"Google Photos"                 # Google Takeout photos: one line per file, the pixels stay put
logbook add ~/backup/31bb7ba8914766d4ba40d6dfb6113c8b614be442   # iOS Contacts from an unencrypted Finder/iTunes backup
logbook add ~/backup/7c7fba66680ef796b916b067077cc246adacf01d   # WhatsApp (iOS) ChatStorage.sqlite from the same backup
logbook add ~/backup/4f98687d8ab0d6d1a371110e6b7300f6e465bef2   # Apple Notes NoteStore.sqlite from the same backup
logbook add ~/backup/2041457d5fe04d39d0ab481178355df6781e6858   # iOS Calendar.sqlitedb from the same backup
logbook add ios-calls ~/inbox/ios-backup-<udid>/ios-calls/CallHistory.storedata   # the call log, by adapter name
logbook import-backup ~/backup                    # all of the above from the backup folder, in one go
logbook add transcript ~/Meetings/tromso.md --source manual   # a transcript: JSON (transcript/v1), WebVTT, SRT, Markdown, text
logbook add ~/Zoom/GMT20260301-130000_Recording.transcript.vtt --source zoom   # VTT and SRT are recognised on sight
logbook sync granola                              # every Granola recording, and its summary as a derived note
logbook add flights ~/Downloads/flighty.csv       # a Flighty export: one flight/v1 line per flight, evidence tracked
logbook add flight "LX 561 NCE ZRH 2026-09-27 pilot"   # your own word: evidence declared
logbook infer flights                             # calendar entries + gaps in your location points: evidence inferred
logbook sync immich                               # everything since the last run; safe to repeat
logbook sync immich --since 2026-01-01T00:00:00Z  # or everything Immich received or changed since then
logbook sync immich --dry-run                     # count and summarise, write nothing
```

`sync` remembers where it got to in `state/<source>.json` and re-runs append nothing that is already
in the log. The watermark is the source's own clock, when it received or last changed an item, not the
capture time, so a photo taken in 2015 and uploaded tomorrow is picked up by tomorrow's sync and still
lands on its 2015 day. Each live source is configured by environment variables; missing ones are named
and the command exits 2.

Contacts become resolution lines (RFC 0006): each contact mints a person or company id in the record, and
every phone number and email address points at it. Set `LOGBOOK_DIAL_PREFIX` (for example `44`) so numbers
saved without a country code get one, with the national trunk `0` dropped (`07700 900123` becomes
`+447700900123`); a number that already starts with the prefix digits but no `+`, or any number when the
variable is unset, is kept as entered and flagged `unnormalised`.

WhatsApp messages become `message/v1` lines (RFC 0008), one per message, with the sender as the same kind of
phone ref, so one resolution of a number covers the address book and the chats. Media files are not copied
into the record yet: a file found under `Message/` beside the database is hashed and its digest kept under
`extra.media` for a later attach pass; set `LOGBOOK_WHATSAPP_HASH_MEDIA=0` to skip the hashing on a large store.
A group message sent from a linked device carries a `@lid` id instead of a phone number, which no contact list
knows; add WhatsApp's own ContactsV2.sqlite (it sits beside ChatStorage.sqlite) and each lid becomes an alias
of the phone number WhatsApp pairs it with (RFC 0006 `alias_of`), so the sender takes the name your contacts
import gave that number, whichever import came first.

Google Photos from a Takeout become `photo/v1` lines (RFC 0002), one per media file in the `Google Photos/`
folder, timed by the sidecar's taken time, with the place, the album, the caption and the names Google tagged as
`extra.people` refs (never resolved); a live photo's still and motion halves are one `camera` line, a photo from a
shared album is `received`, an edited copy with no sidecar is still a line, timed by the file. The sidecar naming
Google uses (`.json`, `.supplemental-metadata.json`, the truncated and `(1)`-numbered variants) is matched
defensively and a sidecar with no file is counted. Media files are hashed into `extra.media` as for WhatsApp, never
copied; set `LOGBOOK_TAKEOUT_HASH_MEDIA=0` to skip the hashing.

Apple Notes become `note/v1` lines (RFC 0010), one per note, with the plain text pulled out of the note archive,
the title, the folder and the modification time. A note edited since the last import is a new line (its `raw_id`
carries the modification time); password-protected notes are skipped because their body is encrypted; notes in
Recently Deleted are logged and flagged `deleted`.

Calendar entries become `event/v1` lines (RFC 0009), one per entry as the phone stores it: the span, the
calendar, the place, the organizer and attendees as email refs, the status; a recurring entry is one line
carrying its rule as RRULE text and a moved occurrence points back at it — occurrences are never expanded.
An all-day entry is placed at local midnight in your record's timezone. The store's placeholder rows (a
start before 1900, such as 1601) are skipped and counted; a birthday from 1965 is kept.

Calls become `call/v1` lines (RFC 0012), one per call the phone's log stores, from the `CallHistory.storedata`
an encrypted backup carries: the start, the end when the call was answered, the direction, whether it connected,
the seconds it lasted, the other end as a phone, email or handle ref (the same shape as a message's sender, so
one resolution of a number covers the address book, the chats and the calls) and the service as the phone names
it — `cellular`, `facetime`, `facetime-audio`, or a third-party app such as `whatsapp`. A missed call is a line
too. Tier 1: a call record is about your own time and carries nobody's words. Any `add ios-calls <file>` names
the adapter for a store copied out under another name; `logbook add <file>` recognises it by content.

Flights become `flight/v1` lines (RFC 0013), one per flight, from up to three places that meet on one key,
`(date, carrier, number)`: a Flighty export (`add flights <csv>`, evidence `tracked`), your calendar plus a
silence in your location points that starts at one airport and ends at another (`infer flights`, evidence
`inferred`), and your own sentence (`add flight "LX 561 NCE ZRH 2026-09-27 pilot"`, evidence `declared`). A
flight seen twice is not written twice as two flights: the later observation supersedes the standing line with
the merge — the tracker's fields win, your declared role always wins — and lists every observation it folded in.
The package ships the world's 1,150 large airports with their zones; `--airports FILE` (or `LOGBOOK_AIRPORTS`)
adds a private field. Tier 1; a booking reference is never kept.

`show` prints people by name — the sender of a message, the organizer and attendees of an event — and the
names come from your own resolution lines, never from the raw lines: import your contacts to get them. The last unretracted resolution of a ref wins (RFC 0006); a ref
nobody has resolved shows as the source gave it, after the name the source itself attached, if any.
`show --raw` prints every ref unchanged. Either way, `show` only reads.

Transcripts become `transcript/v1` lines (RFC 0004), one per recording, tier 3 by default because a transcript
carries other people's words in full (`--tier` overrides). The text is never in the line: the file's own bytes go
into the content-addressed store, `attachments/<sha256>` (SPEC §1.1), and the line points at them; `raw_id` is
`<source>:<sha256>` unless the file brings one, so the same transcript added twice is one line. `logbook add
transcript <file|folder> --source <name>` reads JSON already in transcript/v1 shape (the interchange format any tool
can write: a `logbook export` line minus the chain fields), WebVTT and SRT (each cue a turn, the speaker from the
voice tag or a leading `Name:`, else unknown), and Markdown or plain text with `Speaker: text` lines and an optional
front-matter block for `title`, `started_at`, `ended_at` and `participants`. A file with no start of its own takes
`--at`, else a date and time in its name (`2026-03-01T13-00-00Z …`, Zoom's `GMT20260301-130000_…`), else it is
skipped and counted. Speakers stay as the source labels them; nothing is resolved here. Turn and speaker counts
and the duration sit under `extra`.

`stats` is one screen of what the record holds, counted through the index: lines per kind, source and year, retractions,
resolutions, attachments. It prints numbers, kinds, sources and dates, never what a line says; `--json` gives the same as one object.

| Source | Variables | What it logs |
|---|---|---|
| `immich` | `LOGBOOK_IMMICH_URL`, `LOGBOOK_IMMICH_KEY` | one `photo/v1` line per asset: capture time, camera, place, size, faces as person ids, never the pixels |
| `dawarich` | `LOGBOOK_DAWARICH_URL`, `LOGBOOK_DAWARICH_KEY` (`LOGBOOK_DAWARICH_LOOKBACK_H`, default 24) | one `location/v1` line per point, identical to the line its export gives |
| `imessage` | none required: this Mac's `~/Library/Messages/chat.db` (`LOGBOOK_IMESSAGE_DB` for another store; `LOGBOOK_IMESSAGE_LOOKBACK_H`, default 24; `LOGBOOK_IMESSAGE_HASH_MEDIA=0` to skip hashing) | one `message/v1` line per message, identical to the line the phone backup's sms.db gives |
| `granola` | `LOGBOOK_GRANOLA_KEY` (`LOGBOOK_GRANOLA_URL`, default `https://public-api.granola.ai/v1`; `LOGBOOK_GRANOLA_LOOKBACK_H`, default 24; `LOGBOOK_GRANOLA_SUMMARIES=0` to skip the summaries) | one `transcript/v1` line per recording, tier 3, the transcript in `attachments/`; plus Granola's AI summary as a tier-2 `note/v1` line with `extra.derived_from` the transcript line's id |
| `gcal` | `LOGBOOK_GCAL_URLS`: Google Calendar's private iCal addresses, comma-separated, each optionally `name=url` (`LOGBOOK_GCAL_LOOKBACK_H`, default 24) | one `event/v1` line per event, identical to the line the calendar's `.ics` export gives (`source` `ics`) |

Create the Immich key under *Account settings → API keys* with only the **asset.read** permission.
The logbook only ever reads; a key that cannot write is a key that cannot do harm if it leaks.

## Keep it flowing

Import your Dawarich export once, then let `sync` pick up every point your phone sends after it:

```bash
export LOGBOOK_DAWARICH_URL=https://dawarich.example.org   # your own server
export LOGBOOK_DAWARICH_KEY=...                            # Settings → Account → API key
logbook add ~/Downloads/dawarich-export.json               # once: the history
logbook sync dawarich                                      # then, as often as you like
```

Both write the same line for the same point (same `raw_id`), so nothing you already imported is written
twice. The first `sync` starts from the newest Dawarich point already in the record; after that from the
last point it saw. A phone uploads in batches, so a point can reach the server after newer ones: each
sync looks back 24 hours before its watermark and skips what the record already has, and says how many
that was. Set `LOGBOOK_DAWARICH_LOOKBACK_H` for a longer or shorter window; `--since` pulls from an exact
time instead.

On a Mac, `logbook sync imessage` reads the Messages database the Mac itself keeps, read-only, and writes
the same line for the same message as the phone backup (same `raw_id`, the message guid), so a record
seeded with `import-backup` carries on from its newest message and nothing is written twice. The first
run starts from the newest iMessage line already in the record, later runs from the newest message seen,
each looking back 24 hours (`LOGBOOK_IMESSAGE_LOOKBACK_H`) for a conversation another device synced late.
Attachments stay where Messages keeps them; a file that is there is hashed into the line, one that is
not is flagged. The terminal needs **Full Disk Access** (System Settings → Privacy & Security) to read
the database; without it the sync says so on one line and exits 1.

Granola works the same way (ADR 0017: backfill and live share one mapping). Create the key under *Settings →
Connectors → API keys* (Business and Enterprise plans; scope it to your personal notes), export it as
`LOGBOOK_GRANOLA_KEY`, and run:

```bash
logbook add transcript ~/Granola-export/ --source granola   # once, if you have exports; optional
logbook sync granola                                        # then nightly: 0 5 * * * logbook sync granola
```

Each recording is one `transcript/v1` line, `raw_id` `granola:<note id>`, with the transcript's segments stored
under `attachments/` and the attendees as Granola names them; the AI summary follows as a `note/v1` line, tier 2,
marked `extra.derived = true` and pointing at the transcript by id (set `LOGBOOK_GRANOLA_SUMMARIES=0` to skip it).
A note made without a recording (one empty turn, zero seconds) gives no transcript line, only its summary,
counted as `without a recording`.
The watermark is the recording's end; each sync looks back 24 hours (`LOGBOOK_GRANOLA_LOOKBACK_H`) and skips what
the record already has. A network failure is retried once, then the sync exits 1 with a clear message and nothing is
written: a batch is all or nothing.

`logbook sync gcal` pulls your Google calendars from their private iCal addresses (Google Calendar →
Settings → the calendar → *Integrate calendar* → *Secret address in iCal format*), one whole calendar per
URL, and reads each with the same reader `logbook add` uses for an `.ics` export, so a calendar you
imported from a Takeout or settings-page export and the same calendar pulled by URL are one line per
event (same `raw_id`, the event's UID and last-modified time; ADR 0017). Name a feed with `name=url` when it has no
name of its own. The watermark is the newest last-modified time seen; each run keeps the events changed
in the 24 hours before it (`LOGBOOK_GCAL_LOOKBACK_H`) and reports, per calendar, how many it saw and how
many were new. A calendar that fails (an expired secret address is a 404) is one line on stderr, the others
are still written, the watermark stays put and the exit is 1.

```bash
export LOGBOOK_GCAL_URLS='Sailing=https://calendar.google.com/calendar/ical/…/private-…/basic.ics,https://…'
logbook sync gcal --dry-run                                # counts per calendar, nothing written
logbook sync gcal
```

Your boat, your aircraft and your car are *subjects* with tracks of their own, not places (ADR 0018). Register
each once in `assets.json`, then let `sync` ask the receivers that hear them:

```bash
logbook assets add solvind --kind yacht --name Solvind --mmsi 999000001        # synthetic MMSI; use your own
logbook assets add ln-zz1 --kind aircraft --name "the club's Cub" --icao24 000a01 --registration ZZ-ZZ1
logbook assets list
export LOGBOOK_AISSTREAM_KEY=...                            # free key from aisstream.io
uv sync --extra ais                                         # or: pip install 'openlogbook[ais]'
logbook sync ais --dry-run                                  # listen for 60 s, count, write nothing
logbook sync ais                                            # then: */10 * * * * logbook sync ais
logbook sync adsb                                           # OpenSky, no key needed; LOGBOOK_OPENSKY_USER/PASS optional
```

Each position is a `location/v1` line like your own, with `subject` set to the asset's id and `raw_id` from the
receiver, the identifier and the fix time (`aisstream:<mmsi>:<unix seconds>`, `opensky:<icao24>:<unix seconds>`),
so a report heard twice is one line, and a stream you saved to a file (`logbook add messages.jsonl`) and the same
reports heard live are one line too. `state/ais.json` and `state/adsb.json` keep a watermark per asset. `show`
lists the boat's points as their own run, named by the asset; whether you were aboard is for an engine to decide
from the two tracks, never written on a line. `LOGBOOK_AISSTREAM_LISTEN_S` sets how long each `sync ais` listens
(a vessel under way reports every few seconds); OpenSky's `states/all` is the present, one fix per aircraft per
poll, so poll as often as its rate limit allows.

**A secret iCal address is the whole calendar** to anyone who holds it; Google can reset it. Keep the
URLs in the shell environment only, as the Dawarich key below: the logbook never prints one, naming a
calendar by its name or by eight characters of the URL's hash.

**A Dawarich API key is full access** to your account: it can read and delete every point you have.
Keep it in the shell environment only (your shell profile, a password manager's CLI, a secrets file
outside the record) and never in the record, the repository or a script you share. The logbook sends it
only in the `Authorization` header and never prints it.

## Reading the day back

`logbook derive stays` is the first reader of the record: it turns the day's `location/v1` lines into
stays, stops and moves and prints them in your local time, or as JSON with `--json`. Nothing is written
to the record; the thresholds live in `policy/stays.json` (created with defaults on the first run) and an
optional `places.json` at the root names places.

```bash
logbook derive stays                          # today
logbook derive stays --day 2026-09-30
logbook derive stays --since 2026-09-01 --until 2026-09-30 --json
logbook derive stays --subject solvind        # one asset's own track (assets.json)
```

A stay is a span at one place of twenty minutes or more, or of any length when something is attached to
it: a calendar event, a transcript, a note, a call, a message or a photo whose time falls inside it.
Evidence promotes; duration is the fallback. A shorter span with nothing attached is a stop, kept and
flagged. A move is what lies between: its distance along the points, its duration, and a mode from the
speed (walk, car, train, flight; flight also when a gap starts and ends near airports). The night of each
day is the longest stay between 22:00 and 08:00; a night with none is in transit. An asset registered in
`assets.json` (ADR 0018) gets its own stays and moves, and a stay of yours that matches its position is
marked `aboard`.

## Handing a window to someone

A crossing package (RFC 0005) is the bundle you hand a named member of your circle: the lines of a window,
verbatim, the attachments they point at, and the resolution lines that let the reader name the people in
them, so they need nothing else from your record. The first reader is Hermes, an agent that pulls one
nightly and proposes actions.

```bash
logbook export crossing --to hermes --since 2026-03-01T00:00:00Z --dry-run     # counts per kind and tier, writes nothing
logbook export crossing --to hermes --since 2026-03-01T00:00:00Z               # the first window, tier 1 only
logbook export crossing --to hermes --since last --tier 1,2                    # every night: since the last one, tiers 1 and 2
logbook export crossing --to hermes --since last --tier 1,2 --kinds message,event --out /srv/hermes/inbox/tonight
```

The window is `[--since, --until)`, `--until` defaulting to now; `--since last` starts where the last crossing
to that destination ended (`exports/crossing.json`), and the first run must say where to start. The bundle
lands under `export/crossing/<destination>/<time>/` unless `--out` says otherwise: `manifest.json`,
`entries.jsonl`, `attachments/<sha256>` for every referenced file the store holds (a missing one stays a
reference), and `resolution.jsonl` when any exported line names someone your contacts have resolved,
alias hops included. A JSON parser is all a reader needs.

How much may cross is a setting in your record, not in the code (ADR 0016): `policy/crossing.json` maps each
destination to its ceiling, `{"hermes": {"max_tier": 2}}` by default. Tier 1 crosses by default; tier 2 only
with `--tier 1,2`, and the manifest then lists every tier-2 line under `review`; tier 3 only when the file
allows it *and* you type `--tier 1,2,3`, and the manifest and the console say loudly that it did. A request
above the ceiling is refused with the file's name. Every real export appends one `crossing/v1` line (RFC 0011)
to the chain — destination, window, counts per tier, the ceiling in force, the package's digest — so the
record itself shows every time anything left it. `--dry-run` writes nothing and appends nothing.

## Three rules

1. **Append only.** Every line is hash-chained to the one before. A broken chain is an error, never repaired silently.
2. **Files first.** No database is required to read, verify or export a logbook. Databases are caches.
3. **Nothing leaves.** Personal lines are encrypted with your key. There is no server. Sharing is a page handed to a named person.

## Read next

- Docs site: https://bighydro.github.io/logbook/
- [VISION.md](VISION.md) — why, and the rules the product refuses to break
- [LORE.md](LORE.md) — where the logbook comes from: ships, pilots, diaries, and the log in computing
- [SPEC.md](SPEC.md) — the format, one page; this is the part meant to become a standard
- [ARCHITECTURE.md](ARCHITECTURE.md) — the five layers and what each may depend on
- [ROADMAP.md](ROADMAP.md) — what ships when
- [CONTRIBUTING.md](CONTRIBUTING.md) — one issue per PR, signed commits, synthetic data only; the easiest thing to build is an adapter for the export you have

## Status

v0.1 — the format, the CLI (init, add, show, verify, export) and the conformance fixture. Engines (days, trips, people) and the circle (sharing) are the next layers; see the roadmap.

Apache-2.0 for code. The specification is CC0.
