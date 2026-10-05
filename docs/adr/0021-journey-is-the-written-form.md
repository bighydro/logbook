# ADR 0021 — `journey/v1` is the written form of RFC 0020

Status: accepted · 2026-10-05

**Context.** ADR 0019 rule 4 says RFC 0020's `trip/v1` "keeps its name". RFC 0031 (the profile freeze) renames it `journey/v1` for new lines, so that *trip* names the derived trip alone, and asks whether a one-sentence ADR is worth its number.

**Decision.** That one sentence of ADR 0019 rule 4 is superseded, and only it: a bought movement or a metered stop (RFC 0020) is written as `kind: "journey"`, `payload.schema: "journey/v1"` from this date; readers accept `trip`/`trip/v1` and `journey`/`journey/v1` as one profile; nothing is migrated (SPEC §3). Everything else in ADR 0019 stands: a trip is derived, never written, and has a derived id.

**Consequences.** `easypark`, `sbb` and `passages` write `journey`; `show` and `search` read both; RFC 0020 carries the amendment; a record holds both spellings for as long as it holds its old lines.
