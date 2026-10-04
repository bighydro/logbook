"""The core tier: the format and what is frozen with it.

Canonicalisation and the hash chain (`chain`), the record and its index (`store`, `index`,
`search`), the attachment store (`attachments`), the policies and the privacy tiers (`policy`,
`crossing`), the day package (`export`), and the readers whose JSON a second implementation is held
to (SPEC §3.2, §6.1): the stays (`stays`), `day`, `days`, `trips`, `year`, `people`, the pages
(`pages`), `places`, the rollups (`rollup`, `listen_rollup`, `drifting`, `ledger`) and what they
read through (`reading`, `present`, `resolve`, `flights`, `events`, `health`, `keepers`, `story`,
`weather`, `countries`, `apps`, `assets`), the shared page (`share`) and `repair`. Core imports
core and nothing above it (`logbook/layout.py`)."""
