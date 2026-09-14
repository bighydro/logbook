# Changelog

## 0.1.0
- Format v0.1: folder layout, envelope, hash chain, tiers, conformance rule.
- CLI: init, add (text or JSONL), show, verify, export.
- Conformance fixture with expected head.

## 0.1.1 (unreleased)
- Docs site (MkDocs Material) deployed from main; reproducible demo tape.
- Package published as `openlogbook`; the command is `logbook`.
- `init` and `find` refuse a code checkout (#12).
- `export --day DATE` / `--days FROM TO` write `day-package/v1` directories (ADR 0013 §4); `export/` is ignored.
