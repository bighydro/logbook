### Added
- EXPERIMENTAL: the relationship reader asks a real model. `people ask NAME QUESTION [--show-prompt]`
  sends one person's lines to the model the dream uses (`LOGBOOK_DREAM_ENDPOINT`, `LOGBOOK_DREAM_MODEL`,
  `LOGBOOK_DREAM_KEY`) under its own entry, `relationship` in `policy/crossing.json`, with a `max_tier`
  of 1 or 2 (3 is refused while the model is a cloud one), a required `until`, an optional `model` and an optional `include_unsigned`; without the entry, or after its day,
  nothing is sent and one sentence says so. Only lines at or under the entry's `max_tier` cross, only of
  signed days unless the entry says otherwise, each as a reference with the promises read in its words,
  and the names that say whom a line is with are held to the same ceiling. Every claim of the answer
  cites lines of the person or is listed under `unsupported`; the answer is never written. The key is
  never said in an error ([the relationship reader](docs/relationship.md)). Slice 0's `people ask`, which
  refused for want of a model, now asks this one.
- `dream person NAME [--window FROM TO]`: one `draft/v1` line of unit `person` (RFC 0036 amendment 1),
  written as the day's draft is (`policy_version`, evidence of the person's lines only or unsupported,
  `supersedes`, nothing written twice at the same head over the same window), under the `relationship`
  entry and refused without it.
