# ADR 0008 — The first three adapters

Status: accepted · 2026-09-13

**Decision.** The first adapters shipped by the project are, in order: Google Takeout (location history, photos metadata, calendar, mail headers, YouTube and Chrome history from one archive), Apple Health (sleep, heart, steps, workouts and routes), and WhatsApp chat exports (tier 2). An email adapter is in scope and tracked as a task, not left as a table row.

**Rationale.** Three drops cover location, photos, calendar, health and messages for most people. Takeout alone is six witnesses in one zip.

**Consequences.** Every other source is a community adapter from the template. The "wanted" list lives in `adapters/README.md`.
