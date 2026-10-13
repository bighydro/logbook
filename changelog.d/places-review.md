### Added
- `logbook setup places review [--top N] [--near PLACE]` (`logbook places review` still answers): the
  places you return to, named in one sitting from what the record already knows, offline
  ([places](docs/places.md#review)). An observed place is a cluster of your stays within 75 m
  (`--radius`), with its visits, nights, first and last visit and hours, ranked by nights then hours;
  a derived table in `index.sqlite`, rebuilt when the record or `places.json` changes, never a line.
  Each is proposed with the name its sources already gave it — a Google Timeline place visit's name
  and address, a home or work type, the place a photo's library named, a calendar entry's location
  held during the stay, a name Dawarich's geocoder wrote on the stay's points — and which source said
  which name how often; a blank where none did. `--accept N[,N]` writes the place into `places.json`
  at the cluster's centre with a fitted radius and puts the naming in the record as `places name`
  does; `--name N "…"` uses your own name; `--reject N[,N]` records the pair in
  `state/places-review.json` so it is not proposed again. On a terminal it asks y, n or a name for
  each. Nothing is accepted on its own, no geocoder is asked, and no coordinate leaves the machine.

### Adapters
- `takeout-location` reads the Semantic Location History of a Takeout archive (`placeVisit`, which
  carries the place's name and address, and `activitySegment`), and the iPhone's own Timeline export
  (`location-history.json`, a top-level array); the docs give the steps to export Timeline from the
  phone.
- `immich` keeps the city, state and country Immich gave a photo under `extra.place`; `apple-photos`
  keeps the address, city and area names Photos gave it (`ZREVERSELOCATIONDATA`) under `extra.place`.
