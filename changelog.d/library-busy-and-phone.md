### Changed
- `serve` answers a busy record one way: while another command holds the writer lock, every act of the
  Library (the Places, Journeys and People forms, the Manifest's review and status, the Day's Reflect,
  Sign, star and *with…*) is a `409` with one sentence, *Another command is writing to the record;
  nothing was written. Try again in a moment.*, the command that holds the lock, and the form you sent
  kept to send again (a recording is chosen again). Nothing is written.
- Every page `serve` serves fits a phone's 400 px column: on the Day, the days, trips, places, assets
  and gaps a wide table scrolls inside its own box, and the Places queue's maps and the World page's
  canvases keep to the column. One test walks every page from `/` and holds each to it, the Day
  among them.
