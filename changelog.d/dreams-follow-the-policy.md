### Fixed
- A draft follows the `dream` entry of `policy/crossing.json`, not only the head: a draft above the
  entry's `max_tier` today (the ceiling lowered, the `until` passed, the entry removed) is no longer
  shown on the Day, on `serve`'s Day page or through the MCP door, though no line was appended. The Day
  says `superseded by policy` and why in one row, and nothing of the draft's text (`draft_withheld`
  under `--json`); the door holds it back from every tool and counts it with the lines above its
  ceiling; `doctor` warns, naming the days. Every draft now records the version of the entry it was
  dreamed under (`extra.policy_version`, the SHA-256 of the entry's `max_tier`, `until` and `model`),
  and `dream --catch-up` dreams a day again when its draft is above the entry or was dreamed under
  another version of it, superseding the old draft; an expired entry still dreams nothing. The old
  draft stays in the record ([the dream](docs/dream.md), *When the entry changes*; ADR 0016).
