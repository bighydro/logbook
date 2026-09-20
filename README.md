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
logbook verify                  # the chain is intact
```

Docker: `docker build -t logbook . && docker run --rm -v ~/Logbook:/data logbook show today` — the image keeps the record in the `/data` volume (`LOGBOOK_HOME=/data`).

Nix: `nix run github:bighydro/logbook -- --version`, or `nix develop` in a clone for a shell with Python 3.12 and uv.

That is the whole product. Everything else is a layer somebody plugs in.

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
  state/            where each live source left off. bookkeeping, not the record.
```

Nothing here needs the app to make sense. Open the files in any editor twenty years from now.

If you also keep a clone of this repository, set `LOGBOOK_HOME` to your record's folder and pass that path to `logbook init`. On a case-insensitive disk (macOS by default) `~/Logbook` and a clone named `~/logbook` are the same folder; `init` refuses a folder that contains `pyproject.toml`, `.git` or `logbook/__init__.py`, and the CLI never picks such a folder as your record.

## Sources

Two ways in. `add` reads a file you already hold; `sync` asks a service you run for what is new.

```bash
logbook add ~/Downloads/dawarich-export.json      # any export the adapters recognise, or a folder
logbook add ~/Takeout/"Location History (Timeline)"/Records.json   # Google Takeout; Timeline.json works too
logbook add ~/backup/31bb7ba8914766d4ba40d6dfb6113c8b614be442   # iOS Contacts from an unencrypted Finder/iTunes backup
logbook add ~/backup/7c7fba66680ef796b916b067077cc246adacf01d   # WhatsApp (iOS) ChatStorage.sqlite from the same backup
logbook add ~/backup/4f98687d8ab0d6d1a371110e6b7300f6e465bef2   # Apple Notes NoteStore.sqlite from the same backup
logbook add ~/backup/2041457d5fe04d39d0ab481178355df6781e6858   # iOS Calendar.sqlitedb from the same backup
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
every phone number and email address points at it. Set `LOGBOOK_DIAL_PREFIX` (for example `41`) so numbers
saved without a country code get one, with the national trunk `0` dropped (`079 654 31 17` becomes
`+41796543117`); a number that already starts with the prefix digits but no `+`, or any number when the
variable is unset, is kept as entered and flagged `unnormalised`.

WhatsApp messages become `message/v1` lines (RFC 0008), one per message, with the sender as the same kind of
phone ref, so one resolution of a number covers the address book and the chats. Media files are not copied
into the record yet: a file found under `Message/` beside the database is hashed and its digest kept under
`extra.media` for a later attach pass; set `LOGBOOK_WHATSAPP_HASH_MEDIA=0` to skip the hashing on a large store.

Apple Notes become `note/v1` lines (RFC 0010), one per note, with the plain text pulled out of the note archive,
the title, the folder and the modification time. A note edited since the last import is a new line (its `raw_id`
carries the modification time); password-protected notes are skipped because their body is encrypted; notes in
Recently Deleted are logged and flagged `deleted`.

Calendar entries become `event/v1` lines (RFC 0009), one per entry as the phone stores it: the span, the
calendar, the place, the organizer and attendees as email refs, the status; a recurring entry is one line
carrying its rule as RRULE text and a moved occurrence points back at it — occurrences are never expanded.
An all-day entry is placed at local midnight in your record's timezone. The store's placeholder rows (a
start before 1900, such as 1601) are skipped and counted; a birthday from 1965 is kept.

`show` prints people by name — the sender of a message, the organizer and attendees of an event — and the
names come from your own resolution lines, never from the raw lines: import your contacts to get them. The last unretracted resolution of a ref wins (RFC 0006); a ref
nobody has resolved shows as the source gave it, after the name the source itself attached, if any.
`show --raw` prints every ref unchanged. Either way, `show` only reads.

| Source | Variables | What it logs |
|---|---|---|
| `immich` | `LOGBOOK_IMMICH_URL`, `LOGBOOK_IMMICH_KEY` | one `photo/v1` line per asset: capture time, camera, place, size, faces as person ids, never the pixels |

Create the Immich key under *Account settings → API keys* with only the **asset.read** permission.
The logbook only ever reads; a key that cannot write is a key that cannot do harm if it leaks.

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
- [CONTRIBUTING.md](CONTRIBUTING.md) — the easiest thing to build is an adapter for the export you have

## Status

v0.1 — the format, the CLI (init, add, show, verify, export) and the conformance fixture. Engines (days, trips, people) and the circle (sharing) are the next layers; see the roadmap.

Apache-2.0 for code. The specification is CC0.
