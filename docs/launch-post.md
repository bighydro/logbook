# Your life in a folder

*The post for Show HN, Lobsters and r/selfhosted. Everything in it is synthetic: the person lives in Oslo and does not exist.*

---

Logbook is a folder of plain files that records what happened to you. Your phone, your photos, your calendar, your messages and your health data already write it down somewhere; Logbook writes it down once more, in one place you hold, and reads it back to you as days.

The folder is the product. There is no server, no account, no app you have to keep.

## Three lines

```bash
pipx install openlogbook
logbook demo --out ~/Demo/Logbook && export LOGBOOK_HOME=~/Demo/Logbook
logbook day 2026-06-17
```

`demo` writes a month of a person who does not exist: twelve thousand lines of location, health, calendar, messages, photos and flights, from a seed. `day` reads one of those days back:

```
2026-06-17  Wednesday
  country       NO (nearest airport TRF)

  00:00–24:00  aboard Nordlys (yacht) · 24 h · 1 note, 1 message, 1 photo
      00:00–08:55  stay   59.4300,10.4800 (Sandefjord) · 8 h 55 min
      08:55–14:00  move   49.4 km · 5 h 5 min · boat
      14:00–24:00  stay   59.0500,10.0300 (Sandefjord) · 10 h
      note         Anchored by nine. Grilled.
      with         proposed Anders Vik (photo)

  health        sleep 6.7 h · 6,602 steps · resting 56 bpm
```

Then `logbook trips`, `logbook rollup countries`, `logbook year 2026 --html` and `logbook verify`. Five minutes of that is in [Try it](try-it.md). Your own record starts with `logbook init` and `logbook add ~/Downloads/takeout.zip`.

## The file is the format

The record is one JSON line per observation, one file per month, hash-chained: each line carries the SHA-256 of the one before, and `logbook.json` names the head. The whole format is one page, [SPEC.md](SPEC.md), licensed CC0, with a conformance fixture and an expected head. Two independent implementations, this one in Python and [logbook-ts](https://github.com/bighydro/logbook-ts) in TypeScript, written clean-room from the spec, reproduce that head and agree on a record the other wrote.

That is the argument. A diary app is a database behind a user interface, and the database is the app's; when the app goes, so does the diary. Here the files come first: no database is needed to read, verify or export a record, and `index.sqlite` is a cache you can delete. A format that fits in an afternoon will still be readable in twenty years.

Nothing in the record is ever edited or deleted. A correction is a new line that names the line it corrects. A line you want hidden is a retraction, which readers mark and never drop. A broken chain is an error, never repaired silently.

Everything above the record is derived and disposable: stays, moves, trips, who was there, computed from the lines every time and never written back. Your own words are the one thing a reader adds, as lines of their own.

## What it refuses to do

**No cloud.** There is no server in this project and none is planned. The record lives in a local folder, and the README tells you not to put it in one that iCloud or Dropbox syncs. `logbook serve` binds `127.0.0.1` and refuses any other host. Live sources, a Dawarich or Immich instance you run, a calendar feed, are pulled by you, with keys kept in your shell and never printed.

**No model by default.** Every reader is rules, and the rules are in the repository. Two commands can ask a language model, and both run a local one, offline, only when you ask: `transcribe` for voice memos and `promises --judge` for the sentences that read as commitments. No cloud model, ever.

**Tiers.** Every line carries a tier. Tier 1 is location, photo metadata, calendar, public activity. Tier 2 is notes, messages, mail, browsing: other people's words and your own. Tier 3 is money and health, and an import option cannot lower it. Nothing leaves without a named recipient and the ceiling you set for them in `policy/crossing.json`; tier 3 crosses only when the file allows it and you type it out. Every export appends a line to the chain saying what left and to whom.

**No feed.** No followers, likes, counts, streaks or ranking. Sharing, when it ships, is a page handed to one named person, who hands one back.

## What is rough

- Encryption at rest for tiers 2 and 3 is specified in outline and not built. Today the files are plain.
- The circle, the exchange of pages between two records, has a bundle format and no transport.
- The adapters are the maintainer's own sources first: iPhone backups, Google Takeout, WhatsApp, iMessage, Apple Health, a handful of apps. Android has only what Takeout carries. See the [adapter bounties](adapter-bounties.md).
- The country of a night comes from a named place, else the nearest large airport, which is wrong near borders.
- The spec is v0.2, draft. The envelope changes only with a version bump and a migration, but it may change.
- One maintainer, who merges monthly and reads every PR.

## The ask

- Try the demo and say what the Day gets wrong.
- Read the spec and implement `verify` in your language. If it takes more than an afternoon, the spec has a bug; file it.
- Write an adapter for the export you already have. The [bounty list](adapter-bounties.md) names the ones wanted, with formats, tiers and the easy ones marked; the rules are in [Contributing](CONTRIBUTING.md).
- If you keep a logbook already, on paper or in text, say what it has that this does not.

Code is Apache-2.0. The specification is CC0. [github.com/bighydro/logbook](https://github.com/bighydro/logbook)
