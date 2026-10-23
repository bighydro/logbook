"""The map of RFC 0043 §11: one offline OpenStreetMap file on the home machine, drawn by the server as
inline SVG. No script, nothing fetched, no tile server: the file is a PMTiles v3 archive of Mapbox Vector
Tiles (Protomaps' basemap builds), named by `map_file` in `logbook.json` and read here with the
standard library alone.

- `pmtiles`: the archive — its header, its root and leaf directories, a tile by z/x/y, gzip by zlib.
- `mvt`: one tile — the protobuf wire format read by hand: layers, features, geometry, keys and values.
- `svg`: a bounding box and a width in pixels made into one `<svg>`: water, land use, parks, roads by
  class, buildings close in, place labels, then the day's track and its numbered stops, and the
  attribution on every map.
- `nearest`: the named thing the map holds nearest a point, within 50 m, as a proposal for an unnamed
  stay; nothing is written.

The Library never downloads the file: getting it is the owner's step on the home machine
(`docs/map.md`), and `logbook setup map PATH` names it. Without it, every caller gets `NO_MAP_FILE`.
A file this package cannot read, truncated or hostile, is one `MapError` naming it, never a traceback
and never a hang."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

KEY = "map_file"  # in logbook.json: the path of the PMTiles file, absolute
NO_MAP_FILE = "No map file is set: `logbook setup map PATH` (docs/map.md)"


class MapError(ValueError):
    """The one error of this package: no map file set, or one that cannot be read, in one sentence."""


def map_file(meta: Mapping[str, Any]) -> Path:
    """The map file `logbook.json` names (`Logbook.meta`); `MapError(NO_MAP_FILE)` when it names none,
    and one sentence naming the path when the file is not there."""
    value = meta.get(KEY)
    if not isinstance(value, str) or not value.strip():
        raise MapError(NO_MAP_FILE)
    path = Path(value)
    if not path.is_file():
        raise MapError(
            f"the map file {path} is not there: `logbook setup map PATH` names another (docs/map.md)"
        )
    return path
