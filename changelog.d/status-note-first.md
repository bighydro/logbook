### Fixed
- `status KIND ENTITY DISPOSITION --reason "…"` for an idea, a place or an asset writes the reason's
  `note/v1` first and then the `status/v1` line, whose `note` names it, as RFC 0037 §10.5 says; it
  wrote them the other way round, the note naming the status under `extra.status` and carrying the
  disposition. The note now carries the words and the entity only. A pair written the old way is read
  the same, and `status list --json` names each status's note (`note`). An org's status is unchanged:
  one tier-3 line, the reason on it, no note ([the profiles](docs/entities.md#statusv1)).
