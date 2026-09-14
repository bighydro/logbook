# ADR 0011 — Log everything that is cheap; judge everything downstream

Status: accepted · 2026-09-14

**Context.** Real sources are noisy: most email is bulk, most photos are not worth showing, screenshots are neither photos nor junk. The temptation is to filter at ingest.

**Decision.** Ingest is not the place for taste. An adapter records every item the source offers, as cheaply as possible (metadata first; bodies and pixels only where the tier and the source allow), and attaches a *classification* it can compute from the item itself — `class` for mail, `provenance` and `faces` for photos. What is shown, hidden, summarised or queued for review is decided by later passes, which are versioned and can be re-run over all history when the rules improve.

Two exceptions: (1) an adapter never reads what the source itself has already judged as junk — spam folders, trash, deleted items; (2) the *body* of an item classed as bulk or automated is never logged, only its header line.

**Consequences.**
- Mail is a headers-first adapter: one small line per message with `class ∈ {human, bulk, automated}`; bodies (tier 2) only for `human`.
- Photos: one line per asset with `provenance ∈ {camera, received, screenshot, other}` and a face count. Faces surface on the day by default; screenshots and `other` feed a review pass that drafts what the image says about the day.
- A classification rule is data plus a version, never a hard-coded decision in the adapter's control flow, so it can be reconsidered.
