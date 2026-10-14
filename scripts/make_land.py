#!/usr/bin/env python3
"""Regenerate logbook/tables/land.json from Natural Earth's 1:110m land polygons (public domain).

    uv run python scripts/make_land.py ne_110m_land.geojson

Reads the GeoJSON file given — `geojson/ne_110m_land.geojson` of the Natural Earth vector repository
(nvkelso/natural-earth-vector on GitHub; a sparse checkout of that one file is enough) — and writes
the land table `logbook export world` and the Library's `/world` draw the map from: every polygon, its
outer ring first and its holes after it (one, the Caspian), each ring's coordinates rounded to 0.01
degree (the 1:110m set is drawn at about a degree a millimetre, so the hundredth is more than the data
holds), consecutive repeats and the closing point dropped, a ring that rounds to fewer than three
points dropped (a polygon whose outer ring goes with it), and each ring delta-encoded as integers in
hundredths of a degree: `[lon0, lat0, dlon1, dlat1, ...]`, the first point absolute and every other
one the step from the one before. The file must stay under `world.LAND_BYTES` (48 KiB);
`tests/test_world.py` holds it to that and to the shape.

This is a development script, and it reads a file: it never touches the network, and the CLI never
runs it (CLAUDE.md: no network on an adapter's default path). Natural Earth is in the public domain
(its LICENSE.md: "All versions of Natural Earth raster + vector map data found on this website are in
the public domain"); no attribution is required, and the table names its source anyway.
"""

from __future__ import annotations

import json
import sys
from itertools import pairwise
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "logbook" / "tables" / "land.json"
SCALE = 100  # hundredths of a degree
SOURCE = (
    "Natural Earth 1:110m physical vectors, land (ne_110m_land), public domain; rounded to 0.01 degree"
    " and delta-encoded by scripts/make_land.py"
)


def ring(coordinates: list[list[float]]) -> list[int] | None:
    """One ring rounded, de-duplicated and delta-encoded; None when fewer than three points are left."""
    points: list[tuple[int, int]] = []
    for lon, lat in coordinates:
        point = (round(lon * SCALE), round(lat * SCALE))
        if not points or points[-1] != point:
            points.append(point)
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()  # the closing point: a reader closes the ring
    if len(set(points)) < 3:
        return None
    flat = [points[0][0], points[0][1]]
    for (x0, y0), (x1, y1) in pairwise(points):
        flat += [x1 - x0, y1 - y0]
    return flat


def polygons(document: dict[str, object]) -> list[list[list[int]]]:
    """Every polygon of every feature, in the file's order: its rings, the outer one first."""
    out: list[list[list[int]]] = []
    features = document.get("features")
    if not isinstance(features, list):
        raise SystemExit("not a GeoJSON FeatureCollection: no features list")
    for feature in features:
        geometry = feature["geometry"]
        if geometry["type"] == "Polygon":
            found = [geometry["coordinates"]]
        elif geometry["type"] == "MultiPolygon":
            found = geometry["coordinates"]
        else:
            raise SystemExit(f"a {geometry['type']} where land polygons were expected")
        for polygon in found:
            outer = ring(polygon[0])
            if outer is None:
                continue
            holes = [r for r in (ring(h) for h in polygon[1:]) if r is not None]
            out.append([outer, *holes])
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    document = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    found = polygons(document)
    table = {"source": SOURCE, "scale": SCALE, "polygons": found}
    data = (json.dumps(table, separators=(",", ":")) + "\n").encode("utf-8")
    OUT.write_bytes(data)
    rings = [r for polygon in found for r in polygon]
    points = sum(len(r) // 2 for r in rings)
    print(f"{OUT}: {len(found)} polygons, {len(rings)} rings, {points} points, {len(data):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
