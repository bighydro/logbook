### Fixed
- `add transcript` stores the file a transcript/v1 JSON's `content` reference names when the export holds
  it (at the reference's own path, `attachments/<sha256>` or `<sha256>` beside the JSON; a spans file
  too), so Granola's and Fireflies' exports no longer leave a missing attachment behind. Bytes that do not
  hash to the reference are refused and counted; adding an export again fills the store for lines
  already in the record and writes no line ([the attachment store](docs/attachments.md#transcripts-what-the-export-holds)).
### Added
- `logbook doctor --attachments` lists the lines whose attachment the store lacks, by source.
