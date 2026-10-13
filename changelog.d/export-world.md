### Added
- `logbook export world [--out DIR] [--from DATE --to DATE] [--tier 1|1,2|1,2,3]`: the record as one
  self-contained HTML page, a globe you can scrub ([the world](docs/world.md)). On a canvas, with no WebGL
  and nothing fetched: the world's outline from Natural Earth's 1:110m land (public domain, bundled under
  48 KiB as `logbook/tables/land.json`, written by `scripts/make_land.py`), the places of `places.json` as
  anchors, the assets of `assets.json` as dots moving along their own tracks, your stays as dots (aboard,
  you ride with the boat), the `journey/v1` lines as tracks, and a time scrubber at the bottom that moves
  everything, the standing `chapter/v1` lines as bands on it. Clicking an anchor or an asset opens its
  summary: nights, journeys, photos, the first and last day. The record's part of the page is one JSON
  block under 1,000,000 bytes, the tracks thinned to fit (never the counts); every id it refers to is
  checked before the page is written, and no coordinate is more precise than the record's own (a stay's
  centre to the fewest decimals of the fixes inside it, four at most). Tier-gated like an export: tiers 1
  and 2 by default, under a new `world` entry of `policy/crossing.json` (2 when the file does not name
  it); every export appends one `crossing/v1` line, and a re-run over an unchanged record rewrites
  nothing.
- `logbook serve`: the same page at `/world` (`?from=&to=` narrows it), its one script named by its hash
  in the page's Content-Security-Policy, and `world` in the Library's navigation.
