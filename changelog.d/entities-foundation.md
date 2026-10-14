### Added
- `logbook review KIND` (RFC 0037): one sitting for the five kinds of thing the record names —
  `person` (= `people review`), `org`, `idea`, `asset`, `place` (= `setup places review`), the two
  old commands printing the same as before, byte for byte ([review](docs/review.md)). The org queue
  is the registered domains of your mail and calendar (a public provider and your own domains name
  nobody's org), the code-host orgs of the pages and tasks, the group chats and the recurring
  merchants; the idea queue the Notion roots, the repositories and the recurring titles; the asset
  queue the track subjects and aircraft registrations the registry does not name; each proposed
  against what you named with the evidence, or as a new one. `--accept`, `--name N "…"`, `--reject`,
  `--all-above`; nothing written unless told, nothing looked up. `review` alone lists every queue.
- `logbook status KIND ENTITY DISPOSITION [--reason "…"] [--at DATE]`: what you decided about an
  org (`hold`, `add`, `sell`, `let-go`, `exited`, `passed`), an idea (`spark`, `exploring`, `build`,
  `built`, `killed`), a place (`let-go`) or an asset (`sold`, `let-go`), one `status/v1` line, no
  money on it, tier 3 for an org (its dispositions describe a position in money) and 2 for the rest;
  `--reason` also writes your words as a `note/v1` at the same tier. A place let go and an asset
  sold close their registry entry with `until` and keep it. `status list KIND` says the current
  status of each, the stale ones and the proposals muted for a year by a status you gave a reason.
- Three profiles in draft with RFC 0037 ([the profiles](docs/entities.md)): `entity/v1` (an org,
  an idea, an asset or a place, and the refs that are it; tier 2, never citing a tier-3 line),
  `entity-review/v1` (every no, for every kind) and `status/v1`. A `resolution/v1` of type
  `company` is read as an org. `policy/entities.json` holds the public mail providers and the
  review's thresholds.

### Changed
- `people review --reject` writes an `entity-review/v1` line of type person; a `people-review/v1`
  line is read as the same no, forever.
- `setup places review --migrate-rejects` writes the pairs `state/places-review.json` holds as
  `entity-review/v1` lines of type place, once; the file is then a cache of those lines as well.
  `--reject` keeps the pair in the file, never a line; `review` says how many are not lines yet.
- What the sources saw is one table in the index, `observed_entities`; `observed_people` and
  `observed_places` are views over it for one release. The index is rebuilt once, on the first
  command after the upgrade.
