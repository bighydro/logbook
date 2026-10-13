### Added
- `logbook serve`'s Places page asks you to name the places you return to: the named places first (nights,
  last visit), then the review queue of `setup places review` in its order, twenty a page, each cluster
  with a dot on a plain canvas drawn by the server (the spot, its radius, the nearest named place and
  distance; no tile host), its facts, its evidence folded, a field prefilled with the best proposal, and
  Name, Skip and Not a place (Enter, Space, `n`). Name and Not a place go through the review engine's own
  `accept` and `reject`, so `places.json`, the naming note and `state/places-review.json` are byte for
  byte what `--name`, `--accept` and `--reject` write; the page is read again after each write. The
  Library's first write act: the form is answered only from this machine (a loopback client, and a
  browser `Origin` of 127.0.0.1 when one is sent), else `403` and nothing written
  ([serve](docs/serve.md#places--name-this-place)). A Day's stay printed as coordinates links to its
  cluster there (*name this place*).
- `setup places review` folds its evidence: the addresses one source wrote along one street are one line
  (`dawarich: "Plattformveien" (38 addresses, 217 stays)`), three lines are shown and `… and N more`
  counts the rest; `--verbose` prints every name as before. The Places page shows the same folding, from
  the same code.
