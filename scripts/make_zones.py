#!/usr/bin/env python3
"""Regenerate logbook/tables/zones.csv from the zone database's zone.tab (public domain).

    uv run python scripts/make_zones.py [zone.tab]

Reads the system's `/usr/share/zoneinfo/zone.tab` (or the file given) and writes `zone,country`:
every zone the database lists, with the ISO 3166-1 alpha-2 country it files it under, sorted by
zone. zone.tab names each zone once under one country; the readers use it to turn the airports
table's zone into a coarse country (`logbook/countries.py`). A development script, never run by
the CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "logbook" / "tables" / "zones.csv"
HEADER = (
    "# the zone database's zone.tab (public domain): zone, ISO 3166-1 alpha-2 country;"
    " scripts/make_zones.py\n"
)
DEFAULT = Path("/usr/share/zoneinfo/zone.tab")


def main(argv: list[str]) -> None:
    source = Path(argv[1]) if len(argv) > 1 else DEFAULT
    rows: dict[str, str] = {}
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        country, _coordinates, zone, *_comments = line.split("\t")
        rows[zone] = country
    OUT.write_text(
        HEADER + "zone,country\n" + "".join(f"{z},{rows[z]}\n" for z in sorted(rows)), encoding="utf-8"
    )
    print(f"{len(rows)} zones → {OUT}")


if __name__ == "__main__":
    main(sys.argv)
