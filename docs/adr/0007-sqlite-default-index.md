# ADR 0007 — SQLite is the default index

Status: accepted · 2026-09-13 · extends ADR 0001

**Decision.** Engines index the log in SQLite (with R*Tree for spatial queries) by default. PostGIS is a plugin for installations that want it. The index is disposable and rebuilt from the files at any time.

**Consequences.** `pipx install` gives a complete, working system with no server. Anyone who deletes the index loses nothing.
