### Fixed
- `derive flights` counts a draft merged into a flight already in the record as a merge, not as a new
  flight, so its dry run and its real run tell the same counts (`0 new flights … also 3 merged` for the
  demo, which said `3 new flights`). Two numbers for one leg met in the same run are one new flight and
  one merge into it, no longer a merge "into a flight already in the record" (#109, #458).
