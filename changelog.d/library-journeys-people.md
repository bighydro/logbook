### Added
- `logbook serve` has two new shelves, phone first (a 400 px column), every derived row with its
  evidence folded (what it rests on, the day, the line ids). **Journeys** (`/journeys?year=`): the trips
  that began in a year, the latest first, each with its name or dates, nights away, return day, route,
  photos, places, the people the record names (the unplaced counted, a link to the review) and the
  journey's draft folded; one journey (`/journeys/FIRST/LAST`) with its stays as dots on a plain canvas
  drawn by the server (no tile host), its days one row each linking the Day, and the promises made on it
  ([serve](docs/serve.md#journeys)). **People** (`/people?year=`): the people the record names, by days
  together this year, then the last real contact; one person (`/people/ID`) with days together by year,
  the last real contact and what it was, drift and why, promises both ways, the coming month's
  anniversaries and the places shared ([serve](docs/serve.md#people)).
- `logbook add --trip ID-OR-DAY "NAME"` names a journey (ADR 0019): one `note/v1` line in your words,
  label `name`, the id under `extra.trip`, dated inside the journey. The Journeys page's *Name this
  journey* writes it through the same function, byte for byte.
- The People page carries the review queue of `people review`, the one place an observed person appears:
  **Merge** writes what `--accept N` writes and **Not the same person** what `--reject N` writes,
  through the same functions. Like the Places page's form, both acts and the naming are answered from
  this machine only (a loopback client, an `Origin` of 127.0.0.1), one at a time, under the record's
  writer lock without waiting for it: another command writing is a `409`, nothing written.

### Changed
- `serve`'s navigation wraps on a narrow screen and names *journeys* and *people* (`/trips` stays, from
  the front page). A draft of a journey (RFC 0036, `unit` `journey`) is read by its id: a `subject` that
  is the trip's id, or an array naming it. It follows the `dream` entry as a day's draft does: one above
  the entry's `max_tier` today is not shown, and the journey's row and page say `superseded by policy`
  and why, nothing of its text.
