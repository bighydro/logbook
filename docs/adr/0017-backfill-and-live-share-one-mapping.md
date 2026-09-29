# ADR 0017 — Backfill and live share one mapping

Status: accepted · 2026-09-29

**Context.** Most sources reach the record twice. First as a backfill: an export, a backup, a folder of files the owner already holds, read once by `logbook add`. Then live: the same service asked for what is new by `logbook sync`, night after night. `dawarich` was the first source built both ways (an export and `GET /api/v1/points`), `imessage` reads the same store from a backup and from the Mac it lives on, and the transcript sources that follow — Granola now, others later — all have an export and an API. Written as two adapters with two mappings, the same observation arrives twice with two shapes and two ids, and every reader downstream has to know which half of the history came from which path.

**Decision.** A source is one mapping with two entrances.

1. **Every source adapter has a file mode** (`NAME`, `sniff`, `run`) that reads what the owner already holds: an export, a backup, a folder. **Where the source offers it, the same adapter has a live mode** (`configure`, `pull`, `watermark`) that `logbook sync <NAME>` runs. A source without an API has the file mode only; a source without an export format still has the file mode, reading the interchange JSON of its profile (a `logbook export` line minus the chain fields), so a line can always be re-added from a file.
2. **Both modes produce identical lines with the same `raw_id`.** One function is the mapping, and both modes call it; the live mode hands it what the API returns, the file mode what the file says. Dedupe on `(source, raw_id)` in `append_many` then makes a backfilled line and the same line pulled live one line: import the history from the export once, let `sync` carry on from there, and re-run either in any order without a duplicate.
3. **The mapping owns the identity.** `raw_id` comes from the source's own stable id when it has one (`<tracker_id>:<timestamp>`, `granola:<note id>`), else from the content (`<source>:<sha256 of the file bytes>`). It never depends on which entrance the item came through, on a file name, or on the record it lands in.
4. **What the API gives beyond the file is ignored, not mapped twice.** Fields the file mode cannot see (a server-side row id, a processing status) stay out of the line, so the two modes cannot drift apart. What only the API can give and the file cannot — a derived summary, a later edit — is a separate line that points at the shared one by id, never a variant of it.

This is the rule for every adapter from now on. `dawarich` (`dawarich.draft`, called by the export reader and by `dawarich_live`) and `imessage` (one reader for the backup's `sms.db` and the Mac's `chat.db`) are the existing examples; `transcript` + `granola` is the first written under the rule (`transcript.draft` is the mapping; the file adapter and `logbook sync granola` both call it).

**Consequences.**
- An adapter's test suite has one test more: the file fixture and the same items served by a fake of the API must come out as equal drafts. A live adapter without a file counterpart, or a file adapter with a live sibling that maps differently, is a bug.
- A first `sync` can resume from the record's newest line of its source and kind (`Index.newest`), because the backfilled lines are the same lines it would have pulled.
- A live mode's extra lines (Granola's summary as `note/v1` with `extra.derived_from`) need the id of the shared line whether that line is being written now or was backfilled months ago, so `append_many` keeps an `id` a draft brings and a live adapter may ask the record for one (`lookup`) before it mints its own.
- The interchange JSON of a profile is a first-class file format for its adapter, not a debugging aid: it is how a line leaves and re-enters the record without an API.
