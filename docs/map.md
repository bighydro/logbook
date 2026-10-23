# The map

The Library draws its maps itself: one OpenStreetMap file on the home machine, read by the server and
drawn as inline SVG in the page. No script, no tile server, nothing fetched when a page is read; light
and dark both; the OpenStreetMap attribution on every map. This is the map of RFC 0043 §11, which the
Day page and the timeline will draw once they call it; until then `logbook lab map render` draws one to
a file, to check by eye.

## Getting the file

The Library never downloads the map. Getting it is your step, once, on the home machine:

1. Install the `pmtiles` command-line tool (github.com/protomaps/go-pmtiles, a single binary).
2. Cut the region you live and travel in out of a Protomaps basemap build (maps.protomaps.com/builds
   lists them; each is the whole planet as one PMTiles v3 file, read over the network by ranges, so
   only your region is downloaded):

   ```bash
   pmtiles extract https://build.protomaps.com/20261001.pmtiles ~/Maps/oslo.pmtiles \
       --bbox=10.4,59.8,11.0,60.1 --maxzoom=15
   ```

   A city is some hundreds of MB; a region or a small country is a few GB. Keep it outside the record
   folder: it is not the record, and a backup of the record need not carry it.
3. Name it:

   ```bash
   logbook setup map ~/Maps/oslo.pmtiles
   ```

   `setup map` reads the file's header first (a PMTiles v3 file, vector tiles, gzip), prints what the
   file holds and the change it will make to `logbook.json`, and asks. `--yes` writes without asking.
   `logbook setup map` alone says which file is set; `logbook setup map --off` removes the setting and
   leaves the file where it is.

| setting | where | set with |
| --- | --- | --- |
| the map file | `logbook.json`, `map_file` | `logbook setup map PATH`, `--off` to remove |

Like `day_start`, it is a setting, not a line: nothing is appended, no hash changes, and the index is not
rebuilt. Without it, everything that would draw a map says one sentence instead:

> No map file is set: `logbook setup map PATH` (docs/map.md)

## Drawing one by eye

```bash
logbook lab map render --track 2026-06-08 --out day.svg             # the day's track, the box round it
logbook lab map render --bbox 10.70,59.90,10.76,59.92 --width 390   # one box, printed as SVG
```

`--width` is in pixels (390, a phone, by default); the height follows from the box. `--track DAY` draws
the day's track as the Day page numbers it: each stay or stop with a position, in order, one pin for one
place however often you were there (two stops closer than a pin on the map are one pin), a straight move between two of them, dashed across a flight, a gap
or a stay with no position. A box west of Greenwich or south of the equator is given with `=`:
`--bbox=-0.2,51.4,0.0,51.6`. The command reads the map file and, with `--track`, that day of the record,
and writes only the SVG.

## What a map holds

From the bottom: the land; land use and parks; water; piers; buildings, close in (a display zoom of
14.5 or more); roads by class, the widest on top; place names, the most important first, a name left out
where it would cover another, a pin or the attribution; then the track and its numbered pins; and the
attribution, `© OpenStreetMap contributors` and what the file's own metadata names (Protomaps' builds
name themselves there), on every map.

The zoom follows the box and the width: the tiles of the whole zoom below the one the box asks for,
within the file's zooms (past its last, its last is drawn larger), 36 tiles at most of those inside the
file's bounds; a box that needs more even at the file's first zoom is refused in one sentence, never
drawn with a part missing. Each shape is
clipped to its tile and to the map, simplified to half a pixel and rounded to a tenth, and every shape of
one kind is one SVG path. A map stays under 300 KB: when everything would be more, the buildings go
first, then the footpaths, the minor roads and the land use, each with a coarser simplification; the
track, the pins and the attribution are never left out. A damaged or hostile file cannot make a map
slow: what one map draws and how long its simplification may look are both capped.

The colours are CSS custom properties with their defaults in the map's own `<style>`, one set for light
and one for dark (`prefers-color-scheme`): `--map-land`, `--map-landuse`, `--map-park`, `--map-water`,
`--map-building`, `--map-road`, `--map-road-major`, `--map-path`, `--map-rail`, `--map-label`,
`--map-halo`, `--map-track`. A page that sets them draws the map in its own colours. Names are in the
system's sans-serif.

## Naming a stay from the map

For a stay with no name in `places.json`, the map can propose one: the named thing nearest the stay's
centre within 50 m (`logbook.contrib.map.nearest.nearest_named`), a restaurant, a pier, a marina, a named
building, with its kind and how far it is. It is a proposal, shown in grey by places review and the
timeline when they read it: nothing is written until you name the place yourself. Roads, a town's point
and stretches of water are never proposed.

## The file, read

The reader is the standard library alone (`logbook/contrib/map/`): `pmtiles.py` reads the PMTiles v3
header, its root and leaf directories and a tile by z/x/y, gzip through zlib; `mvt.py` decodes a Mapbox
Vector Tile from the protobuf wire format by hand. A file cut short, damaged or made to mislead (a
section past its end, a directory that counts more than it holds, leaves that nest without end, a tile
that inflates without end) is one error naming the file, never a traceback or a hang. Brotli or zstd
archives are refused by name: Protomaps' builds are gzip.
