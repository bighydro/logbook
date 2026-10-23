### Changed
- `logbook serve` answers every door and shelf from pages built ahead of time, at the 06:00 close and
  after every act on a page, instead of reading the record while you wait; a built page says when it
  was built in its footer. Today's Day is always current. `serve --build` builds them now, `serve
  --live` renders every page as it is asked for. The pages are kept beside the index, never in the
  record's folder, readable by you alone.
