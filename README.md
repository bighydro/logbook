# Logbook

**A diary that writes itself.**

Your life already gets recorded, by your phone, your photos, your calendar, your messages. Logbook writes it all down once, in one folder that only you hold, and reads it back to you as days. You hand a page to someone you care about; they hand one back.

It is the opposite of social media: no feed, no followers, no likes, no counts. Reveal, never reward. Nothing leaves without a name.

![How Logbook works](https://raw.githubusercontent.com/bighydro/logbook/main/docs/how-it-works.svg)

```bash
brew install bighydro/logbook/logbook   # Mac, with Homebrew
pipx install openlogbook                # Linux; or anywhere Python is: uv tool install openlogbook
pipx install openlogbook                # Windows, in Terminal, once pipx is there; the steps: docs/install.md
logbook demo --out ~/Demo/Logbook       # a month of a person who does not exist, every profile
export LOGBOOK_HOME=~/Demo/Logbook
logbook trips                           # a cabin weekend, Zürich, a week aboard, Copenhagen
logbook day 2026-06-17                  # one day read back: nights, stays, who was there, health
logbook verify                          # the chain is intact
```

Never opened a terminal? [docs/install.md](docs/install.md) walks through the install on each platform and says what the screen will show.

Then your own: `logbook setup` asks one question at a time ([the first hour](docs/first-hour.md)), or `logbook init` makes the folder and your key, `logbook add ~/Downloads/takeout.zip` reads any export without flags, and `logbook show today` reads it back. Docker and Nix are in [the tour](docs/tour.md).

## What it does

**The record.** Everything that happened to you, written once, as JSON lines in files you own. One file per month, every line hash-chained to the one before, nothing ever edited or pruned. Fifty-odd adapters read the exports and app stores you already have: Google Takeout, an iPhone backup, Apple Health, Photos, WhatsApp, iMessage, mail, calendars, flights, music, money, boats and aircraft. Live sources (`sync`) write the same line for the same event, so backfill and live never duplicate. What a tier 2 or 3 line says can be sealed at rest with [age](https://age-encryption.org) to keys only you hold; the chain verifies without any key ([sealing](docs/tour.md#sealing-tiers-2-and-3), [RFC 0029](rfcs/0029-encryption-at-rest.md)).

**The recount.** The record reads your life back to you without your effort. `day` is one calendar day: the night, the stays, who was there, health, weather, what you wrote. `trips` finds runs of nights away; `year` composes a year; `digest` is the day in 25 lines with one question you may ignore; `rollup`, `ledger`, `people`, `promises`, `tasks` and `search` each read one aspect. `serve` shows it in a browser on this machine, `year --print` lays it out for paper, `export vault` renders it for Obsidian or Logseq, and `mcp` serves it to an agent on this machine behind a tier gate.

**The circle.** `share day` and `export trip-bundle` write a signed bundle of one day or one trip for a named person; `receive` checks the signature and keeps their side beside your record, never in its chain. Two logbooks, one shared moment, each side its own words and photos.

Nothing here needs the app to make sense: open the files in any editor twenty years from now. The format is one page, [SPEC.md](SPEC.md), and a second implementation written from it alone, [logbook-ts](https://github.com/bighydro/logbook-ts), agrees with this one on every record either writes.

## The ten rules

1. **Append only.** Every line is hash-chained to the one before. Nothing is updated or deleted; a correction is a new line that retracts an old one. A broken chain is an error, never repaired silently.
2. **Files are the truth.** The record is a folder of JSON lines and Markdown. Any database is a cache that can be thrown away and rebuilt.
3. **One log.** Every source writes into the same record. Days, trips, people and places are derived from it and recomputed when the rules improve; they are never the source of anything.
4. **Nothing leaves without a name.** There is no server and no account. A share is a signed page handed to one named person, and the policy file says how much each person may receive.
5. **Reading never opens a connection.** Every reader touches the record and the tables shipped in the package, nothing else. A socket opens only behind a command that says so, and a test enforces it.
6. **Adapters are pure.** Export in, observations out. No network on the default path, no write to the source, and every app store is checked with `PRAGMA table_info` before it is read.
7. **Every line has a tier.** 1 is where you were, 2 is what you said, 3 is money and health. Derived data inherits the highest tier of its evidence, tiers 2 and 3 cross to no one by default, and a record with recipients seals them at rest.
8. **Reveal, never reward.** No feed, no followers, no likes, no counts, no streaks, no ranking. The one evening question can be ignored forever.
9. **Humans write, agents operate.** An agent may import, derive and draft. A note, a confirmation and a visibility decision are the owner's alone, enforced in the lowest layer.
10. **The spec is the product.** The envelope changes only with a version bump, a regenerated conformance fixture and a decision record, and two independent implementations must agree before 1.0 is frozen.

## Where to go next

| You want to | Read |
|---|---|
| install it, one line on each platform | [Install](docs/install.md) |
| try it in five minutes, nothing of yours | [Try it](docs/try-it.md) |
| set up your own record, one question at a time | [The first hour](docs/first-hour.md) |
| see every command on your own record | [The tour](docs/tour.md) |
| find every page | [The docs](docs/index.md), also at https://bighydro.github.io/logbook/ |
| understand the format, or implement it | [SPEC.md](SPEC.md), [conformance/](conformance/README.md), [the RFCs](rfcs/README.md) |
| know how the pieces fit | [ARCHITECTURE.md](ARCHITECTURE.md), [the decisions](docs/adr/README.md) |
| know why, and what it refuses to have | [VISION.md](VISION.md), [LORE.md](LORE.md) |
| know what shipped and what is next | [Release notes](docs/release-notes.md), [CHANGELOG.md](CHANGELOG.md), [ROADMAP.md](ROADMAP.md) |
| write an adapter for the export you already have | [CONTRIBUTING.md](CONTRIBUTING.md), [the bounties](docs/adapter-bounties.md) |
| report a vulnerability, or read the threat model | [SECURITY.md](SECURITY.md) |

## Implementations

| Implementation | Language | Status |
|---|---|---|
| [openlogbook](https://github.com/bighydro/logbook) (this repository) | Python | reference |
| [logbook-ts](https://github.com/bighydro/logbook-ts) | TypeScript | independent, written from the spec alone |

Both reproduce the conformance head in `conformance/expected.json` (Level 1), and CI appends a line with one and verifies it with the other on every pull request. Level 2, the sealed sample `conformance/sample-logbook-sealed` opened with the published fixture identity (`conformance/expected-sealed.json`), is the reference's so far; logbook-ts's Level 2 is the next step of RFC 0029 §14. Level 2, the sealed sample `conformance/sample-logbook-sealed` with its published identity, is the reference's so far (SPEC §6).

## Status

Format `logbook/0.3`, package 0.5.0, status alpha. The record, the readers, sharing by file and sealing of tiers 2 and 3 at rest all ship; a transport for the circle is the next format work ([ROADMAP.md](ROADMAP.md)).

Apache-2.0 for code. The specification is CC0.
