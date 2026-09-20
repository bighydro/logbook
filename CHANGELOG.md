# Changelog

## Unreleased
- SPEC §1.1 (ADR 0015): the content-addressed attachment store, `attachments/<sha256>`, optional, write-once, never pruned, outside the hash chain; the `{ sha256, path, bytes, media_type }` reference shape that RFCs 0004, 0005, 0008 and 0010 point at. No format bump; nothing implemented yet.
- SPEC clarifications, no format bump, no hash change: GENESIS named; month-file placement is a writer MUST, not a validity condition; every envelope field present and `end` null, never absent; timestamps UTC with `Z`, fractional seconds hashed verbatim; `seq` decimal unpadded and hex lowercase in the pre-image; the verifier checks §2 as well as the chain; duplicate keys and duplicate `seq` are invalid; only the canonical form is hashed; unknown keys in `logbook.json` are preserved; the write order (lines, then `logbook.json`, then the index). §6 and `conformance/README.md` now state the same tamper-and-delete condition. Found by the clean-room TypeScript implementation.
- The reference is as strict as SPEC §2–3 (#47), no hash change: `verify` names any missing envelope field (`end` is `null`, never absent; `schema/observation.schema.json` now requires it); a line with a duplicate JSON key, at any depth, is invalid on read; writers normalise `at`/`end`/`recorded_at` to UTC with a literal `Z` (an offset is converted, a stamp with no zone is refused); `verify` reports a timestamp with a numeric offset as a WARNING in this release — the record stays valid, exit 0 — and the next release makes it an error; `append`/`append_many` fsync the month files before `logbook.json` is saved.
- `ios-contacts` file adapter: an iPhone's AddressBook.sqlitedb (also the hashed file in an unencrypted Finder/iTunes backup) → `resolution/v1` (RFC 0006), one line per phone number and email address, minting one UUIDv7 per contact as `person` or `company` — how a record gets its people (ADR 0013.2). Opened read-only and immutable; refs are deduped on the normalised value so a later backup appends nothing already resolved; `LOGBOOK_DIAL_PREFIX` completes numbers saved without a country code, dropping one national trunk `0`. `logbook add` now reports every count an adapter tallies, not only the location ones.
- `whatsapp` file adapter: an iPhone's WhatsApp ChatStorage.sqlite (also the hashed file in an unencrypted Finder/iTunes backup) → `message/v1` (RFC 0008), one line per message: chat (direct or group; broadcast lists are groups; status chats skipped), sender as a source-native `phone` or `handle` ref through the new shared `adapters/phone.py` (so a WhatsApp number and an address-book number are the same ref), text, `media_kind`. `raw_id` is `<chat jid>:<stanza id>` so a later backup appends nothing already logged. Media v1 rule: files are never copied into the record; a file present under `Message/` is hashed into `extra.media` (`sha256`, `bytes`, `local_path`) for a later attach pass, a missing one is `extra.media_missing`; `payload.media` is never set (the §1.1 store is not built yet); `LOGBOOK_WHATSAPP_HASH_MEDIA=0` skips the hashing. Streams the store through one cursor, built for a million rows. `logbook add` now also reports what an adapter noted without skipping (media hashed or missing, rows keyed by row id).

## 0.3.0 — 2026-09-15
- **BREAKING:** records created by 0.1.0 or 0.2.0 must run `logbook migrate` once before any other command will read or write them (SPEC §3.1).
- Format `logbook/0.2` (SPEC §3.1, ADR 0014): `canonical_json` is now RFC 8785 exactly (UTF-16 key order, ECMAScript float layout; tested against the RFC's vectors). 0.1 hashed floats such as `0.0`, `120.0` and `1e-06` differently, so `verify` and every writer refuse a 0.1 record; `logbook migrate` recomputes `prev`/`hash` in seq order, keeps everything else, records `lineage` in `logbook.json`, appends one `migration/v1` line, keeps the 0.1 files at `logbook-0.1/`. The conformance sample is 0.2.
- `index.sqlite`: a disposable SQLite locator of the files (ADR 0001, 0007) — `logbook index` builds it in one streaming pass; `show`, `retract`, `export --day/--days` and `add`/`sync` dedupe go through it and rebuild it when it is missing or stale; `append`/`append_many` extend it at each checkpoint; `verify` and whole-log `export` never read it. `show` now lists a local day (the owner's timezone) with local clock times, as `export --day` always did.
- `sync <source> [--since RFC3339] [--dry-run]` pulls from a live source through the new live-adapter contract (`configure`/`pull`) and keeps its watermark in `state/`; first live adapter: `immich` → `photo/v1` (RFC 0002), stdlib urllib only.

## 0.2.0 — 2026-09-15
- Docs site (MkDocs Material) deployed from main; reproducible demo tape.
- Package published as `openlogbook`; the command is `logbook`.
- `init` and `find` refuse a code checkout (#12).
- `export --day DATE` / `--days FROM TO` write `day-package/v1` directories (ADR 0013 §4); `export/` is ignored.
- `add` takes several paths (`logbook add a.json b.json some/dir`); a path that does not exist is an error (exit 2), never a note.
- `retract SEQ "reason"` writes a `retraction/v1` line that supersedes SEQ (SPEC §3); `show` hides the retracted line behind a marker, `export --day` keeps it and adds `retracted_by`.
- `export --days` reads the log once for the whole range instead of once per day.

## 0.1.0
- Format v0.1: folder layout, envelope, hash chain, tiers, conformance rule.
- CLI: init, add (text or JSONL), show, verify, export.
- Conformance fixture with expected head.
