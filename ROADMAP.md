# Roadmap

Phases, not dates. Each phase ends with something a stranger can use.

**0 — the format (now).** SPEC v0.1, JSON Schema, conformance fixture, this CLI. Verify passes on the sample logbook.

**1 — three drops.** Adapters for Google Takeout (location, photos, calendar), Apple Health (sleep, steps, workouts) and WhatsApp exports (messages, tier 2). `logbook add <zip>` sniffs which is which. Encryption at rest for tiers 2–3 (spec v0.2).

**2 — days.** The reference engine: stays, moves, flights, places, meetings, people, trips. `logbook show <day>` becomes a page. The MCP server ships, so any agent can add, ask and confirm.

**3 — the circle.** The shared-page bundle format; exchange between two logbooks by file; then a transport. Per-person pages: last real contact, shared moments, birthdays.

**4 — the community.** Adapter template and bounty list (Strava, Garmin, Immich, Dawarich, Telegram, iMessage, bank CSV, Spotify, Letterboxd). Payload-profile RFCs. A second implementation in another language by someone who only read the spec.

**5 — v1.0.** The envelope frozen; conformance badge; books and published pages as community layers; data-portability law gives every service a reason to emit the format.
