### Fixed
- `export crossing` ships the resolution lines that name a mail's addresses (`from`, `to`, `cc`, `bcc`)
  and a transcript's participants (email, phone, provider id) in `resolution.jsonl`, as it did for a
  message's sender and a calendar guest; before, a mail or a transcript crossed with nobody on it named
  ([the crossing](docs/crossing.md), RFC 0005).
