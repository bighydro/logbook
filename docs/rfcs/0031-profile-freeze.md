# RFC 0031 — Profile freeze for v1.0

Status: **draft** · 2026-10-04 · comment period: two weeks · Decision 2 of the October 2026 audit

The envelope (SPEC §2–3) is what v1.0 freezes. The payload profiles under it (SPEC §5, one RFC each in `rfcs/`) have so far been drafts, every one of them, and a draft may change. This RFC sorts them into three sets by one rule computed from the code, not from memory: a profile that a reader, a rollup or a derive command reads is **frozen**; a profile that an adapter writes and nothing reads is **parked**; a profile that nothing writes and nothing reads is **deleted**. It then says what each word binds, how a parked profile becomes frozen later, and the five pull requests that carry it out.

## Summary

- Nineteen profiles are frozen: schema additive-only, reader output stable, one conformance fixture each that both implementations pass.
- Seven are parked: adapters keep writing them, the schema may change, no reader and no fixture, not in the v1.0 promise.
- Two are deleted: `commitment/v1` and `commitment-close/v1`, written by nothing and read by nothing since RFC 0007 was drafted.
- `trip/v1` is renamed `journey/v1` for new lines; readers accept both spellings; no migration, since the record is append-only and a rename is a reader's concern.
- The frozen set does not change before v1.0; a parked profile joins it by a reader, a fixture in both implementations and one amendment to this RFC.

## Motivation

A format people can build on must stop moving. A second implementation, a notebook that reads the folder, an adapter someone writes for a service we have never seen: each of them is a bet that the shape of a line on disk today is the shape it has next year. The envelope has held still since v0.2 and the chain proves it. The profiles have not: RFC 0020 was amended a day after it was drafted, RFC 0019 gained a field this month, and every RFC in the list says *draft*. A builder reading the list cannot tell which drafts are load-bearing.

Two implementations must agree. SPEC §6 says it for the envelope and the chain, and the cross-impl job holds [logbook-ts](https://github.com/bighydro/logbook-ts) to it on every push; SPEC §6.1 says it for the readers and names the readers that are compared. A profile is only as frozen as the fixtures that pin it: **a frozen profile is one whose schema, canonical form and reader output are covered by conformance fixtures in both implementations.** Without the fixture, a freeze is a sentence in a document; with it, a change that breaks the promise fails a job.

The rule for the three sets is deliberately mechanical. Whether a profile is read is a fact of the code, found by looking for the lines that select its kind (`Index.by_kind`, `of_kind`, `evidence`, `retractions`, `resolutions`) and interpret its fields. A profile the owner cares about but nothing reads cannot be frozen yet, because there is no reader output to pin; the way to freeze it is to write the reader. That is the process section.

## How the sets were computed

The writers are the modules that spell a `payload.schema` value (every adapter sets `SCHEMA = "<name>/v1"`, or imports another adapter's), plus the core commands that append a line of a kind (`add`, `retract`, `migrate`, `infer flights`, the keeper inference of a photo import, `add story`, `export crossing`, `import trip-bundle`, `done`, `people merge`). The readers are the modules that select lines by kind and read the payload: the Day, `days`, `derive stays`, `trips`, the rollups, `keepers`, `promises`, `year`, `ledger`, `people`, `places`, `digest`, `questions`, `done` and the pages built on them.

Two commands touch every profile and count for neither set. `show` (SPEC §3.2.1) prints one row per line of whatever kind it meets, with a formatter for the profiles it knows and `text`, `title`, `name`, `url` or `key=value` for the rest; `search` indexes the words of thirteen kinds. Neither interprets a profile's structure, and neither is compared across implementations (§6.1), so neither can pin a schema. A profile read only by them is parked. The demo generators (`demo.py`, `demo_life.py`) write every profile and are not adapters.

The five bundle formats (`crossing-package/v1`, `shared-page/v1`, `trip-bundle/v1`, `trip-share/v1`, `day-package/v1`) are manifests and pages, not line payloads, and are outside this RFC; `received/v1`, the line that `import trip-bundle` appends, is in it.

The count the audit expected was 18 frozen, 10 parked, 2 deleted. The code gives **19, 7, 2** (28 profiles). The deleted pair matches. The difference is in the other two sets, and the numbers are the code's as of main at the time of writing, not the earlier audit's: `story/v1` and `received/v1` became read by the Day in the week before this RFC (#187, #194), the screen-time lines under `event/v1` are read by `rollup attention`, and the earlier audit may have counted the bundle formats, which this one leaves out. The tables below are the evidence; a reader who disagrees with a row can point at the module.

## The frozen set

Nineteen profiles. *Written by* names adapters by their registry names, and core commands in italics. *Read by* names the module and, where it differs, the command.

| Profile | Written by | Read by | Status |
|---|---|---|---|
| `call/v1` (0012) | ios-calls, google-takeout-meet | `day`, `people`, `stays` (evidence), `rollup people --drifting` | frozen |
| `event/v1` (0009) | ios-calendar, ics, gcal, apple-wallet, screentime (kind `app-use`), google-takeout-home, -pay, -access-log | `day`, `stays` (evidence), `people`, `flights` (`infer flights`), `digest`, `questions`, `done`, `rollup attention` (kind `app-use`) | frozen |
| `flight/v1` (0013) | flighty; *add flights*, *infer flights* | `flights` (the standing set), `day`, `trips`, `rollup flights`, `year`, `digest` | frozen |
| `health-sample/v1` (0014; kind `health`) | apple-health, withings, withings-export, myfitnesspal, myfitnesspal-export | `health` (`rollup health`), `day`, `days`, `year`, `trip` | frozen |
| `keeper/v1` (0024) | *the keeper inference of a photo import* (producer `keeper-inference`) | `keepers`, `day`, `year`, `describe` | frozen |
| `listen/v1` (0019) | spotify, apple-music, apple-podcasts, shazam | `listen_rollup` (`rollup listen`) | frozen |
| `location/v1` (0001) | google-takeout-location, dawarich, dawarich (live), ais, adsb, passages | `stays` (`derive stays`), `day`, `days`, `trips`, `rollup`, `year`, `places`, `flights` | frozen |
| `mail/v1` (0015) | mail | `day`, `people`, `done` | frozen |
| `message/v1` (0008) | imessage, imessage (live), whatsapp, beeper, line, twitter, google-takeout-chat | `day`, `people`, `stays` (evidence), `rollup people --drifting` | frozen |
| `note/v1` (0010) | ios-notes, google-takeout-keep, granola; *add*, *setup*, *describe*, the MCP server | `day`, `promises`, `stays` (evidence), `places`, `ledger`, `describe` | frozen |
| `photo/v1` (0002) | apple-photos, immich, google-takeout-photos | `day`, `keepers`, `stays` (evidence), `people` (faces), `pages`, `year` | frozen |
| `received/v1` (0025) | *import trip-bundle* | `day`, `trip` (the shared columns), `serve` | frozen |
| `resolution/v1` (0006) | ios-contacts, whatsapp-contacts, google-takeout-contacts; *people merge* | `resolve`, and through it the names of every reader; `people`, `trips`, `digest`, `questions` | frozen |
| `retraction/v1` (0003) | *retract*, *repair* | every reader: `Index.retractions` is what makes a line standing | frozen |
| `story/v1` (0028) | *add story* | `day`, `days` (the stories about the day) | frozen |
| `task/v1` (0016) | apple-reminders, google-takeout-tasks; *done*, the MCP server | `promises`, `done` | frozen |
| `transaction/v1` (0021) | splitwise, copilot, google-takeout-pay | `ledger`, `trip` (the page), `done` | frozen |
| `transcript/v1` (0004) | transcript, granola, wispr-flow; *transcribe* | `day`, `promises`, `people`, `stays` (evidence), `add story` | frozen |
| `weather/v1` (0026) | weather (live) | `day`, `year`, `trips` | frozen |

Three rows deserve a word. `retraction/v1` and `resolution/v1` are read by every reader, since standing lines and names are computed from them before any reader starts; they are frozen whether or not anyone thought of them as profiles. `story/v1` is frozen by the rule although RFC 0028 is marked *unfinished*: the Day reads it, so its shape is load-bearing today. Its open questions are for its author to close before the fixture is written, and until then the freeze covers the fields the Day reads (`title`, `text`, `refers_to`, `teller`, `listener`, `confidence`, `source`) and not the ones still in question.

## The parked set

Seven profiles. An adapter, or a core command, writes each; no reader, rollup or derive command reads it. `show` prints it and `search` indexes its words where it has any.

| Profile | Written by | Read by | Status |
|---|---|---|---|
| `browse/v1` (0017) | safari, pocket, google-takeout-chrome, google-takeout-activity | nothing (`show`, `search`) | parked |
| `crossing/v1` (0011) | *export crossing*, *share day*, *export trip-bundle* | nothing (`show`); the crossing watermark is a file beside the record, not these lines | parked |
| `highlight/v1` (0022) | apple-books, google-takeout-maps | nothing (`show`, `search`) | parked |
| `migration/v1` (SPEC §3.1) | *migrate* | nothing; `verify` checks the chain it sits in, not the line | parked, see the unresolved questions |
| `trip/v1` (0020) → `journey/v1` | easypark, sbb, passages | nothing (`show`, `search`) | parked, renamed |
| `voice-memo/v1` (0023) | voice-memos | nothing as a reader; `transcribe` reads it to write `transcript/v1` lines | parked |
| `watch/v1` (0018) | google-takeout-youtube | nothing (`show`, `search`) | parked |

`trip/v1` is the surprise of the table. The passage lines (RFC 0020 rule 6) are the only thing a deck log writes that is not a position, and the Day shows a vessel's leg from the `location/v1` lines beside them, as ADR 0018 says it should; the trip line itself is read by nothing. The parking is the fact, and the rename below is what makes the fact safe to leave.

## The deleted set

| Profile | Written by | Read by | Status |
|---|---|---|---|
| `commitment/v1` (0007) | nothing | nothing | deleted |
| `commitment-close/v1` (0007) | nothing | nothing | deleted |

No adapter sets either schema; no core command appends either kind; no reader selects either. `promises` (SPEC §3.2.10) proposes and never asserts, which is RFC 0007's rule 3 applied so thoroughly that the profile the rule belongs to was never written.

## What "frozen" means

For every profile in the frozen set, from the merge of this RFC until v1.0 and through it:

1. **The schema is additive-only.** A field may be added, as MAY. No field is removed, renamed or retyped; no MUST becomes MAY or the reverse; no enumerated value is withdrawn. A change that needs any of these is a new version, `name/v2`, with its own RFC, and the readers keep reading `v1`.
2. **The canonical form is fixed.** It already is, by ADR 0014 and SPEC §3: the line's hash is computed over RFC 8785 JSON of the content fields. The freeze adds nothing here and is listed so that nobody reads an "additive" field change as licence to rename a key a hash covers.
3. **The reader output is stable.** The JSON of every reader that reads the profile keeps every key it has today with the same meaning and type under the fields SPEC §6.1 compares; a key may be added. The fields §3.2 marks as a reader's own (`confidence`, `reasons`, `method`, `warning`) stay the reader's own.
4. **One conformance fixture per profile**, under `tests/fixtures/conformance/<profile>/`: one synthetic line as its RFC's example gives it, its canonical form and hash, the `show` row the reference prints for it, and, for a profile that a §6.1 reader reads, that reader's JSON over a record that holds the line. The fixture is the freeze. logbook-ts must pass the parts of it that its readers cover, and the cross-impl job runs them.

A frozen profile's RFC moves from *draft* to *frozen for v1.0* in its status line, with the date and a pointer here. The RFC is not otherwise edited: an addition under rule 1 is an amendment to the RFC with its date, as RFC 0020 did on 2026-10-02.

## What "parked" means

For every profile in the parked set:

1. **Adapters keep writing it.** Nothing about `logbook add` or `import-backup` changes; a line written today is as valid as one written yesterday, and the chain holds it either way.
2. **The schema is marked "may change".** Its RFC's status line says *parked · may change before v1.0*. A field may be renamed, retyped or dropped by an amendment with a date, and a line written before the amendment is read by what it says, not by what the amendment says.
3. **A reader may be added later.** That is the only way out of the set (the process below).
4. **No conformance fixture**, and no row in the §6.1 table.
5. **Not in the v1.0 promise.** A builder who reads a parked profile does so knowing the shape is a draft, and a change to it is not a breaking change of the format.

Parked is not a judgement of worth. `browse/v1` and `watch/v1` carry more lines than most frozen profiles in a real record; they are parked because nothing reads them yet, and a schema nobody reads is a schema nobody has tested against a day.

## Deletions

`commitment/v1` and `commitment-close/v1` are removed from the code, the documents and the registry:

- **Code.** There is nothing to remove from the writers or the readers, since neither exists. `promises.py` cites RFC 0007 for the word `inferred` (its `certainty`), and `judge.py` for what a commitment is; the citation moves to `docs/promises.md` and SPEC §3.2.10, which carry the definition from then on.
- **Documents.** The two rows leave SPEC §4's tier table, with no spec version bump: §4 lists defaults for profiles that exist, the envelope (§2–3) is untouched, and the conformance sample holds no line of either kind (its profile lines are RFCs 0011–0024). `rfcs/README.md` lists RFC 0007 under *withdrawn*. `docs/promises.md` and the README stop pointing at it for the definition.
- **Registry.** RFC 0007's status line becomes *withdrawn by RFC 0031*, dated the day PR 1 merges; the file stays, since RFCs are the project's own record and are never deleted, and the number is never reused.

**Existing records still verify.** `verify` checks the envelope and the chain (SPEC §6); a payload's schema is not its concern, and SPEC §5 already says a logbook with unknown schemas is valid. A record that holds a `commitment/v1` line keeps its hash, its `seq` and its place in the chain. `show` prints it as it prints any line of a kind it has no formatter for: the clock, the kind, the source, then the payload's `text` where there is one (a commitment has one) and every field as `key=value` where there is none (a close). Nothing is hidden and nothing is rewritten.

## Rename: `trip/v1` → `journey/v1`

For the written form: a new line of a bought movement or a metered stop (RFC 0020) carries `kind: "journey"` and `payload.schema: "journey/v1"`; `easypark`, `sbb` and `passages` write that from the pull request that lands the alias. `journey/v1` is `trip/v1` under a new name, field for field; RFC 0020 is amended with the rename and the date, and keeps its number.

**Readers accept both.** `show` formats a `trip`/`trip/v1` line and a `journey`/`journey/v1` line the same way; `search --kinds trip` and `--kinds journey` each find both; any reader that is later written for the profile reads both kinds. A record written across the rename holds lines of both kinds, and that is the normal state of a record.

**`migrate` is not required, and is not offered.** The record is append-only (SPEC §3): the old lines cannot be rewritten, and a migration that appended a `journey/v1` twin of every `trip/v1` line would double the record to spell a word differently. A rename is a reader concern. The chain does not care what a payload calls itself; the reader does, and the reader is the one place a rule can be held, versioned and re-run (ADR 0013). The `migration/v1` line of SPEC §3.1 exists for a change of canonicalisation, which a reader cannot absorb; this is not that.

**Why rename at all.** Since ADR 0019, *trip* names the derived thing (`logbook trips`, `trip:<first>:<last>`, the trip page, the shared trip); a `trip/v1` line is a ride, a ticket, a parking session or a passage: raw evidence, like a flight line. Two things called *trip* in the same `show` row and the same `search --kinds` is the kind of ambiguity a frozen format should not carry into its first stable year, and the profile is parked, so this is the cheap moment. ADR 0019 rule 4 says the profile "keeps its name"; it was written to refuse a profile for the derived trip, and this rename refuses the same thing from the other side. It still needs a new ADR to say so, since ADRs are not edited (unresolved question 2).

## Process: how a parked profile gets frozen

Three things, in this order, and then one amendment:

1. **A reader.** A reader, rollup or derive command of the reference reads the profile's lines and interprets its fields; its output is a §3.2 section, written down so that a second implementation can agree with it. A `show` formatter or a `search` row is not a reader.
2. **A fixture in both implementations.** The fixture of the frozen section above, passed by the reference, and by logbook-ts for the parts its readers cover, in the cross-impl job.
3. **A schema pass.** The RFC's field table is read once more against every writer, and any field a writer sets that the table does not have is added as MAY or dropped from the writer, so the frozen table is the whole truth.
4. **One amendment to this RFC**, dated, moving the row from the parked table to the frozen table with its reader and its fixture named. The profile's own RFC changes its status line.

A profile frozen this way is frozen from the amendment's date; the frozen set grows and never shrinks before v1.0.

The reverse does not exist. A frozen profile does not return to parked: if its reader is withdrawn, the fixture still holds and the schema is still frozen, because a builder may have read the promise.

## Unresolved questions

1. **Is `migration/v1` a profile or a part of §3.1?** It is written by `migrate`, read by nothing, and named in the spec's own text. By the rule it is parked; by its place in the spec it is frozen with the envelope. Proposed answer: it belongs to §3.1, is frozen with it, and leaves the tables of this RFC; the spec's wording is the place to say so (PR 5). Carl decides.
2. **ADR 0019 rule 4 and the rename.** The rule says `trip/v1` keeps its name. A new ADR that supersedes that one sentence, and only it, is proposed alongside PR 2; the alternative is to drop the rename and freeze nothing about the word. Carl decides whether a one-sentence ADR is worth its number.
3. **Where the per-profile fixtures live.** This RFC says `tests/fixtures/conformance/<profile>/`, as the audit asked. logbook-ts works from `SPEC.md`, `rfcs/` and the root `conformance/` folder and nothing else (CONTRIBUTING, the clean-room rule); a fixture under `tests/` is one it would have to be told about. Either the fixtures live under `conformance/profiles/` or the clean-room rule names the new path.
4. **What "reader output stable" binds while logbook-ts has no derived reader.** §6.1's status line is honest: logbook-ts carries `verify`, `add` and `show`, and no second implementation of a derived reader exists. Until one does, rule 3 of the freeze binds the reference alone, and the cross-implementation fixture covers the line, its hash and its `show` row. The RFC says this plainly rather than promising what cannot yet be checked.
5. **`story/v1` is frozen while its RFC is unfinished.** The freeze covers the fields the Day reads. Whether the open questions of RFC 0028 (its non-technical co-author's) should be closed before this RFC merges, or whether the fixture can wait for them, is the author's call and the captain's.
6. **Does `search` count for anything?** It reads the text fields of thirteen kinds by name and skips a fixed list of keys. This RFC says it is not a reader. If Carl disagrees, `browse/v1`, `watch/v1`, `highlight/v1`, `voice-memo/v1` and `trip/v1` move to frozen and the count is 24, 2, 2.
7. **The `event/v1` kind `app-use`.** Screen-time lines carry `event/v1` under a kind of their own, and `rollup attention` reads them by that kind while `day` reads `event`. One profile under two kinds is a shape no other profile has; whether that is an amendment to RFC 0009 or a profile of its own is open, and the freeze of `event/v1` covers both kinds as they are.
8. **The counts.** 19, 7, 2 against the expected 18, 10, 2. The rule above is the whole method, and the tables are the evidence; if the earlier audit's universe can be reconstructed, the two can be reconciled row by row.
9. **The date promise.** The frozen set does not change before v1.0. v1.0's horizon is the roadmap's phase 5, which has no date. A freeze with no end is a promise a builder can hold; a freeze with no v1.0 is one the project has to keep indefinitely. Both are acceptable; the roadmap should say which is intended.

## Implementation plan

Five pull requests, in order, each one issue, each mergeable alone:

1. **Delete the two dead profiles.** RFC 0007's status line; the two rows of SPEC §4; `rfcs/README.md`; the citations in `docs/promises.md`, the README, `promises.py` and `judge.py` moved to the reader's own documents. No code path changes; the tests that mention the word *commitment* describe `promises` and stay. Changelog fragment under *Profiles and spec*.
2. **The `journey/v1` alias.** `easypark`, `sbb` and `passages` write `journey`/`journey/v1`; `show`, `search` and the kind tables accept both; RFC 0020 amended; the one-sentence ADR if question 2 says yes; the fixtures of the three adapters regenerated; a test that a record with both spellings shows and searches as one.
3. **Conformance fixtures, Python side.** `tests/fixtures/conformance/<profile>/` for the nineteen frozen profiles (or the path question 3 settles), generated by a script beside `conformance/make_sample.py`, with a test that every frozen profile has one and that every fixture's hash, `show` row and reader JSON still hold. The nineteen RFCs' status lines.
4. **logbook-ts fixtures.** The same fixtures read by logbook-ts's cross-implementation test for the parts it covers (`verify`, `add`, `show`), wired into the cross-impl job. Filed against logbook-ts from the spec's words, never from this repository's source.
5. **SPEC §6.1 wording.** §5 gains the three words and what each binds, pointing here; §6.1 says that a frozen profile's fixture is part of conformance; §3.1 answers question 1; the *Status* lines of §6 and §6.1 say what is compared today. Spec text only, no envelope change, no version bump.

The letter to builders, `docs/letters/2026-10-04-the-freeze.md`, goes out with this RFC and is updated once when the five have merged.
