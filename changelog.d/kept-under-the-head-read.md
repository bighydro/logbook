### Fixed
- A Library page read while a sync was between `logbook.json` and the index no longer keeps that earlier
  reading as the record's: what the server shares between pages, the Day's readings and the morning's
  replies owed and revisits are kept under the head the index held, and the review pages' tables of
  observed people, orgs, ideas, assets and places are stamped with it, so the next page after the sync
  reads the new line. The tables live in the index, so a restart no longer kept the earlier one either.
  The page's footer and the built pages' record name that head too.
