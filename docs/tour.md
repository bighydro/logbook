# The tour: every command on your own record

[Try it](try-it.md) is five minutes on a demo record and [The first hour](first-hour.md) is `logbook setup`
screen by screen. This page is the long form: what each command does on a record of your own, in the order
you are likely to meet them. Every example is synthetic; the person lives in Oslo and does not exist.

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
`crypto` extra and the password in one environment variable, never a flag:

```bash
pip install "openlogbook[crypto]"        # or: uv tool install "openlogbook[crypto]"
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
them: Health runs through `apple-health` (RFC 0014; `healthdb.sqlite` is copied first so the store finds its
source names beside it), Safari is reported as *copied, no adapter yet*; `--only calls,health` names them too. Without the extra
installed the command prints the `pip install` line and exits 2; without the variable it says which one to set.

## Where to keep the record

Never in a folder that iCloud Drive, Dropbox, Google Drive or OneDrive syncs. Those services evict files to the
cloud and fetch them back on demand, so reads stall on files that are not really there, and the record ends up
on someone else's server. Keep it in a plain local folder and point `LOGBOOK_HOME` at it:

```bash
logbook init ~/Records/Logbook           # once
export LOGBOOK_HOME=~/Records/Logbook    # in your shell profile, so every command finds it
```

`logbook setup` asks for the folder and refuses one a sync client owns, with the reason; then the timezone, your own
names, emails and phones (`policy/owner.json`, so you are never your own company), your home as coordinates pasted
from a maps app, and what is on this machine to import — a Takeout in `~/Downloads`, an iPhone backup, Messages on
a Mac — each with a dry run first. One question at a time, each with its default and why it is asked; `q` stops
and `logbook setup` again continues where it stopped (`state/setup.json`); `--yes` takes every default. It never
asks for a secret: a live source is named by its variable and where the key comes from.
[docs/first-hour.md](first-hour.md) shows every screen.

Back it up with `logbook backup DEST`: one verified snapshot of the record under `DEST/<owner_id>/<timestamp>/`
on another disk — the month files, `logbook.json`, `policy/`, `places.json`, `assets.json`, `attachments/` and
`notes/`; never `index.sqlite`, `inbox/` or `state/` — with every file the previous snapshot already holds
unchanged hard-linked to it, so a daily snapshot of a record with gigabytes of attachments costs the bytes that
changed. The copy is verified where it lands and its head must be the live head, or nothing is kept; `--keep N`
prunes to the newest N; `--verify` also hashes every attachment against its name. `backup list DEST` shows
each snapshot with its lines, head and size; `backup restore SNAPSHOT TARGET` copies one back into an empty
folder and verifies it. A destination inside the record or under a sync client's folder is refused. Time
Machine or an equivalent that copies the folder as it is works too. [docs/backup.md](backup.md) has the
launchd and systemd examples for a nightly run.

```bash
logbook backup /Volumes/Backup/Logbook --keep 14     # a verified snapshot, the newest fourteen kept
logbook backup list /Volumes/Backup/Logbook
logbook backup restore /Volumes/Backup/Logbook/<owner_id>/2026-06-02T071500Z ~/Records/Logbook
```

`logbook doctor` checks that this machine is set up to keep the record, one line per check, `pass`, `warn` or
`fail`, and exits 1 when anything fails: the record is found and `verify` is green with `logbook.json` at
the head; `index.sqlite` is current; `policy/owner.json` names at least one alias; `places.json` has a
home; `assets.json` is a registry; each optional extra (`ais`, `crypto`, `sealed`, `speakers`,
`transcribe`) is installed, with its install line when not; the variables of every live source the record
uses are set, by name only, never a value; the volume has room; and the folder is not one iCloud Drive,
Dropbox, OneDrive or Google Drive syncs, which is a fail with the reason; the last scheduled run was
recent and clean, and a restore test of the backup passed within 35 days ([the schedule](schedule.md)). It
reads and never writes, so it is safe to run any time.

```bash
logbook doctor
pass  record             12,772 lines, head 53d39fda0b2c…, verified; /Users/ines/Records/Logbook
pass  index              index.sqlite is current with logbook.json
warn  owner              policy/owner.json is empty: add your other names, emails and phones so you are never your own company
pass  places             4 place(s), home: Home
pass  assets             1 asset(s): nordlys
pass  extra:ais          websockets is installed
pass  extra:crypto       cryptography is installed
pass  extra:sealed       pyrage is installed
warn  extra:speakers     pyannote.audio not installed: pip install "openlogbook[speakers]"
warn  extra:transcribe   mlx-whisper or faster-whisper not installed: pip install "openlogbook[transcribe]"
warn  sync:dawarich      set LOGBOOK_DAWARICH_KEY
pass  disk               184.2 GiB free on the record's volume
pass  folder             a plain local folder, no sync client
13 checks: 9 pass, 4 warn, 0 fail
```

## Sealing tiers 2 and 3

The envelope of every line is plain: when, what kind, which source. What a tier 2 or 3 line *says*, a note, a
message, a transaction, a health sample, can be sealed at rest with [age](https://age-encryption.org) to keys
only you hold (SPEC §2 and §4, [RFC 0029](rfcs/0029-encryption-at-rest.md), [ADR 0020](adr/0020-tiers-2-3-sealed-with-age.md)).
The chain is untouched: `verify` checks every hash without any key and says how many lines it did not open;
with your identity it opens each one and checks it against its digest too. Tier 1 is never sealed.

```bash
pip install "openlogbook[sealed]"          # pyrage, age's Rust implementation; nothing else changes
logbook key init --recovery                # this machine's identity, and a recovery identity printed once for paper
logbook seal --all                         # seal the tier 2–3 lines written before the record had recipients
logbook verify                             # valid — …; sealed: 4,100 lines, every one opened and checked
logbook key show                           # the recipients, and whether this machine's identity opens the record
logbook key add-recipient --recipient age1…   # a new laptop, a hardware key: resealed, no hash changes
```

Two recipients or none: `key init` refuses to seal until a recovery identity exists, because a record that can
lose its only key is not sealed, it is lost. The identity lives at `~/.config/logbook/identities/<owner_id>.txt`
(`%APPDATA%\logbook\identities\` on Windows), readable by you alone, never inside the record, never in a
variable that is on disk; `--identity-file PATH` or `LOGBOOK_IDENTITY_FILE=PATH` name another file. A machine
without it reads tier 1, lists every day, verifies the chain and refuses to write tiers 2–3 in one sentence.
Attachments a sealed line points at are sealed under the same name. The index is a plaintext locator and lives in
your cache directory (`~/.cache/logbook/<owner_id>/`), not in the record, with chat ids blinded; `logbook search`
does not search sealed lines. `export` writes opened payloads unless `--sealed`; a crossing package reseals to the
destination's recipient from `policy/crossing.json`, or ships opened under `--open`. `seal --all` replaces the
plain files and shreds nothing: a backup from before still holds the plaintext.

## Upgrading

0.3.0 changes how lines are hashed (format `logbook/0.2`, SPEC §3.1). A record written by 0.1.0 or 0.2.0 is refused until it is migrated. Back up first, then migrate once:

```bash
cp -a ~/Logbook ~/Logbook.bak    # or wherever LOGBOOK_HOME points
logbook migrate                  # same lines, new hashes; keeps the old files at logbook-0.1/
```

Format `logbook/0.3` (sealing, SPEC §3.1) hashes by the same rule as 0.2, so a 0.2 record is read as it is and needs no migration; `logbook seal --all` is the one optional step, and it leaves a `migration/v1` line.

0.5.0 corrects the units `apple-health` gave resting heart rate and HRV (RFC 0014). A record that imported a Health store with an earlier version carries those lines 60 and 1,000 times too large; put them right once:

```bash
logbook repair health-units --dry-run   # how many lines it would retract and re-emit
logbook repair health-units             # per wrong line a corrected line and a retraction; nothing rewritten
```

## What is in the folder

```
~/Logbook/
  logbook/          the record. one file per month. append only. never edit.
    2026/09.jsonl
  inbox/            drop anything here. `logbook inbox list` says what was read; `inbox clean` moves or deletes it.
  notes/            what you write. plain Markdown, one file per day.
  logbook.json      who this is, your timezone, the chain head; `day_start` when your day does not begin at
                    midnight ("06:00": a line at 02:00 belongs to the evening before; RFC 0036, draft).
  policy/           crossing.json: the highest tier each circle member may receive, `until` when the access is
                    lent for a while, `signed_within_days` when only days you signed lately may cross (RFC 0036, draft). yours to edit.
                    stays.json: how long a stay is, how far a place reaches. yours to edit.
                    import.json: the sources you switched off, each with a reason. yours to edit.
                    owner.json: your own other names, emails and phones, so you are never your own company. yours to edit.
                    questions.json: the digest's closing questions, each with the facts it asks on. yours to edit.
  assets.json       the boats, aircraft and cars whose tracks the record keeps (ADR 0018). yours to edit.
  places.json       the named places: lat, lon, radius_m, kind (home, asset-berth, other), tags, country. `logbook places`.
  state/            where each live source left off, and which question the digest asked. bookkeeping, not the record.
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
logbook add takeout-chat ~/Takeout/"Google Chat"      # Takeout by name: pay, chat, meet, contacts, keep, tasks, chrome, youtube, … (docs/adapters/takeout.md)
logbook add takeout-pay ~/Takeout/"Google Pay" --dry-run   # any import: count against the record, write nothing
logbook add ~/backup/31bb7ba8914766d4ba40d6dfb6113c8b614be442   # iOS Contacts from an unencrypted Finder/iTunes backup
logbook add ~/backup/7c7fba66680ef796b916b067077cc246adacf01d   # WhatsApp (iOS) ChatStorage.sqlite from the same backup
logbook add ~/backup/4f98687d8ab0d6d1a371110e6b7300f6e465bef2   # Apple Notes NoteStore.sqlite from the same backup
logbook add ~/backup/2041457d5fe04d39d0ab481178355df6781e6858   # iOS Calendar.sqlitedb from the same backup
logbook add ios-calls ~/inbox/ios-backup-<udid>/ios-calls/CallHistory.storedata   # the call log, by adapter name
logbook add health ~/inbox/ios-backup-<udid>/health/healthdb_secure.sqlite   # Apple Health, by adapter name (or apple-health)
logbook import-backup ~/backup                    # all of the above from the backup folder, in one go
logbook inbox list                                # every file under inbox/: size, the import that read it, whether every line is in
logbook inbox clean --to /Volumes/Archive        # move what is imported in full to an external disk (or --delete it); the rest stays
logbook attach import-backup ~/backup --only whatsapp,imessage,photos   # then the media the lines name, into attachments/
logbook add transcript ~/Meetings/tromso.md --source manual   # a transcript: JSON (transcript/v1), WebVTT, SRT, Markdown, text
logbook add ~/Zoom/GMT20260301-130000_Recording.transcript.vtt --source zoom   # VTT and SRT are recognised on sight
logbook add mail ~/Takeout/Mail --account you@example.org --skip-labels Spam,Trash   # Gmail via Google Takeout: one mail/v1 line per message
logbook sync granola                              # every Granola recording, and its summary as a derived note
logbook sync mail                                 # the same mailbox live over IMAP, read-only; dedupes against the Takeout import
logbook sync notion                               # what happened in Notion each day: pages created, edited, moved, archived; never their text
logbook sync github                               # commits, issues and pull requests created, closed, merged, reviews and comments (docs/adapters/github.md)
logbook add github-export ~/code/oldboat          # an old project's clone or GitHub's account export: its commits and each version of its docs
logbook add flights ~/Downloads/flighty.csv       # a Flighty export: one flight/v1 line per flight, evidence tracked
logbook add flight "LX 561 NCE ZRH 2026-09-27 pilot"   # your own word: evidence declared
logbook add story ~/Stories/lake.md --teller ola@example.org --listener kari.nordmann@example.org --refers-to 1961   # a told story (RFC 0028): on the day it was told, about the time it names
logbook infer flights                             # calendar entries + your location points leaving one airport for another: evidence inferred
logbook transcribe voice-memos                    # a transcript/v1 line per voice memo, by a local model (openlogbook[transcribe]); nothing leaves the machine
logbook add screentime --mac                      # this Mac's Screen Time sessions (knowledgeC.db, behind Full Disk Access): app, span, device; never a title or URL
logbook add screentime --backup ~/backup          # the phone's Screen Time store out of an iOS backup: hourly totals per app (docs/adapters/screentime.md)
logbook sync immich                               # everything since the last run; safe to repeat
logbook sync immich --since 2026-01-01T00:00:00Z  # or everything Immich received or changed since then
logbook sync immich --dry-run                     # count and summarise, write nothing
logbook sync immich --restart                     # the whole library again, whatever the watermark says
```

`sync` remembers where it got to in `state/<source>.json` and re-runs append nothing that is already
in the log. The watermark is the source's own clock, when it received or last changed an item, not the
capture time, so a photo taken in 2015 and uploaded tomorrow is picked up by tomorrow's sync and still
lands on its 2015 day. Each live source is configured by environment variables; missing ones are named
and the command exits 2.

The first `sync immich` by hand walks the whole library, which takes hours for hundreds of thousands of
assets (the first scheduled run reads the last 14 days: [the
schedule](schedule.md#a-sources-first-scheduled-run)). It says what it is walking before it starts —
`immich: 426,121 assets on the server, 0 already in the record` (the count the server gives; `total
unknown` when it will not say) — and then counts every page as `x of N assets`, so a long walk is told
from a loop. An interrupted walk (Ctrl-C, a lost connection, a server error) is checkpointed in
`state/immich.json` as the lines land, and the next run says `resuming where the last run stopped, at x
of N assets` and asks the server for nothing before that point; `--restart` walks the library from the
beginning instead. Each asset is fetched once: the pages are ordered by capture time, which a burst or a
batch of scans shares to the second, and the server serves such a run again at a page boundary; the
adapter sees through that and the record's own refusal of a line it already holds stays the safety net.

`sync mail` is the mailbox over IMAP (`LOGBOOK_IMAP_HOST`, `LOGBOOK_IMAP_USER`, `LOGBOOK_IMAP_PASSWORD`,
an app password): read-only, every folder resumed from its own mark, and a message the Takeout import
already wrote is refused by `Message-ID` before its body is fetched ([Mail](adapters/mail.md#mail-imap)).

`logbook sync --all` runs every configured live source in turn — configured: at least one of its
`LOGBOOK_*` variables set, and all it needs present — each from its own watermark; a disabled source or
one with no variable set is skipped and said so, and a failure in one never stops the next. The quick
sources go first and `immich` last, and the first line says the order, so a photo walk of hours never
holds up the messages, the calendar, the positions or the weather. Each source prints its own summary as
it runs, then one line per source closes the run (`ok`, `failed (status 1)`, `skipped
(LOGBOOK_GRANOLA_KEY not set)`), and the exit status is 1 when any failed. A dry run never waits out a
source's quota or rate limit: the first such answer ends that source's dry run on one line (`sync: drive:
dry run stopped at the source's limit after 0 lines: HTTP 429: …`), exit 1, nothing written, and `--all`
goes on to the next. `logbook sync --install-schedule` makes the machine run `sync --scheduled` at 00:00,
12:00 and 18:00 local and `sync --scheduled --close` at 06:00, the run that closes the day (the dream's
catch-up after the sync, when the dream is there and allowed): two launchd agents on macOS
(`~/Library/LaunchAgents/org.logbook.sync.plist` and `org.logbook.sync.close.plist`), two systemd user
timers on Linux (`~/.config/systemd/user/logbook-sync.timer` and `logbook-sync-close.timer`). The plists
or units are printed before they are written, nothing is written outside that directory, and
`--uninstall-schedule` removes them again; `--system` writes daemons for a machine nobody logs in to and
prints the two sudo commands that install them. Installing also names this machine the record's home in
`state/home.json` ([ADR 0022](adr/0022-the-records-home.md)): the one machine that writes, which `logbook
doctor` checks on every machine and warns about on any other. The agent runs the Python that installed it
and points at the record found at install time; the keys your sources need it reads from
`~/.config/logbook/sync.env` (`KEY=value` lines, mode 600), which you write and the command never does.
The scheduled run is `sync --all` (a source's first scheduled run reads its last 14 days, never its whole
history: [the schedule](schedule.md#a-sources-first-scheduled-run)), then `doctor`, with the outcome in
`state/last-run.json`, the restore test on the first Sunday of the month, and, with
`LOGBOOK_NOTIFY_TELEGRAM_TOKEN` and `LOGBOOK_NOTIFY_TELEGRAM_CHAT` in that file, one Telegram message
when something is wrong or on Sunday evening ([the schedule](schedule.md)). `sync weather` is the one
source that asks a third party about your days: it asks nothing, by name or in `--all`, unless that file
(or the environment) says `LOGBOOK_WEATHER=1`, and then each run asks about the days since the last,
yesterday on the first.

```bash
logbook sync --all                                # every configured source, one after the other
logbook sync --all --dry-run                      # count per source, write nothing
LOGBOOK_WEATHER=1 logbook sync weather --since 2026-06-01   # the weather of your days' places, one decimal of latitude (docs/adapters/weather.md)
logbook sync --install-schedule                   # 00:00, 06:00 (the close), 12:00 and 18:00 local
logbook sync --scheduled                          # what the schedule runs: sync --all, then doctor
logbook sync --uninstall-schedule
```

A nightly `logbook backup` goes on the same scheduler, by hand: [docs/backup.md](backup.md) has the
launchd agent and the systemd timer for a 03:00 snapshot that keeps two weeks.

Contacts become resolution lines (RFC 0006): each contact mints a person or company id in the record, and
every phone number and email address points at it. Set `LOGBOOK_DIAL_PREFIX` (for example `44`) so numbers
saved without a country code get one, with the national trunk `0` dropped (`07700 900123` becomes
`+447700900123`); a number that already starts with the prefix digits but no `+`, or any number when the
variable is unset, is kept as entered and flagged `unnormalised`.

WhatsApp messages become `message/v1` lines (RFC 0008), one per message, with the sender as the same kind of
phone ref, so one resolution of a number covers the address book and the chats. Media files are not copied
with the lines: a file found under `Message/` beside the database is hashed and its digest kept under
`extra.media`, and `logbook attach import-backup <backup> --only whatsapp,imessage,photos` later streams every
file the lines name out of the backup into the content-addressed store, checked against the line
([docs/attachments.md](attachments.md)); set `LOGBOOK_WHATSAPP_HASH_MEDIA=0` to skip the hashing on a large store.
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
`(date, carrier, number)`: a Flighty export (`add flights <csv>`, evidence `tracked`), your calendar plus your
location points leaving one airport and next reaching another, silent in between or not (`infer flights`,
evidence `inferred`), and your own sentence (`add flight "LX 561 NCE ZRH 2026-09-27 pilot"`, evidence `declared`). A
flight seen twice is not written twice as two flights: the later observation supersedes the standing line with
the merge — the tracker's fields win, your declared role always wins — and lists every observation it folded in; a
codeshare (two numbers, one aircraft leaving once) is one flight too. An inferred leg is a flight only between airports
150 km or more apart, never one a tracked flight already covers, and carries a number only when it is the flight the
calendar entry names.
The package ships the world's 1,150 large airports with their zones and OurAirports' `type`; `--airports FILE`
(or `LOGBOOK_AIRPORTS`) adds a private field (`type` optional: `medium_airport` for a regional field with
scheduled traffic). Tier 1; a booking reference is never kept.

Apple Health becomes `health-sample/v1` lines (RFC 0014) from the `healthdb_secure.sqlite` an encrypted backup
carries: steps, distance, active and basal energy and flights climbed summed into quarter-hour buckets per device;
heart rate at its own resolution, at most one reading a minute per device; resting heart rate, heart-rate
variability and weight one line each; every sleep stage as a span with its stage; every workout as a span with
its duration, activity, energy and distance. Each line names the device that measured it (`Watch7,1`) and, when
`healthdb.sqlite` is beside the store, the source's name. Tier 3 (SPEC §4; `--tier` overrides). `logbook add health <file>` names the adapter;
`logbook add <file>` recognises the store by content. Re-importing a later backup appends only what is new.

`show` prints people by name — the sender of a message, the organizer and attendees of an event — and the
names come from your own resolution lines, never from the raw lines: import your contacts to get them. The last unretracted resolution of a ref wins (RFC 0006); a ref
nobody has resolved shows as the source gave it, after the name the source itself attached, if any.
`show --raw` prints every ref unchanged, and a note's whole text where `show` prints its first line and
`… (+N lines)`. A calendar entry two calendars carry (the same title, or the same flight number, within five
minutes) is one row naming both sources. Either way, `show` only reads.

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

Mail becomes `mail/v1` lines (RFC 0015), one per message, tier 2 by default (`--tier` sets another for the whole
import, never per message). `logbook add mail <file.mbox|folder>` reads a Google Takeout `Mail/` export — or any mbox —
streamed, one message in memory at a time however large the file (the lines read from the last 200 wait while the
record is asked about them): the `Message-ID` as `raw_id` (prefixed by the
mailbox when `--account` names it, so a re-import appends nothing; a live puller appends nothing either way, since
every mail road asks the record by the normalised `Message-ID` before it writes), the thread root from
`References`, the sender and recipients as `{email, name}` exactly as the headers spell them (a resolution of the
address names them in `show`, as for a message's sender), the subject, the `Date` header with its offset kept and
`at` in UTC, Gmail's labels, the body as plain text (an HTML-only message stripped to its text, no library), the
size, and every attachment by name, media type and length — never decoded. Attachments are decoded, hashed and put
into `attachments/` only with `--attachments`; otherwise the line names them and the record holds no bytes.
`direction` is `sent` when
the sender is one of your addresses — put `"owner_emails": ["you@example.org"]` in `logbook.json`, or pass
`--account` — else `received`. `--only-labels`/`--skip-labels` keep or drop by Gmail label, `--since` cuts by day or
instant. A message with no `Message-ID` is keyed by the digest of its bytes and counted; a message with no readable
`Date` is timed by its mbox separator and counted; a body longer than 64 KB is cut and counted; nothing is dropped
silently. Built for a 20 GB Takeout: read in chunks at well over 40 MB/s with one message in memory, a progress line
every 10,000 messages with the rate, and resumable — `inbox/manifest.json` keeps the byte offset of the last message
the record holds, so an interrupted `add mail` picks up there and a finished one reads nothing (`--restart` reads
it all again). `show` prints
`✉ subject — from → to (n attachments)`, never the body; `show --raw` prints the body under the row.
[docs/adapters/mail.md](adapters/mail.md) has the whole of it.

`stats` is one screen of what the record holds, counted through the index: lines per kind, source and year, retractions,
resolutions, attachments. It prints numbers, kinds, sources and dates, never what a line says; `--json` gives the same as one object.
`stats --health` is one row per day from the health lines — hours asleep (the night that ends on that day, asleep
stages only — never in bed or awake — each device's spans unioned so a night written twice counts once, then the longest device, never a sum across devices), steps (per quarter hour the larger device, summed) and resting heart rate — and
prints no device, zone or other field; `--json` gives the rows as `days`.

| Source | Variables | What it logs |
|---|---|---|
| `immich` | `LOGBOOK_IMMICH_URL`, `LOGBOOK_IMMICH_KEY` | one `photo/v1` line per asset: capture time, camera, place, size, faces as person ids, never the pixels |
| `dawarich` | `LOGBOOK_DAWARICH_URL`, `LOGBOOK_DAWARICH_KEY` (`LOGBOOK_DAWARICH_LOOKBACK_H`, default 24) | one `location/v1` line per point, identical to the line its export gives |
| `imessage` | none required: this Mac's `~/Library/Messages/chat.db` (`LOGBOOK_IMESSAGE_DB` for another store; `LOGBOOK_IMESSAGE_LOOKBACK_H`, default 24; `LOGBOOK_IMESSAGE_HASH_MEDIA=0` to skip hashing) | one `message/v1` line per message, identical to the line the phone backup's sms.db gives |
| `beeper` | `LOGBOOK_BEEPER_TOKEN` (`LOGBOOK_BEEPER_URL`, default `http://localhost:23373`; `LOGBOOK_BEEPER_ALLOW_REMOTE=1` to read a Beeper on another machine, which the design says not to) | one `message/v1` line per message of every chat Beeper Desktop bridges, `source` `beeper-<network>`; attachments referenced by asset id, never fetched; `--networks` chooses, default every one but imessage |
| `granola` | `LOGBOOK_GRANOLA_KEY` (`LOGBOOK_GRANOLA_URL`, default `https://public-api.granola.ai/v1`; `LOGBOOK_GRANOLA_LOOKBACK_H`, default 24; `LOGBOOK_GRANOLA_SUMMARIES=0` to skip the summaries) | one `transcript/v1` line per recording, tier 3, the transcript in `attachments/`; plus Granola's AI summary as a tier-2 `note/v1` line with `extra.derived_from` the transcript line's id |
| `notion` | `LOGBOOK_NOTION_TOKEN` (`LOGBOOK_NOTION_ROOTS`: page or database ids or links to limit to; `LOGBOOK_NOTION_OWNER_ID`: your Notion user id, to mark your own actions) | one `event/v1` line per page, day and action (`created`, `edited`, `moved`, `archived`), tier 1: title, path, id, url, who acted, the body's digest and word count, a row's status, select, date and checkbox values, its database and the ids of the rows its relations link to; never the text ([Notion](#notion)) |
| `github` | `LOGBOOK_GITHUB_TOKEN` (a fine-grained token, read-only) and `LOGBOOK_GITHUB_REPOS` (`owner/name`, comma-separated, or `--all`; `LOGBOOK_GITHUB_URL` for a GitHub Enterprise Server); your logins under `handles` in `policy/owner.json` | one `event/v1` line per commit, issue or pull request created, closed or merged, review and comment, tier 1 (tier 2 from a private repository): the message, body or comment in full, who acted (`owner` or `other`), `agent: true` when an agent's session marker is in the text; a watermark per repo ([GitHub](#github)) |
| `gcal` | `LOGBOOK_GCAL_URLS`: Google Calendar's private iCal addresses, comma-separated, each optionally `name=url` (`LOGBOOK_GCAL_LOOKBACK_H`, default 24) | one `event/v1` line per event, identical to the line the calendar's `.ics` export gives (`source` `ics`) |
| `drive` | `LOGBOOK_DRIVE_SA_KEY` (a Workspace service account's JSON key file) and `LOGBOOK_DRIVE_USER` (the address it reads as); [Google Drive](#google-drive) | one `event/v1` line per file, hour and activity — created, edited, renamed, moved, shared, commented on, trashed, deleted, restored — with a count; the file's name, type, id and link, who acted, never its content; tier 1 |
| `gtasks` | the same two; [Google Tasks](#google-tasks) | one `task/v1` line per task each time it changes, the line a Takeout export gives (`source` `google-takeout`), so `logbook tasks` reads it and a later export writes nothing twice; a done one says how long it was open; never the notes; tier 2 |
| `meet` | the same two; [Google Meet](#google-meet) | one `event/v1` line per call that has ended, tier 1: when, the meeting code, who joined as Meet names them; and when Meet transcribed it, one `transcript/v1` line as Granola's is, tier 3, the words in `attachments/` |
| `gaudit` | the same two; [Google sign-ins](#google-sign-ins) | one `event/v1` line per sign-in event of yours in the Workspace's login audit log, tier 1: when, what happened, how, and the place Google derived from the address; never the address |

Create the Immich key under *Account settings → API keys* with only the **asset.read** permission.
The logbook only ever reads; a key that cannot write is a key that cannot do harm if it leaks.

## What never enters the record

Demo, sample or placeholder data never enters the record: an adapter existing is not a decision to run it.
Your list of switched-off sources lives in `policy/import.json`, `{"disabled": [{"source": "sbb", "reason":
"a demo account"}]}`; `add`, `sync` and `import-backup` skip a disabled source and say so, with or without
`--only`, and `logbook sources` lists every adapter this build has, file and live, with its state and the
reason. `init` writes the empty list, and a record made earlier gets it on the first run. An alias stands for
its adapter (`books` for `apple-books`, `health` for `apple-health`), and a name no adapter carries is
listed as such rather than silently ignored.

## Keep it flowing

Import your Dawarich export once, then let `sync` pick up every point your phone sends after it:

```bash
export LOGBOOK_DAWARICH_URL=https://dawarich.example.org   # your own server
export LOGBOOK_DAWARICH_KEY=...                            # Settings → Account → API key
logbook add ~/Downloads/dawarich-export.json               # once: the history
logbook sync dawarich                                      # then, as often as you like
```

Both write the same line for the same point (same `raw_id`), so nothing you already imported is written
twice. The first `sync` starts from the newest Dawarich point already in the record (the first scheduled
run from 14 days back when that point is older: [the
schedule](schedule.md#a-sources-first-scheduled-run)); after that from the last point it saw. A phone
uploads in batches, so a point can reach the server after newer ones: each sync looks back 24 hours
before its watermark and skips what the record already has, and says how many that was. Set
`LOGBOOK_DAWARICH_LOOKBACK_H` for a longer or shorter window; `--since` pulls from an exact time instead.

On a Mac, `logbook sync imessage` reads the Messages database the Mac itself keeps, read-only, and writes
the same line for the same message as the phone backup (same `raw_id`, the message guid), so a record
seeded with `import-backup` carries on from its newest message and nothing is written twice. The first
run starts from the newest iMessage line already in the record (the first scheduled run from 14 days
back when that line is older, or when there is none), later runs from the newest message seen,
each looking back 24 hours (`LOGBOOK_IMESSAGE_LOOKBACK_H`) for a conversation another device synced late.
Attachments stay where Messages keeps them; a file that is there is hashed into the line, one that is
not is flagged. The terminal needs **Full Disk Access** (System Settings → Privacy & Security) to read
the database; without it the sync says so on one line and exits 1.

### Beeper

Beeper Desktop bridges WhatsApp, Signal, Telegram, Instagram, Messenger, LinkedIn, X and more into one app,
and while it runs it serves a small HTTP API on this machine only. `logbook sync beeper` reads every chat of
every network through it, read-only, and writes one `message/v1` line per message under `source`
`beeper-<network>` (`beeper-whatsapp`, `beeper-signal`, …), so readers can tell the networks apart.

```bash
export LOGBOOK_BEEPER_TOKEN=...                             # Beeper Desktop → Settings → Developers → Approved connections, +
logbook sync beeper --dry-run                               # count per network, write nothing
logbook sync beeper                                         # every network but imessage, each chat from its own watermark
logbook sync beeper --networks whatsapp,signal              # only these
logbook sync beeper --networks telegram --since 2020-01-01T00:00:00Z   # a network added later: its history, once
```

Enable the API under *Settings → Developers* (the switch *Beeper Desktop API*; it listens on
`http://localhost:23373` while the app runs), then create a token with the *+* next to *Approved
connections*. **The token is a password**: it can read every chat and send as you. Keep it in the variable
in your shell profile, never in a file of the record, and revoke it there when you stop using it. Leave
*Remote Access* off: the API is meant to be read from this machine only, and `sync beeper` refuses a
`LOGBOOK_BEEPER_URL` that is not localhost unless `LOGBOOK_BEEPER_ALLOW_REMOTE=1` says you know what you are
doing. The sync only ever issues GET requests (listing accounts, chats and messages); nothing here sends,
reacts, marks read, archives or changes a thing, and a test holds it to that. `logbook doctor` says whether
`sync:beeper` is configured and, when it is, whether the app answers — the one other call, `GET /v1/info`.

Each chat keeps its own watermark (`marks` in `state/beeper.json`): a run reads a chat back to its newest
message seen, less 24 hours for a message a bridge delivers late, and the record refuses what it already
holds. A chat with no watermark yet — every chat on the first run, a new chat later — starts at the
source's watermark, or at `--since`, or, on the source's first scheduled run, 14 days back; to pull the
history of a network you add to `--networks` later, give `--since` once. Reactions, hidden messages and
events with neither text nor attachment (joins, calls, bridge state) are skipped and counted. An
attachment is referenced by its Beeper asset id, size, media type and file name under `extra.media`,
never downloaded: the bytes stay in Beeper. When the app is not running the sync says so on one line and
exits 1, and `sync --all` goes on to the next source.

**Known overlap.** Beeper is a second view of chats other sources already read: an iMessage from this Mac's
own database (`sync imessage`), a WhatsApp message from a chat export or the phone's backup, the Beeper
cache in an iPhone backup (the `beeper` file adapter). Those lines carry other sources and raw ids, so the
record does not deduplicate them against the Beeper lines. `--networks` is how you choose; the default
pulls every network but imessage, which the local source has.

### Notion

`logbook sync notion` keeps what happened in your Notion workspace — a page created, edited, moved or
archived, a task's status changed — as one `event/v1` line per page, day and action, so the Day can say
*worked on Sail plan, +340 words* or *Book the ferry: Doing → Done*. It is a record of events, never a
mirror: a line points at the page by its id and link and holds no word of what the page says.

```bash
export LOGBOOK_NOTION_TOKEN=ntn_...                         # the integration's secret: a password
export LOGBOOK_NOTION_OWNER_ID=...                          # optional: your Notion user id, to mark your own actions
export LOGBOOK_NOTION_ROOTS='https://www.notion.so/…/Research-…, …'   # optional: only what is under these
logbook sync notion --dry-run                               # count, write nothing
logbook sync notion                                         # then four times a day with the schedule
logbook sync notion --since 2026-01-01T00:00:00Z            # every page edited since then, once
logbook sync notion --relations-backfill --dry-run          # rows whose relations the record lacks: count
logbook sync notion --relations-backfill                    # then write them, one line a row
```

**The token.** In Notion, *Settings → Connections → Develop or manage integrations → New integration*,
type *Internal*, for your workspace. Under *Capabilities* leave **Read content** on and switch *Update
content*, *Insert content* and the comment capabilities off; for user information choose *Read user
information without email addresses*, which gives the names of the people who edit (without it a line
names them by id). Copy the *Internal Integration Secret* into `LOGBOOK_NOTION_TOKEN` in your shell
profile, never in a file of the record. **Then share the pages**: an integration sees nothing until
you add it to a page. Open each top-level page you want kept (your ideas, research, notes, tasks and
contacts), choose *••• → Connections*, and add the integration; it then reads that page and everything
under it, and nothing else. `LOGBOOK_NOTION_ROOTS` narrows that further to the pages and databases you
name, by id or by the link *Copy link* gives. The sync only reads (`GET`, and `POST` only to Notion's
search, which changes nothing), and a test holds it to that.

**Who acted.** Each line names the person (or the integration) who made the page, for `created`, or
who edited it last, for the other actions, by Notion user id and name, and marks them `owner` or
`other`. Notion does not say which user is you: set `LOGBOOK_NOTION_OWNER_ID` to your user id, or
the sync uses the user who owns the integration when Notion names one, which for an internal
integration it does not. Without either, the lines say who acted and mark no one, and the run lists
the people it saw with their ids, so run `logbook sync notion --dry-run` first and set yours before
anything is written: a line is never rewritten. The owner id marks; it decides nothing else.

| On the line | What it holds |
|---|---|
| `at` | the page's creation time for `created`; its last edit otherwise. The day is the record's own local day |
| `title` | the page's title, verbatim; a database row's name |
| `raw_id` | `<page id>/<day>/<action>`: the dedupe key, so a page edited twice on one day is one line |
| `modified_at` | the page's last edit as the sync saw it, which is also the watermark |
| `extra.action` | `created`, `edited`, `moved` or `archived`; `relations` on a line `--relations-backfill` wrote |
| `extra.page` | the page's `id` and `url` (the private link, which opens only for people the page is shared with) |
| `extra.path`, `extra.parent` | the titles above the page, the top first, as far as the integration can see; the parent's type and id |
| `extra.database` | a database row's database, `{id}`: every line of a row has it, a page that is not a row never |
| `extra.actor` | `id`, `name`, `type` (`person` or `bot`) and `role` (`owner` or `other`) |
| `extra.body` | `sha256` and `bytes` of the page's text, `words`, and `words_delta` since the page's previous line: a digest, never the text |
| `extra.properties` | a database row's status, select, multi-select, date and checkbox values, by name |
| `extra.changed` | each of those that changed since the page's previous line, `{name, old, new}` |
| `extra.relations` | a database row's relation properties, `{name: [page id, …]}`: the ids of the rows it links to, as Notion gives them and in its order, never their titles |
| `extra.relations_changed` | each relation that gained or lost an id since the row's latest line with relations, `{name, added, removed}` |
| `extra.moved_from` | on a move, the parent and path the page had |

**What a line never holds.** The page's text, its comments, its files, its cover or icon, its public
link, anyone's email or avatar, and every property but the few above: no text, number, person, phone,
email, url, file, formula or rollup value, and of a relation only the ids, so a contacts database gives
the names of its pages and none of their details. The digest lets you check a copy of the text against the line; a very short
body could be guessed from it, as from its word count.

**Relations.** A database row's links to other rows — an idea's *Areas*, a task's project — are on the
line that holds the row as it is (the one with the body's digest), as `extra.relations`, one entry per
relation property: `{"Areas": ["<page id>", …]}`, the ids exactly as Notion gives them and in the order
the row has them, an empty list for a relation that links nothing. A reader learns which rows belong
together from the record alone: the sync never looks a related page up, so the line holds no title, body
or rollup of it, and a reader that wants the title reads the related row's own lines. The row's database
is on every line of the row as `extra.database`, so "a row of Notes" needs no question to Notion either.
RFC 0009 has no field for links between entries, so the ids go under `extra`, where the profile keeps
whatever else a source reports. A relation is a change like any other: an edit that only links or
unlinks a row writes its one line, with `extra.relations_changed` saying which relation gained and lost
which ids (a reorder gains and loses nothing); a re-sync of a row nobody touched writes nothing. As for
any change, a relation changed again later on a day whose line is written waits for the row's next line
on another day (or the backfill below), which tells it against the row's latest line with relations.
Notion serves a relation's first 25 links with a page and the rest on request; the sync asks for the
rest, paged, and when it cannot have them all it leaves `relations` off that line and counts the row,
never writing the first 25 as if the others were gone.

**Rows synced before the record kept relations** get them with their next edit. To have them now,
`logbook sync notion --relations-backfill` writes one line per row whose relations the record does not
hold yet — `--dry-run` counts them first, `--since 2026-09-01` takes only the rows edited since that
local day. Each line has `extra.action` `relations`, is dated at the row's last edit (`raw_id` `<page
id>/<day>/relations`) and holds the row's reference, path, parent, database and its relations as the
backfill reads them; no body, property or actor, and it reads no page's blocks. It also catches links
set from the other side of a relation when Notion left this row's edit time alone, saying what changed
(two lines then stand at the row's last edit, and the later in the record's order is the newer); to
compare, it reads every relation of more than 25 links whole on every run, a request per hundred links.
A row the record holds no line of yet is left to the next sync, which writes it with its relations; the
backfill never moves the watermark and never stands in for an edit or a move the sync has yet to write.
It keeps to the same three requests a second and stops on one line when Notion's rate limit does not
lift, the lines already written kept: running it again writes only what is still missing. In the Day a
backfilled row shows once more, at its last edit, as a second Notion entry with its title.

**The tier.** Every line is tier 1: SPEC §4 and RFC 0009 give `event/v1` tier 1, and a Notion line is
an event with a title, a place in a tree and who acted, as a calendar entry is a title, a place and an
organizer. The tier says where a line may travel (tier 1 crosses by default, ADR 0016), never who wrote
it: a line Ola's edit made is tier 1 exactly as one of yours is. A note's own words are tier 2
(RFC 0010); a Notion line holds none, which is why it can be tier 1.

**Which lines.** A run lists the pages edited since the watermark, newest first, by Notion's cursor,
and asks the record what it already holds of each. A page made since the watermark gives `created`
on the day it was made; its last edit gives `archived` when the page is archived or in the trash,
`moved` when its parent is not the one on its previous line, else `edited` — unless the record already
holds the page at that edit. An edit on the day the page was made, seen in the same run, is the
`created` line, which then holds the body and properties. Notion keeps no history the API shows, so a
line records the page as the sync saw it: two edits between two syncs are one, an old → new value is
against the page's previous line, and an edit later on a day that already has its line is not written
again. A page Notion stops listing — deleted for good, or no longer shared — leaves no line.
Notion's API withholds some block types from integrations, such as an AI block: a page that holds
one is still written, with `extra.body` `{"unavailable": "withheld"}` in place of the digest and
word count (`"not_found"` when a block is deleted while the sync reads the page), and the run counts
those pages, names the block type once, never the page, and goes on.

**The watermark** is the newest last-edit time seen (`state/notion.json`); each run reads back two hours
before it, because Notion stamps an edit to the minute and its search lists a fresh edit late, and the
record refuses what it already holds. `--since` reads from an exact time; `--dry-run` counts and writes
nothing. The first run by hand reads every page once, its blocks included, to count its words (a first
scheduled run reads the pages edited in the last 14 days, [the
schedule](schedule.md#a-sources-first-scheduled-run)): at three requests a second a workspace of a few
thousand pages takes a quarter of an hour or more, and says how far it is every hundred pages; later runs
read only what changed. The sync stays under Notion's rate limit — at most three requests a second; a 429
waits as long as Notion's `Retry-After` says, a server error is tried again after 1, 2, 4… seconds — and
when the limit does not lift it stops on one line, exit 1, the watermark where it was, so the next run
carries on. `logbook doctor` lists `sync:notion` once the token is set, by name only, and asks Notion
nothing; `sync --all` and the schedule run it with no more configuration.

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

### GitHub

`logbook sync github` keeps what happened in your repositories — every commit on the default branch,
every issue and pull request created, closed or merged, every review and comment — as one `event/v1`
line each, tier 1 (tier 2 from a private repository, so its text never crosses at tier 1), with the
message, the body or the comment in full, as RFC 0009's `notes` allows, and who acted, marked `owner` by the handles you list in `policy/owner.json`. A pull request an agent
wrote, by the session marker in its body, is `agent: true`, so a page can list what your agents did.
`logbook add github-export DIR` reads an old project's clone or GitHub's account export once: its
commits, and each version of its README and docs as a digest and a word count, so an old project's
ideas have a first-said date; the same commit or issue read both ways is one line. A clone says
nothing of whether its repository is public, so its lines are tier 2 unless you add it with `--public`.

```bash
export LOGBOOK_GITHUB_TOKEN=github_pat_...                  # fine-grained, read-only: Contents, Issues, Pull requests, Metadata
export LOGBOOK_GITHUB_REPOS='ines-example/sailplan'         # owner/name, comma-separated, or --all
logbook sync github --dry-run                               # count, write nothing
logbook sync github                                         # then four times a day with the schedule
logbook add github-export ~/code/oldboat                    # once per old project
```

[docs/adapters/github.md](adapters/github.md) has the whole of it: the token, who acted, the text and
the tier, every field of a line, the watermark per repo and the export.

### Google, on one key

Six sources read your Google account: `sync gmail` (your mail), `sync gcal` (your calendars), `sync drive`
(what happened to your Drive files), `sync gtasks` (your tasks), `sync meet` (your Meet calls) and `sync
gaudit` (your sign-ins); and `people review --from-google` reads your contacts, as names for the review
and never as lines ([the people page](people.md#names-from-google-contacts)). All of them sign in the
same way, with one **service account** of your own Google Workspace that the Workspace allows to act as
you (*domain-wide delegation*), configured by the same two variables, read-only, one scope each. A service
account signs in with a key file and nothing that expires: every run signs a short request with the key
and gets an access token good for an hour, which it keeps in memory for that run and never writes
anywhere. There is no refresh token to go stale in a scheduled job, which is how a sign-in done once in a
browser dies months later. Only you can stop it: by deleting the key or withdrawing the delegation.

| Source | Scope it asks for, read-only | What it covers |
|---|---|---|
| `sync gmail` | `https://www.googleapis.com/auth/gmail.readonly` | every message, as `mail/v1` lines ([the mail page](adapters/mail.md#gmail-over-the-api)) |
| `sync gcal` | `https://www.googleapis.com/auth/calendar.readonly` | the calendars you own, as `event/v1` lines |
| `sync drive` | `https://www.googleapis.com/auth/drive.activity.readonly` | what happened to your files |
| `sync drive` | `https://www.googleapis.com/auth/drive.metadata.readonly` | the folder path each Drive line names |
| `sync drive --videos`, `videos fetch` | `https://www.googleapis.com/auth/drive.metadata.readonly`, and for the fetch `https://www.googleapis.com/auth/drive.readonly` | only for the family's videos: the files of one folder, then their bytes into a bounded cache ([Videos](adapters/videos.md)); not in the list below, add it only if you use them |
| `sync gtasks` | `https://www.googleapis.com/auth/tasks.readonly` | your tasks, each as it stands (`task/v1`) |
| `sync meet` | `https://www.googleapis.com/auth/meetings.space.readonly` | your Meet calls and their transcripts |
| `sync gaudit` | `https://www.googleapis.com/auth/admin.reports.audit.readonly` | your own sign-ins, from the login audit log |
| `people review --from-google` | `https://www.googleapis.com/auth/contacts.readonly` | your contacts, as names for the review |
| `people review --from-google` | `https://www.googleapis.com/auth/contacts.other.readonly` | your other contacts, the same |

**Setting it up**, once, as the Workspace's administrator:

1. In the Google Cloud console, in a project of your own (create one if you have none), open *APIs &
   Services → Library* and enable the **Gmail API**, the **Google Calendar API**, the **Google Drive
   API**, the **Google Drive Activity API**, the **Google Tasks API**, the **Google Meet REST API**, the
   **Admin SDK API** (the audit log) and the **People API** (the contacts): the ones for the sources you
   want.
2. *IAM & Admin → Service accounts → Create service account*. Call it `logbook-sync`; it needs no role
   in the project. Open it and copy its **Unique ID** (the client ID, a long number).
3. On the same page, *Keys → Add key → Create new key → JSON*. The browser downloads one file: that
   file is the key. If the console refuses, the organisation policy *Disable service account key
   creation* (`iam.disableServiceAccountKeyCreation`, on by default in organisations made since 2024)
   is in the way: turn it off for this one project under *IAM & Admin → Organization policies*.
4. In the Workspace admin console, *Security → Access and data control → API controls → Manage
   Domain Wide Delegation → Add new*. Paste the client ID and, as the OAuth scopes, the scopes of the
   table above, comma-separated, all read-only:
   `https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/drive.activity.readonly,https://www.googleapis.com/auth/drive.metadata.readonly,https://www.googleapis.com/auth/tasks.readonly,https://www.googleapis.com/auth/meetings.space.readonly,https://www.googleapis.com/auth/admin.reports.audit.readonly,https://www.googleapis.com/auth/contacts.readonly,https://www.googleapis.com/auth/contacts.other.readonly`.
   Authorize. A new delegation can take a few minutes, sometimes longer, before Google honours it. A
   scope you leave out is a source that cannot run: leave out `gmail.readonly` and `sync gmail` says so
   and exits 1 (switch it off in `policy/import.json` if you mean it); leave out
   `drive.metadata.readonly` and Drive lines carry no folder path, said once per run. A key set up
   before `sync meet` and `sync gaudit` existed has neither scope: `sync --all` then runs both and
   both fail, each on one line, until you add the two scopes here or switch the two sources off in
   `policy/import.json`.
5. Move the key out of your downloads to `~/.config/logbook/google-sa.json` and make it yours alone:
   `chmod 600 ~/.config/logbook/google-sa.json`. **Never commit it**, and never put it in the record's
   folder, a cloud folder, a repository or a message: whoever holds it reads your mail, your calendars,
   your Drive's activity, your tasks, your calls and their transcripts, your sign-ins and your contacts
   for as long as the delegation stands.
6. Name it in the environment, in your shell profile and in `~/.config/logbook/sync.env`, the file the
   schedule reads (docs/schedule.md); the schedule then runs all six with nothing more to set:

   ```
   LOGBOOK_DRIVE_SA_KEY=~/.config/logbook/google-sa.json
   LOGBOOK_DRIVE_USER=ines@example.org
   ```

   (The names say *Drive* because Drive came first; every Google source reads the same two.)
7. `logbook doctor` now shows one `google` line — the key present, the user set, which sources are on
   the key, a source switched off in `policy/import.json` named as disabled, and what `people review
   --from-google` reads on it — and a `sync:<name>` line for each source. It reads the key and checks
   that no one else on the machine can, and asks Google nothing:

   ```
   pass  google       key present, user set; sources on the key: gmail, gcal, drive, gtasks, meet, gaudit; people review --from-google: contacts, other contacts
   ```

`unauthorized_client` means the delegation does not yet grant the scope named in the message (step 4);
`invalid_grant` that the key was deleted, this machine's clock is wrong, or `LOGBOOK_DRIVE_USER` is not a
user of the domain. Signing needs the `crypto` extra (`pip install "openlogbook[crypto]"`); without it a
sync says so. Every request is retried with a doubling wait on a rate limit or a server error, and stops
on one plain line, exit 1, the watermark where it was, when that does not pass. `sync --all` runs the
six in the order mail, gmail, gcal, drive, gtasks, meet, gaudit are registered: `mail` (IMAP) before
`gmail`, so a mailbox you read both ways is written once by whichever comes first.

### Gmail

`logbook sync gmail` reads your mailbox over the Gmail API with the key above, and writes exactly the
line `logbook sync mail` (IMAP) writes for the same message: the same parser, the same fields, the same
dedupe key, the account and the `Message-ID`. A mailbox you synced over IMAP yesterday and over the API
today is written once. The mail page has what a line holds, what is left out (drafts, Spam, Trash) and
when to use which ([Gmail over the API](adapters/mail.md#gmail-over-the-api)).

```bash
logbook sync gmail --dry-run                               # counts, nothing written
logbook sync gmail --since 2026-01-01T00:00:00Z            # a first run from a day you choose
logbook sync gmail                                         # then from Gmail's history id
```

A first run by hand without `--since` lists every message; the first scheduled run reads the last 14 days
and leaves its mark there ([the schedule](schedule.md#a-sources-first-scheduled-run)).

### Google Calendar

`logbook sync gcal` reads the calendars you own. With the two variables above set it reads them over
the Calendar API (`calendar.readonly`): every calendar whose owner you are, your primary first, never
one shared with you or a subscribed one such as a holidays calendar. Without them it reads the private
iCal addresses you list (Google Calendar → Settings → the calendar → *Integrate calendar* → *Secret
address in iCal format*), one whole calendar per URL; with both, the key wins and the URLs are not read.
Either way each event goes through the reader `logbook add` uses for an `.ics` export, so a calendar
you imported from a Takeout or settings-page export, the same calendar pulled by URL and the same
calendar read over the API are one line per event (same `raw_id`, the event's UID and last-modified
time; ADR 0017). The API has no field for an event's GEO coordinates or an attendee's *delegated*
answer, so a line read over the API lacks those two where a feed had them; the record keeps the line it
has. The watermark is the newest last-modified time seen; each run keeps the events changed in the 24
hours before it (`LOGBOOK_GCAL_LOOKBACK_H`) and reports, per calendar, how many it saw and how many were
new. A calendar that fails (an expired secret address is a 404) is one line on stderr, the others are
still written, the watermark stays put and the exit is 1. A first scheduled run keeps the events changed
in the last 14 days ([the schedule](schedule.md#a-sources-first-scheduled-run)); an event planned long
ago and unchanged since comes in with `--since`.

```bash
export LOGBOOK_GCAL_URLS='Sailing=https://calendar.google.com/calendar/ical/…/private-…/basic.ics,https://…'
logbook sync gcal --dry-run                                # counts per calendar, nothing written
logbook sync gcal
```

**Moving from the feeds to the key.** Set the two variables and run `sync gcal` as before; nothing else
changes. The watermark in `state/gcal.json` is the same clock either way (the API's `updated` time is
the feed's `LAST-MODIFIED`), so the first run on the key carries on from where the feeds stopped, less
the lookback, and writes nothing twice: the events it reads again are already in the record by their
`raw_id`. You can then delete `LOGBOOK_GCAL_URLS`, and reset the secret addresses in Google Calendar,
since nothing reads them any more.

### Google Drive

`logbook sync drive` writes down what happened to your Drive files each day: created, edited, renamed,
moved, shared, commented on, trashed, deleted, restored. It reads the Drive Activity API, read-only, as
you, with the key of [Google, on one key](#google-on-one-key).

```bash
logbook sync drive --dry-run                               # counts per activity, nothing written
logbook sync drive --since 2026-01-01T00:00:00Z            # a first run from a day you choose
logbook sync drive                                         # then from where it left off
```

A first run by hand without `--since` reads all the activity Google keeps. The first scheduled run reads
the last 14 days ([the schedule](schedule.md#a-sources-first-scheduled-run)), and a dry run that meets
the project's daily quota stops on one line instead of waiting it out.

The family's videos, the digitised tapes in one Drive folder, are a source of their own on the same key:
`sync drive --videos` with `LOGBOOK_DRIVE_VIDEOS_FOLDER` set to the folder's id, then `videos fetch`,
`videos infer` and `review videos` ([Videos](adapters/videos.md)).

**What a line holds.** One `event/v1` line per file, per hour and per kind of activity, so an afternoon
of editing is a handful of lines with a count, `Edited Budget 2027 ×14`, not hundreds. It holds the
file's name, its type, its id and a link that opens it in Drive; the folders it is in, root first
(`["My Drive", "Boat"]`), read with the metadata scope, each folder's name asked once and kept in
`state/drive-cache.json` for a week (never in the record) and asked again when an activity renames or
moves it; who acted, you as `owner` and anyone else as Google names them (`people/…`, a person's
account, not their address); for a share, with whom (a person's `people/…` name, a group's address, a
domain, or anyone with the link) and the role; for a move, the folder it went to and came from; for a
rename, the old name and the new. An hour is written once it is over, so a run at 07:00 leaves
06:00–07:00 for the next. Someone else's activity on someone else's file that was shared with you is
left out and counted.

**What a line never holds.** The file's content, a comment's words, the file's size or modified time.
The path is where the file is when its line is written; a line already in the record is never
rewritten, so lines written before the metadata scope was delegated keep no path. Lines are **tier
1**, like calendar entries, whoever acted: the tier says where a line may travel, and a file's name and
what happened to it are the same fact whoever did it.

### Google Tasks

`logbook sync gtasks` reads your Google Tasks, read-only, with the key of [Google, on one
key](#google-on-one-key) (the Tasks scope in step 4). A task is an idea or a promise you made yourself;
the record keeps each one as it stands, the way a Takeout export of your tasks would, and `logbook
tasks` reads them back.

```bash
logbook sync gtasks --dry-run                              # counts per list, nothing written
logbook sync gtasks
```

**What a line holds.** One `task/v1` line (RFC 0016) per task as it stands: its title in your own
words, `open` or `done`, its list, its due day if it has one, its parent for a subtask, and when it was
done. Google keeps no creation time, so a line is dated when the task last changed, which for a task
captured and left alone is when you wrote it down, and for one ticked off is when you ticked it. A task
that changes — ticked off, renamed, reopened, deleted — is a new line beside the old one, which it
supersedes; an unchanged task writes nothing, and nothing is ever rewritten. A done task says how long it
was open, from the first time the record saw it open (unknown when it never did). It is the line the
Takeout Tasks adapter writes for the same task, with the same `source` (`google-takeout`) and the same
`raw_id`, so a Takeout export imported later adds nothing `sync` already wrote, and a `sync` after an
export carries on where it ended.

**What a line never holds.** The task's notes: only their digest and how many words they have. Lines
are **tier 2**, as RFC 0016 makes every task: sealed at rest when the record seals, and crossing only
after review.

### Google Meet

`logbook sync meet` writes down the Meet calls you were in, read from the Meet REST API with the key
of [Google, on one key](#google-on-one-key) (`meetings.space.readonly`, read-only, as you).

```bash
logbook sync meet --dry-run                                # counts, nothing written
logbook sync meet --since 2026-09-01T00:00:00Z             # a first run from a day you choose
logbook sync meet                                          # then from where it left off
```

A first run by hand without `--since` reads every call Meet keeps; the first scheduled run reads the last
14 days ([the schedule](schedule.md#a-sources-first-scheduled-run)).

**The call.** One `event/v1` line per call, once it has ended (a call still going on is counted and
written by the next run): when it started and ended, and who joined as Meet names them — a signed-in
participant is a Google account, `users/…`, kept as an attendee (never turned into a name here:
`people review` sees them, and so does a review with your contacts), a guest by the name they typed, a
caller by the number Meet shows, partly hidden. Meet keeps no title for a call, so the line is titled
by its meeting code, `Meet abc-mnop-xyz`; the calendar entry you planned it in is a line of its own,
from `sync gcal`. The conference record's name (`conferenceRecords/…`) is the line's reference back.
Lines are **tier 1**, like the calendar's.

**The transcript.** When Meet transcribed the call, one `transcript/v1` line more, built exactly as a
Granola recording's is — the same mapping, the same profile, **tier 3**: who spoke, how many turns,
the language, a link to the transcript's Google Doc, and the words themselves in `attachments/`,
named by their digest, never in the line. A call transcribed in several sittings is one line. Google
finishes a transcript a while after the call; until it has, the call is written without it and the
transcript comes with a later run.

**Granola too?** If Granola also recorded the call, its transcript stays a line of its own beside
Meet's. They are two transcripts, by two providers, with their own words, speakers and ids; that
they are of one call is for a reader to see from the times, not for a source to decide by joining
them.

Each call is keyed by its conference record (`meet:<id>`, and `meet:<id>:transcript`), so a re-run
writes nothing twice, and a call already in the record is not asked about again. The watermark is the
newest call's start; each run looks back a day before it, for a call that ended or a transcript Google
finished since.

### Google sign-ins

`logbook sync gaudit` writes down your own sign-ins to your Google Workspace, from its login audit log
(the Admin SDK Reports API, `admin.reports.audit.readonly`, with the key of [Google, on one
key](#google-on-one-key)). It asks for your sign-ins only, never the other users of the Workspace;
Google answers it only for an administrator, which you are of your own Workspace.

```bash
logbook sync gaudit --dry-run                              # counts per kind of sign-in, nothing written
logbook sync gaudit
```

**What a line holds.** One `event/v1` line per sign-in event, **tier 1**: when, what happened
(`Signed in`, `Sign-in failed`, `Signed out`, `Sign-in challenge`, …), how (`login_type`, the
challenges asked and how they went, why one failed, whether Google thought it suspicious), and where,
as Google derived it from the address: a country, a subdivision and, when the log says one, a city
(`Oslo, NO-03, NO`).

**What a line never holds: the address.** The IP address a sign-in came from is never written — not in
the line, not in its key, not as a digest, since a digest of an address hides nothing (there are only
four billion of them to try) — and neither is the network it came through. What may travel with a
line is the place Google made of the address, coarse, never a coordinate. (A Takeout export's *Access
Log Activity* is another file, every access to every service, read by the `google-takeout-access-log`
adapter, off by default.)

Each event is keyed by the log's own id for it, so a re-run writes nothing twice; each run looks back
a day before the newest sign-in seen, since Google can add one to the log hours later.

Your boat, your aircraft and your car are *subjects* with tracks of their own, not places (ADR 0018). Register
each once in `assets.json`, then let `sync` ask the receivers that hear them:

```bash
logbook assets add solvind --kind yacht --name Solvind --mmsi 999000001        # synthetic MMSI; use your own
logbook assets add ln-zz1 --kind aircraft --name "the club's Cub" --icao24 000a01 --registration ZZ-ZZ1
logbook assets list
logbook assets status                                       # where each one last was, and how old that fix is
export LOGBOOK_AISSTREAM_KEY=...                            # free key from aisstream.io
uv sync --extra ais                                         # or: pip install 'openlogbook[ais]'
logbook sync ais --dry-run                                  # listen for 60 s, count, write nothing
logbook sync ais                                            # then: */10 * * * * logbook sync ais
logbook sync ais --listen 3600                              # or: one long sitting, written at the end
logbook sync ais --until 18:30                              # … until the record's clock next shows 18:30
logbook sync adsb                                           # OpenSky, no key needed; LOGBOOK_OPENSKY_USER/PASS optional
```

Each position is a `location/v1` line like your own, with `subject` set to the asset's id and `raw_id` from the
receiver, the identifier and the fix time (`aisstream:<mmsi>:<unix seconds>`, `opensky:<icao24>:<unix seconds>`),
so a report heard twice is one line, and a stream you saved to a file (`logbook add messages.jsonl`) and the same
reports heard live are one line too. `state/ais.json` and `state/adsb.json` keep a watermark per asset. `show`
lists the boat's points as their own run, named by the asset; whether you were aboard is for an engine to decide
from the two tracks, never written on a line. `sync ais` listens for `--listen SECONDS`, or `--until HH:MM` (the
record's local time, the next time the clock shows it), or else `LOGBOOK_AISSTREAM_LISTEN_S` (default 60 s; a
vessel under way reports every few seconds), and writes at the end; while it listens it prints one line a minute
with the messages heard per asset, reconnects with a wait that doubles from 1 s to 60 s when the socket drops,
and on Ctrl-C still writes what it heard, then exits 130. The key is read from `LOGBOOK_AISSTREAM_KEY` only and
never printed. OpenSky's `states/all` is the present, one fix per aircraft per poll, so poll as often as its
rate limit allows.

**A secret iCal address is the whole calendar** to anyone who holds it; Google can reset it. Keep the
URLs in the shell environment only, as the Dawarich key below: the logbook never prints one, naming a
calendar by its name or by eight characters of the URL's hash.

**A Dawarich API key is full access** to your account: it can read and delete every point you have.
Keep it in the shell environment only (your shell profile, a password manager's CLI, a secrets file
outside the record) and never in the record, the repository or a script you share. The logbook sends it
only in the `Authorization` header and never prints it.

**Is every source still flowing?** `logbook sources --gaps` reads the index alone, never the files, and
prints one row per source with lines: how many, its last line's time, the longest silent stretch (between two
lines, or since the last one, still running) and the days with no line from it, folded into runs, so a phone
that stopped sending or a sync that died is seen on one screen. The range runs from each source's first line
to today in the record's zone, or from `--since YYYY-MM-DD`; a line dated after today (a calendar's future
entries) is outside it, and today counts as a missing day only once the source has been silent a full day.
`--expect dawarich imessage` shows only those sources, marks one that has been silent a day or more at any
point of the range, or has no line at all, with `!`, and exits 1 when any is marked, so a cron job can tell
you: `0 7 * * * logbook sources --gaps --since 2026-09-01 --expect dawarich imessage`. Every line counts,
retracted or not; `--json` gives the same report as data.

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
An event counts when it happened somewhere — a calendar entry, Google Home's door, an event with a
location or attendees — and a Notion or Drive edit does not. Evidence promotes; duration is the fallback. A shorter span with nothing attached is a stop, kept and
flagged. A move is what lies between: its distance along the points, its duration, and a mode from the
speed (walk, car, train, flight; flight also when a gap starts and ends near airports). The night of each
day is the longest stay between 22:00 and 08:00; a night with none is in transit.

A tracker such as Dawarich sends no points while you are still, so a silence is read as time at the place:
a gap whose next point is back inside the stay's radius continues the stay however long it was, and a stay
lasts until the tracker's next point when that point comes after a silence and lies within a short walk
(1.2 km by default) — even when it is the next morning and already on your way out, so the night at home is
seen. In `policy/stays.json`, `merge_gap_s` (600 s by default) governs an excursion, not a gap at the same
place: step outside the radius and come back within it and the stay is one; come back later and it is two
stays with a move between. A gap of `merge_gap_s` or more is a silence, and `walk_max_kmh` for `merge_gap_s`
is the hop a silence may end with and still count as time at the place. An asset registered in
`assets.json` (ADR 0018) gets its own stays and moves; when its position lies within the radius of yours for
`aboard_min_s` (20 minutes) or longer you are aboard it, and the run of your stays and moves aboard it is one
stay `aboard <asset>` with the run inside it, so the asset's movement never fragments your stay
([docs/day.md](day.md), *Aboard an asset*). A night aboard names the asset and carries its position.

## The Day

`logbook day 2026-06-13` is the day read back whole ([docs/day.md](day.md)): the night before and the night
after (home, away or in transit), the country of the day, the timeline of stays, stops, moves and flights with what
attached to each (events, transcripts, notes, mail threads, calls, keepers named; messages and photos counted) and who
was there — confirmed by a note, a transcript or a timed calendar entry; proposed by a face or an all-day entry —
then what the calendar planned where the track has nothing, the night's sleep, the day's steps and resting heart rate,
and which sources spoke and when they last did. A run of stays and moves aboard a boat or an aircraft is one stay
`aboard <asset>` with the anchorages inside it; a silence of the tracker is a `gap` row that places nothing. `--json`
gives the Day as one object, every row with the ids of its lines. Nothing is written.

A **story** someone told — "in 1961 we moved to the house by the lake" — is a line on the day it was told, never on the
day it is about (`add story <file> --teller <ref> --listener <ref> --refers-to 1961`, RFC 0028, a draft). `show` prints
it on its told day as `📖 refers to 1961 — told by Ola Nordmann to Kari Nordmann`; `day 1961-05-04` lists it under
*Stories about this day*, apart from the timeline, because a told year is a claim and the timeline is what was observed.

## In a browser

`logbook serve` is the record read in a browser, on this machine only ([docs/serve.md](serve.md)): the Day as a
timeline with each row's attachments under a toggle (`/day/2026-06-17`), a window one row per day (`/days`), the trips of
a year (`/trips`), the places, the assets with their last fix, and where each source went quiet — the same readers as the
commands, rendered as HTML with one inline stylesheet and no script, nothing fetched from anywhere. The server binds
`127.0.0.1` and refuses any other host; no page references a URL outside itself; nothing is written.

```bash
logbook serve                                 # http://127.0.0.1:8765/
```

## Reading the record

The readers above the day page derive, and never append: every one of them is a function of the record at its
head, and the same record reads the same way twice. The only lines they ever add are the captain's own namings.

```bash
logbook places propose                        # unnamed stays ranked by hours, with the nearest known place and a suggested name
logbook places propose --write                # name the ones you accept: places.json, and one note/v1 line each
logbook places add Home --lat 59.9139 --lon 10.7522 --kind home
logbook places name 59.92,10.74 Cafe          # or a stay id from `propose`; the naming is a note in the record

logbook rollup countries --year 2026          # days per country from the overnight stay; in transit apart
logbook rollup flights                        # count, km, long-haul, by evidence, from the flight lines standing
logbook rollup nights                         # home, away, in transit, nights aboard, the longest trip
logbook rollup places                         # nights, stays, hours, people per named place and asset; the top unnamed clusters
logbook rollup places --with                  # the place × person table: stays, days and nights at each place per person
logbook rollup people                         # days and nights together, last real contact, places shared, per person
logbook rollup health --by week               # sleep, steps, resting heart rate, HRV per month or ISO week; — when missing
logbook rollup listen --year 2026             # listens, hours, skips, the top artists by hours, hours by month, from every listen/v1 line
logbook rollup attention --year 2026          # hours by app and by category (communication, browser, media, work, other) from Screen Time
logbook rollup money --year 2026              # the transactions by month, by country of the stay, by the source's category

logbook trips --year 2026                     # runs of nights away: route, places, people, flights in and out
logbook ledger --month 2026-06                # the transactions at the stay and in the trip, per day; shares per person
logbook year 2026 --html ~/2026.html          # the year read back: the rollups, the trips, one day a month; a page that prints
logbook trip trip:2026-06-15:2026-06-20       # one trip: the route as stays with a map, days, flights, people, keepers, health, spend
logbook year 2026 --html ~/2026.html --print  # the paper edition: a cover, contents, a spread a month with the keepers as hero photos; A4 or Letter
logbook trip trip:2026-06-15:2026-06-20 --html ~/week.html --print  # the same for one trip, a spread a day; docs/print.md says how to make the PDF
logbook export trip-bundle trip:2026-06-15:2026-06-20 --to kari --tier 1,2   # that trip for a member of the circle; `import trip-bundle` takes one in
logbook show person "Kari Nordmann"           # first and last contact, days together, places, the last shared stays
logbook show asset solvind                    # trips aboard, nights, people, the track's summary
logbook show place Office                     # visits, people, photos
logbook people --year 2026                    # everyone the record names: channels, days and nights together, last real contact
logbook person ola@example.org                # one page: the numbers, then the shared days, most recent first
logbook people merge                          # the same person named twice: proposals with the evidence; --apply ID merges
logbook search '"with kari"' --since 2026-06-01   # full-text, literal, ranked, by day: notes, messages, mail, events, transcripts

logbook infer keepers                         # favourites → keeper/v1 (memory); the Art album → keeper/v1 (art)
logbook keepers --since 2026-06-01 --lane art
logbook keepers --people                      # who appears on the keepers, per month: the faces the library named, proposed
logbook describe keepers --photos ~/Pictures/Photos\ Library.photoslibrary   # a local vision model's sentence per keeper photo (openlogbook[describe]); never a name, never a place

logbook promises --judge                      # a local model reads every "I'll…" the rules found; the commitments, as proposals
logbook promises --all --since 2026-06-01     # every candidate the rules found, judged or not
logbook promises done 3b9e5d0f2a71c846        # it was kept: one task/v1 line, so --open hides it

logbook tasks --open                          # the task/v1 lines as they stand: the latest snapshot of each
logbook tasks --propose-done                  # the mail, calendar entry or transaction that says an open task was done
logbook tasks done 0dd9108fb6d5d715 --evidence 01a0fda3-99b0-7af6-a986-0a377117a94b   # one task/v1 line, done

logbook digest                                # today in 25 lines at most, with one question you answer in a word
logbook digest 2026-06-10 --markdown          # the same lines as Markdown; --json the sets behind them
```

Every command takes `--json`, and under `--json` every number carries the ids of the lines it came from: a stay
by its first and last location line (one unbroken run of points), a flight by the flight line standing, a person
by the lines that put them there. The rollups are described in [docs/rollups.md](rollups.md). The ledger, the transactions in context, in [docs/ledger.md](ledger.md). A home region is a place of kind `home` in `places.json`; a night whose stay
is within 400 m of one is a night at home whatever that place's radius, so a trip never starts or ends with the
guest room across the street. Without a home place no night is home, there are no trips, and the commands say so.

**Who was there.** A stay's company comes from the record's own evidence: an attendee of a timed calendar entry
held at the stay (its location geocodes within a kilometre of the stay — coordinates on the entry, or a
location that names a place in `places.json` — or it has no location and overlaps the stay by more than an
hour; an all-day entry places nobody), a participant of a transcript recorded inside it whom the record
resolves to a person (`Speaker A`, `me` and `Unknown` are nobody), a note written inside it that says
`with <name>` — all confirmed — and a face the photo library tagged, proposed only. Names resolve through the
record's resolution lines (RFC 0006); a bare address nobody has named and a calendar system address
(`calendar.google.com`, `noreply`, `reservations@`, `invite@`) are dropped. You are never your own company:
the with module knows you by `owner_id` and `owner_emails` in `logbook.json`, by every resolution line that
names those, and by `policy/owner.json`, `{"names": [...], "emails": [...], "phones": [...], "handles":
[...]}`, where your other spellings and your logins go; `init` writes it empty. `trips` lists at most twelve names, most evidence first.

**Countries, coarsely.** `rollup countries` has no map. The country of a night is the one a place in
`places.json` carries (`country`, your word), else the nearest large airport within 300 km and the country its
zone is filed under in the bundled `zone.tab`. That is wrong near borders and far from airports, and the method
is printed with the numbers; name the place and give it a country when it matters.

**Trips are derived, never written** (ADR 0019). A trip is a run of consecutive days whose overnight stay is
outside every home region, recomputed every time; a trip's name, when you give one, is a note (`logbook add
--trip ID "NAME"`, or the field on its page in `serve`). Its route is
the night places in order: the named place, else an airport's code and city (`ZRH, Zurich`) when the stay is at
one — within 3.5 km of the reference point of an airport with scheduled traffic (OurAirports type large or
medium; a terminal often lies well off the runway midpoint the row marks), within 2 km of any other row — else
the coordinates with `near <place>, x km` for a named place within 5 km, else the coordinates with the city of
the nearest large airport within 30 km in parentheses (`53.5998,10.0130 (Hamburg)`; the city, never the
airport's code); consecutive points within 200 m of each other are one. `logbook day` labels an unnamed stay the
same way.

**Keepers** (RFC 0024) are the photos you marked: a favourite in the library is a `memory`, a photo in an album
named Art is `art`. `add photos` writes them with the photo lines, and `infer keepers` reads the marks out of any
library's photo lines once; `show <day>` lists the day's keepers first, as its hero photos. `keepers --people` is
who appears on them per month, from the names your library gave its faces — proposed, never confirmed; a face's
name is a person only when it is exactly a label a resolution line carries (`docs/adapters/photos.md`). `describe keepers`
(`docs/describe.md`) has a local vision model (`openlogbook[describe]`, mlx-vlm on Apple silicon) write one factual
sentence and the visible things for each keeper whose file is reachable, as a derived note on the photo's day,
once per photo; it is never told who is in the picture or where it was taken and may not guess either.

**Promises** (`docs/promises.md`) are proposals, never facts: every sentence of a transcript or a note that reads
as a first-person future or obligation, in English or German (`I'll send`, `we'll get back`, `let me`, `I need to`,
`ich schicke`, `ich melde mich`, `ich muss`), with the day, the line, the speaker when the record resolves one and a
due hint when a date phrase is in it (`by Friday`, `next week`, `bis Montag`), found by rules. The rules find far
too many, so `--judge` has a local instruct model (`openlogbook[judge]`, mlx-lm on Apple silicon, a 4-bit
Qwen2.5 by default) read each candidate in its context and say whether it is a commitment, by whom, to whom,
what and by when; the verdicts are kept in the record and never redone, and the command shows the commitments
it is sure of (`--all` for everything). No model runs unless you ask, never a cloud one, and nothing leaves the
machine. `promises done <id>` is the one thing it writes: a `task/v1` line marked done.

**Tasks** (`docs/tasks.md`) are the `task/v1` lines a task app's export left, each as its latest snapshot (RFC 0016);
`tasks --propose-done` asks the record whether an open one was done without anyone ticking it off: within the
fortnight after the task, a mail subject that names its key nouns and confirms something (a booking confirmation
for "book flights to Zürich"), a calendar entry for an appointment ("Call with Ola" for "call Ola"), a transaction
at a merchant the task names — by rules, English and German, no model, no network — each a proposal with the
evidence line's id. `tasks done <id> --evidence <line>` appends the closing `task/v1` line and nothing else. The
matcher is a value, so the promises judge's engine can replace the rules later without changing the report.

**The digest** (`docs/digest.md`) is the day in 25 lines at most, composed from the readers above and never a
list of everything: where, with whom confirmed, what attached; the flights; the open promises due within the week;
the usual sources with no line; tomorrow's timed calendar entries; and one closing question you can answer in a
word, so the day closes itself (ADR 0005). It writes nothing and sends nothing; delivery is a later decision.

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

## Handing a day to a friend

A shared page (RFC 0025, `docs/rfcs/rfc-0025-shared-page-bundle.md`) is one day of your record for one person
in your circle, as one signed zip: the day's lines verbatim, the attachments they point at, the day-package
summary, and a manifest signed with your record's sharing key — made the first time you share, kept at
`~/.config/logbook/share/<owner_id>.key`, its public half in `logbook.json` as `share_key`. The other side
verifies the signature under the key they hold for you, recomputes every line's hash, and keeps the page beside
their record, never in it.

```bash
logbook circle key                                   # your public key; give it to Ola
logbook circle add ola 5df798a3…                     # Ola's, once; policy/circle.json
logbook share day 2026-06-13 --to ola                # tier 1, under the ceiling policy/crossing.json gives ola
logbook share day 2026-06-13 --to ola --tier 2 --out ~/Desktop/saturday.zip
logbook receive ~/Downloads/saturday.zip             # Ola's side: verified, then circle/ines/2026-06-13/
logbook day 2026-06-13                               # … and the Day ends with a `from ines` section
```

The same ceiling as a crossing applies, per destination, and a page is a crossing: every share appends one
`crossing/v1` line, so the record shows each day that left it. A page that fails any check — the signature, a
line's hash, a file the manifest does not name — is refused with the check named and nothing of it is kept.
The two pages under `tests/fixtures/share/` are the fixture a second implementation reads.

## Opening it in Obsidian

`logbook export vault ~/Vault` renders the record as a folder of plain Markdown with wikilinks — a page per
day, place, person, trip and year — that Obsidian or Logseq opens as a vault, its graph view the record's
shape ([docs/vault.md](vault.md)). It is tier-gated exactly like a crossing: tier 1 by default, the shape of
every day and no text of any note or message; `--tier 1,2` when `policy/crossing.json` names `vault` with a
ceiling of 2. Every run appends one `crossing/v1` line, and re-running rewrites only the files that changed.

## Asking an agent

`logbook mcp` serves the record to an agent on this machine over the Model Context Protocol, on this
process's stdin and stdout and nothing else: no port, no socket. The host starts it, and the tools are the
readers above — `day`, `days`, `trips`, `places`, `people`, `person`, `promises`, `gaps`, and a `search` over
the index — plus two that write through `Logbook.append` and nothing else: `add_note` (one `note/v1` line, as
`logbook add`) and `promise_done` (one `task/v1` line, as `logbook promises done`).

```bash
pip install "openlogbook[mcp]"                # the official Python MCP SDK
logbook mcp --inspect                         # the tool table and a sample request; no record needed
logbook mcp                                   # what a host runs; LOGBOOK_HOME or --root names the record
```

Every answer passes the crossing gate of ADR 0016: `policy/crossing.json` names the `mcp` destination and its
ceiling, 1 unless you raise it, and the answer says how many lines sat above it and were left out
(`gate.withheld`). At 1 the agent sees the record's shape and no note, message or name; at 2 your notes and
your circle too; tier 3 only when the file allows it *and* you start the server with `--allow-tier-3`.
[docs/mcp.md](mcp.md) has the host's config snippet and the tools.

