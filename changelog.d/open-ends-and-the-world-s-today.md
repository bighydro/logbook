### Fixed
- The World's time slider ends on today, not on the latest line the record holds: one calendar entry
  in 2055 no longer stretches it thirty years into the future. `--from` and `--to` still reach any
  day, the future included.
- `/gaps` in the Library counts each silence to the server's own clock, so the same page read twice
  is the same page (the slow test that turned `main` red on 1dd86c2).
