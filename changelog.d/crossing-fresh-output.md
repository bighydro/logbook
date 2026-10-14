### Fixed
- `export crossing` builds every bundle in a fresh folder beside `--out DIR`, checks it against its own
  manifest and renames it into place, replacing DIR whole. A second export into the same folder used to
  overwrite only the files it wrote, so a tier-1 crossing into the folder of an earlier `--tier 1,2` one
  left the earlier `resolution.jsonl` and tier-2 attachments beside a manifest that said there were none.
  The manifest now lists every file of the package under `files` (path, sha256, bytes). A DIR that exists
  and is not an earlier bundle is refused before anything is written, unless `--force`; the record, a
  folder that holds it and any path in it outside `export/` are refused even then. A failed export
  leaves DIR as it was. `export trip-bundle` writes the same way and takes `--force` too
  ([the crossing](docs/crossing.md#the-output-directory)).
