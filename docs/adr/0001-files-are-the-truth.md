# ADR 0001 — Files are the truth; databases are caches

Status: accepted · 2026-09-13

**Context.** The private predecessor stored the log in Postgres/PostGIS and mirrored it to JSONL. A standard cannot require a database server.

**Decision.** The JSONL files under `logbook/<YYYY>/<MM>.jsonl` are the record. Any database is a derived index that may be deleted and rebuilt. `verify` and `export` read files only.

**Consequences.** Engines that need spatial queries bring their own index (SQLite + R*Tree by default; PostGIS as a plugin). Chain order is `seq`, not file order, because backfilled history lands in old month files.
