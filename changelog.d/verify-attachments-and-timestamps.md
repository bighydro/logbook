### Fixed
- `verify` walks the attachments the lines name (SPEC §1.1), as it always said it would and never did:
  a file the store does not hold is listed under `attachments:` with the first line that names it and
  is not an error; a present plain file whose bytes do not hash to its name is an error naming the line,
  hashed by default (`--no-attachment-digests` leaves present plain files unhashed on a large store);
  with the identity, a sealed file is opened and a plaintext that does not hash to its name, or a file
  that does not open, is an error, which no flag skips. A missing file, a corrupted plain one and a
  sealed one swapped for valid ciphertext of other bytes all passed before. `doctor` looks for the same
  files and counts the missing ones in its `record` line, without hashing them.
- Timestamps must be RFC 3339 instants. `append` took any `at`, `end` or `recorded_at` ending in `Z`, so
  `not-a-dateZ` was written, `verify` said nothing, and the index rebuild then failed; it refuses one now,
  and `verify` reports one a line already carries as an error naming the line. A valid stamp is still
  written exactly as given (it is hashed as written), and one with a numeric offset is still converted.
