### Added
- `logbook import pickup FOLDER [--write] [--source NAME] [--tier N] [--keep]` moves a folder of call
  transcripts collected from the receiving side (the Purser's) into the record: one transcript line per
  file through the transcript adapter, each with its own source, its text stored, where it came from under
  `extra.picked_up`. A file already taken is skipped by its hash; a dry run unless `--write`, which removes
  each file taken from the folder unless `--keep` ([the pickup](docs/crossing.md#the-pickup)).
