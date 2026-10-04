# Roadmap

Milestones, not dates. Each one ends with something a stranger can use. [Release notes](https://bighydro.github.io/logbook/release-notes/) say what each version changed for you; this page says where the whole thing is going.

## Done

- **The format.** SPEC v0.2, the JSON Schema, the conformance fixture, and a CLI that writes, reads, verifies and exports it. A second implementation, [logbook-ts](https://github.com/bighydro/logbook-ts), was written from the spec alone and agrees with this one on every record either writes; CI checks that on every pull request.
- **The drops.** Adapters for Google Takeout, an iPhone backup (`import-backup`), Apple Health, Photos, WhatsApp, iMessage, mail, calendars, flights, music, podcasts, money, Screen Time, voice memos with local transcription, boats over AIS and aircraft over ADS-B. `logbook add <file>` sniffs which is which. Backfill and live sources write the same line for the same event.
- **The days.** `day`, `days`, `trips`, `year`, `digest`, the rollups, the ledger, people, promises, tasks and search, all derived from the log and recomputed when the rules improve. A browser view on this machine, a paper edition, an Obsidian or Logseq vault, and an MCP server behind a tier gate.
- **Sealed at rest.** Tiers 2 and 3 sealed with age to the owner's recipients, the chain verifiable without a key (SPEC v0.3, RFC 0029, ADR 0020); a Level 2 conformance fixture with a published identity.
- **The circle, by file.** A signed bundle of one day or one trip handed to one named person, verified and kept beside the receiver's record (RFC 0025). Transport is a USB stick, a message, whatever carries a file.
- **The community kit.** The adapter template, the bounty list, payload-profile RFCs, changelog fragments, a docs site.

## Next

- **A transport for the circle.** Peer to peer over a relay, or a small server the owner runs. The bundle format came first so that the choice can wait.
- **Per-person pages across the circle.** Last real contact, shared moments, birthdays, from both sides of a shared day.
- **More adapters from the bounty list**, by the people who hold the exports: Strava, Garmin, Immich, Telegram, bank CSVs, Letterboxd and the rest.

## 1.0

The envelope frozen; a conformance badge; books and published pages as community layers; two implementations in agreement on every rule. Data-portability law gives every service a reason to emit the format, and a logbook becomes the strongest claim a person can make about what happened to them.
