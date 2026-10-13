### Added
- `logbook setup places review --ask-photos`: the places the review proposes as blanks get the names
  your photo libraries hold for the photos already in the record, counted by photo and named by source
  (`immich ×12: Havbyen`, `photos ×3: Plattformen`) ([Ask the photos](docs/places.md#ask-the-photos)).
  Immich is asked by asset id through the client `sync immich` uses (`GET /api/assets/{id}`, your own
  server and key, at most 10 a second); Photos is read from the library on this machine
  (`--photos-library PATH`). Your photos' asset ids go to your own Immich server and nothing else
  leaves the machine: no coordinate, no name, never a geocoder; no line is written. The 50 photos
  nearest each place's centre from each library (`--limit N`); `--all` asks about the places that
  have a name too. Before anything is sent it says how many photos it will ask about and where; a
  library that fails is said once and the review goes on. Answers are kept 30 days in
  `state/places-photos.json`. `--accept` and `--reject` work as before, on the same numbers; without
  the flag the review is unchanged.

### Adapters
- `immich.place` asks the server for one asset's place by id, and `apple_photos.places` reads the
  places Photos named for given assets from a library, its schema confirmed first.
