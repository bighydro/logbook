# ADR 0004 — Human notes live in the Logbook

Status: accepted · 2026-09-13

**Context.** External tools (a notes app, a places database) could own the human-written meaning about places, people and days, with the Logbook holding only machine facts.

**Decision.** Notes, confirmations and visibility choices are written into the Logbook as tier-2 lines. External tools may receive exports; they are never the source of truth for anything a person wrote here.

**Consequences.** Export to other tools is one-way. A note survives any recompute and any export because it is a line in the chain, not a field in someone else's database.
