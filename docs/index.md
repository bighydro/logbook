# Logbook

A diary that writes itself: your life, in a folder you hold, read back to you as days. The [README](https://github.com/bighydro/logbook#readme) is the landing page; this is every page, one line each.

## Start

- [Install](install.md): one line on each platform, for someone who has never opened a terminal, with what each step prints.
- [Try it](try-it.md): five minutes with a demo record, every reader on a month that never happened.
- [The first hour](first-hour.md): `logbook setup` screen by screen, for someone who has never used a terminal.
- [The commands](commands.md): the 22 commands by what you are doing, and the older names each still answers to.
- [The tour](tour.md): every command on your own record, from the first import to handing a day to a friend.
- [A life in a record](demo.md): `logbook demo --years N`, a synthetic life in phases from a childhood of scanned photos to the boat.
- [Your life in a folder](launch-post.md): the launch post, with everything in it synthetic.

## Why

- [Vision](VISION.md): the record, the recount, the circle, and the list of things the product refuses to have.
- [Lore](LORE.md): where the logbook comes from, ships, pilots, diaries, and the log in computing.
- [Roadmap](ROADMAP.md): what is done, what is next, what 1.0 means.
- [Open problems](PROBLEMS.md): what the format cannot do yet, stated so a collaborator can pick one.
- [Letters](letters/2026-10-04-the-freeze.md): the captain to the builders; the first one is about the freeze.
- [Release notes](release-notes.md): what each version changed for you, five bullets each.
- [Changelog](CHANGELOG.md): every change, in full.

## The format

- [Specification](SPEC.md): the folder, the line, the chain, the tiers, the profiles, conformance. One page, CC0.
- [Architecture](ARCHITECTURE.md): the five layers and what each may depend on.
- [How a line becomes a Day](line-to-day.md): one line followed from the adapter through the index to the page.
- [Conformance](conformance/README.md): the sample record and the head every implementation must reproduce.
- [Decisions](adr/README.md): the architecture decision records, numbered, never edited after acceptance.
- [RFCs](rfcs/README.md): the payload profiles and spec changes, each with a schema and one synthetic example.
- [RFC 0025, the shared bundle](rfcs/rfc-0025-shared-page-bundle.md): the signed page one logbook hands another.
- [RFC 0027, reflection](rfcs/0027-reflection.md): the digest's closing question comes from the record.
- [Benchmark, per-line sealing](rfcs/bench-encryption-2026-10.md): what encryption at rest would cost on a three-million-line record.

## Reading the record

- [The Day](day.md): one calendar day read back, and `days` for a window of them.
- [The Year](year.md): one year composed from every reader, and one trip read back on its own.
- [The rollups](rollups.md): countries, flights, nights, places, people, health, listening, attention, summed over a range.
- [The digest](digest.md): the day in 25 lines at most, ending in one question you may ignore.
- [The ledger](ledger.md): the record's money read back in context, by month or by trip.
- [People](people.md): everyone the record knows, what it knows of each, and merging the duplicates.
- [Promises](promises.md): the sentences in your own words that read as commitments, and whether they were kept.
- [Tasks](tasks.md): every task line, open or done, and the evidence that one was finished.
- [Search](search.md): full text across notes, transcripts, messages, mail and events, within a tier.
- [In a browser](serve.md): `logbook serve`, the record read on this machine only.
- [On paper](print.md): the year and the trip laid out for A4 and Letter.
- [The vault](vault.md): the record as a folder of Markdown with wikilinks for Obsidian or Logseq.
- [Describing keepers](describe.md): a local vision model's note per photo you marked a keeper.
- [The MCP server](mcp.md): the record served to an agent on this machine, behind a tier gate.

## Sources

- [Adapters](adapters/README.md): what an adapter is, the three names it exports, the rules it keeps.
- [Adapter bounties](adapter-bounties.md): the adapters not yet written, each with its export, profile and tier.
- [Google Takeout](adapters/takeout.md): one archive, many witnesses; the sub-adapters for [Tasks](adapters/takeout-tasks.md), [Maps](adapters/takeout-maps.md), [Home](adapters/takeout-home.md) and [YouTube](adapters/takeout-youtube.md).
- [Mail](adapters/mail.md): one line per message from a Takeout mailbox, at 20 GB scale.
- [Health](adapters/health.md): Apple Health, Withings and MyFitnessPal as `health-sample/v1`.
- [Apple Photos](adapters/photos.md): the library, its albums, favourites and the names you gave the faces.
- [Apple Wallet](adapters/wallet.md): boarding passes and tickets as flights and events.
- [Listening](adapters/listen.md): Spotify, Apple Music and Apple Podcasts as `listen/v1`.
- [Screen Time](adapters/screentime.md): which app, from when to when.
- [Voice memos](adapters/voice-memos.md): the recordings, and their transcripts from a local model.
- [Weather](adapters/weather.md): the weather of the places your days were spent at, one line per day.
- [Passages](adapters/passages.md): a ship's deck log transcribed to CSV as the vessel's own movement.

## Keeping it

- [Backup](backup.md): copy the record to another disk, verify it there, restore it.
- [The attachment store](attachments.md): the content-addressed bytes a line points at.
- [Shared trips](trips-shared.md): two people on one trip exchange their records of it.

## The project

- [Contributing](CONTRIBUTING.md): one way to do everything, from the first clone to the merged pull request.
- [Governance](GOVERNANCE.md): one captain, public decisions, RFCs for profiles.
- [Releasing](releasing.md): the checklist the captain follows.
- [Security](SECURITY.md): the threat model on one page, and how to report.
