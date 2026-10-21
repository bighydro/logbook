### Added
- `logbook search` marks a hit that a later line of its kind supersedes: the row ends
  `· superseded by #N`, and `--json` gives every hit `standing` and `superseded_by`; `--standing`
  shows standing hits only, still filling `--limit` ([search](docs/search.md)).
