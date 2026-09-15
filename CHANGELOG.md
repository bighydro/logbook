# Changelog

## 0.1.0
- Format v0.1: folder layout, envelope, hash chain, tiers, conformance rule.
- CLI: init, add (text or JSONL), show, verify, export.
- Conformance fixture with expected head.

## Unreleased
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
