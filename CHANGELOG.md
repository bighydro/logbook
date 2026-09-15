# Changelog

## 0.1.0
- Format v0.1: folder layout, envelope, hash chain, tiers, conformance rule.
- CLI: init, add (text or JSONL), show, verify, export.
- Conformance fixture with expected head.

## Unreleased
- Format `logbook/0.2` (SPEC §3.1, ADR 0014): `canonical_json` is now RFC 8785 exactly (UTF-16 key order, ECMAScript float layout; tested against the RFC's vectors). 0.1 hashed floats such as `0.0`, `120.0` and `1e-06` differently, so `verify` and every writer refuse a 0.1 record; `logbook migrate` recomputes `prev`/`hash` in seq order, keeps everything else, records `lineage` in `logbook.json`, appends one `migration/v1` line, keeps the 0.1 files at `logbook-0.1/`. The conformance sample is 0.2.
- `sync <source> [--since RFC3339] [--dry-run]` pulls from a live source through the new live-adapter contract (`configure`/`pull`) and keeps its watermark in `state/`; first live adapter: `immich` → `photo/v1` (RFC 0002), stdlib urllib only.

## 0.2.0 — 2026-09-15
- Docs site (MkDocs Material) deployed from main; reproducible demo tape.
- Package published as `openlogbook`; the command is `logbook`.
- `init` and `find` refuse a code checkout (#12).
- `export --day DATE` / `--days FROM TO` write `day-package/v1` directories (ADR 0013 §4); `export/` is ignored.
- `add` takes several paths (`logbook add a.json b.json some/dir`); a path that does not exist is an error (exit 2), never a note.
- `retract SEQ "reason"` writes a `retraction/v1` line that supersedes SEQ (SPEC §3); `show` hides the retracted line behind a marker, `export --day` keeps it and adds `retracted_by`.
- `export --days` reads the log once for the whole range instead of once per day.
