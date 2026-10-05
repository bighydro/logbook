### Profiles and spec
- `trip/v1` is written as `journey/v1` for new lines (RFC 0031, ADR 0021): `easypark`, `sbb` and `passages` write `kind`
  `journey`, `schema` `journey/v1`; `show` formats both spellings the same way and `search --kinds trip` or `--kinds journey`
  finds both. Nothing is migrated: a `trip/v1` line already in a record stays as it is. RFC 0020 carries the amendment and
  is marked *parked · may change before v1.0*.
