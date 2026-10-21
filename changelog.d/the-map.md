### Added
- The map: one offline OpenStreetMap file (a PMTiles v3 vector extract, a Protomaps build you put on the
  home machine) drawn by the server as inline SVG, light and dark, no script and nothing fetched, the
  OpenStreetMap attribution on every map. `logbook setup map PATH` names the file after reading its
  header (`--off` removes it); `logbook lab map render --bbox … [--track DAY]` draws one to check by eye;
  for an unnamed stay the map proposes the named thing within 50 m. No page draws it yet
  ([the map](docs/map.md), RFC 0043 §11).
