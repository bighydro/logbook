"""The map of RFC 0043 §11 on the command line (docs/map.md): `logbook setup map PATH` names the offline
OpenStreetMap file in `logbook.json` (`map_file`), after reading its header, and `--off` removes it;
`logbook lab map render` draws one map to a file, to check by eye what the Day page and the timeline
will draw. Neither fetches anything: the file is the owner's, put on the home machine by the owner. The
map's code (`logbook.contrib.map`) is imported only when a command runs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core.store import Logbook
from .common import Subparsers


def shown(path: str | Path) -> str:
    """A path as printed: under the home directory as `~/…`, never spelling it (`logbook setup`)."""
    path = Path(path)
    try:
        return str(Path("~", *path.relative_to(Path.home()).parts))
    except ValueError:
        return str(path)


# -- logbook setup map ---------------------------------------------------------------------------------------


def setup_map_arguments(sub: Subparsers) -> None:
    """`logbook setup map [PATH] [--off] [--yes]`."""
    s = sub.add_parser(
        "map",
        help="the offline OpenStreetMap file your maps are drawn from (logbook.json map_file, docs/map.md)",
        description="name the map file the Library draws its maps from: a PMTiles v3 file of OpenStreetMap"
        " vector tiles (a Protomaps basemap build), on this machine. Its header is read first; what will"
        " be written is printed and asked. Nothing is downloaded: getting the file is yours (docs/map.md)."
        " Without PATH, says which file is set",
    )
    s.add_argument("path", nargs="?", metavar="PATH", help="the .pmtiles file")
    s.add_argument("--off", action="store_true", help="remove map_file from logbook.json; the file stays")
    s.add_argument("--yes", action="store_true", help="write without asking (tests, scripts)")
    s.set_defaults(fn=cmd_setup_map)


def _confirm(question: str, yes: bool) -> bool:
    from .setup import Console, Skipped, Stopped

    try:
        return Console(yes=yes).confirm(question, default=True)
    except (Stopped, Skipped):
        return False


def cmd_setup_map(a: argparse.Namespace) -> None:
    """Read the file's header (`pmtiles.read_header`), print the change and what the file holds, ask, and
    write `map_file` under the writer lock: a setting, not a line, so nothing is appended and no hash
    changes, and the index is not rebuilt. `--off` removes the key the same way."""
    from ..contrib.map import KEY, NO_MAP_FILE, MapError, pmtiles

    lb = Logbook.find()
    current = lb.meta.get(KEY)
    was = shown(current) if isinstance(current, str) and current else "(none)"
    if a.off:
        if current is None:
            print("no map file is set; nothing changed")
            return
        print(f"map_file: {was} → (none) in logbook.json; the file itself stays where it is")
        if not _confirm("Remove it?", a.yes):
            print("nothing written")
            return
        with lb.writer():
            meta = lb.meta
            meta.pop(KEY, None)
            lb._save_meta(meta)  # set_meta keeps every key; this one goes
        print("map_file removed: a map now says how to set one")
        return
    if a.path is None:
        if current is None:
            print(NO_MAP_FILE)
            return
        try:
            said = pmtiles.read_header(Path(str(current))).describe()
        except MapError as e:
            said = str(e)
        print(f"map_file: {was}\n{said}")
        return
    path = Path(a.path).expanduser().resolve()
    try:
        header = pmtiles.read_header(path)
    except MapError as e:
        print(f"setup map: {e}; nothing written", file=sys.stderr)
        sys.exit(2)
    print(f"{shown(path)}: {header.describe()}")
    if current == str(path):
        print("map_file already names it; nothing changed")
        return
    print(f"map_file: {was} → {shown(path)} in logbook.json")
    if not _confirm("Write it?", a.yes):
        print("nothing written")
        return
    with lb.writer():
        lb.set_meta(**{KEY: str(path)})
    print("written: maps are drawn from this file, on this machine; nothing is fetched")


# -- logbook lab map render ----------------------------------------------------------------------------------


def lab_map_arguments(verbs: Subparsers) -> None:
    """`logbook lab map render --bbox … [--width PX] [--track DAY] [--out FILE]`."""
    m = verbs.add_parser(
        "map",
        help="the offline map (docs/map.md): draw one as SVG, to check it by eye",
        description="the map of RFC 0043 §11, drawn from the file `setup map` names, as the Day page and the"
        " timeline will draw it; nothing is fetched and nothing is written to the record",
    )
    acts = m.add_subparsers(dest="map_verb", required=True)
    r = acts.add_parser(
        "render",
        help="one map as SVG: the box, the width, a day's track",
        description="draw the box at the width given, as inline SVG: water, land use, parks, roads,"
        " buildings close in, place names, then the day's track and its numbered stops; the"
        " OpenStreetMap attribution on every map. A box west of Greenwich is given --bbox=-0.2,51.4,…",
    )
    r.add_argument(
        "--bbox", metavar="MINLON,MINLAT,MAXLON,MAXLAT", help="the box (default: round --track's stays)"
    )
    r.add_argument("--width", type=int, default=390, metavar="PX", help="pixels wide (default 390, a phone)")
    r.add_argument(
        "--track", metavar="YYYY-MM-DD", help="this day's track and stops, numbered as the Day page"
    )
    r.add_argument("--out", metavar="FILE", help="write the SVG here (default: print it)")
    r.set_defaults(fn=cmd_map_render)


def cmd_map_render(a: argparse.Namespace) -> None:
    """The map file first (`NO_MAP_FILE` when none is set), then the day's timeline through the Day's own
    reader (the index's two days around it, no scan of the log), then the drawing."""
    from ..contrib.map import MapError, map_file, svg
    from ..core import day as day_reader
    from ..core import stays

    lb = Logbook.find()
    try:
        path = map_file(lb.meta)
        track = svg.track_of(day_reader.read(lb, a.track)["timeline"]) if a.track else None
        if a.bbox:
            box = svg.Box.parse(a.bbox)
        elif track is not None:
            box = svg.Box.around(track)
        else:
            raise MapError("a map needs --bbox MINLON,MINLAT,MAXLON,MAXLAT, or --track DAY to draw round it")
        drawn = svg.render(path, box, a.width, track)
    except MapError as e:
        print(e, file=sys.stderr)
        sys.exit(2)
    except (ValueError, stays.SettingsError) as e:
        print(f"lab map render: {e}", file=sys.stderr)
        sys.exit(2)
    if not a.out:
        sys.stdout.write(drawn.svg)
        return
    data = drawn.svg.encode("utf-8")
    Path(a.out).write_bytes(data)
    reduced = ", detail reduced to stay under 300 KB" if drawn.level else ""
    print(
        f"{a.out}: {len(data) / 1000:.1f} KB of SVG, {drawn.width}×{drawn.height} px, zoom {drawn.zoom},"
        f" {drawn.tiles} tiles{reduced}"
    )
