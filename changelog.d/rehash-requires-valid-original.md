### Fixed
- `seal` and `migrate` now refuse a record whose original hashes do not verify: `key seal --all` and
  `repair migrate` check every hash, under the rule the record was written with, and every link across the
  whole record before a line is rehashed, verify the new files before they replace the old, and on a
  failure name the first failing line and its id and change nothing.
