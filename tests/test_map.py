"""The map of RFC 0043 §11, drawn (`logbook.contrib.map.svg`), asked for the named thing nearest a stay
(`.nearest`), named in `logbook.json` (`logbook setup map`) and drawn by eye (`logbook lab map render`).
The map file is the synthetic coast of `tests/oslo_map.py`, written here; the record is the demo's (the
Oslo persona, who does not exist)."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import oslo_map
import pytest

from logbook import cli
from logbook.commands import maps
from logbook.contrib import serve
from logbook.contrib.map import KEY, NO_MAP_FILE, MapError, map_file, nearest, svg
from logbook.core.store import Logbook

SVG = "{http://www.w3.org/2000/svg}"
COAST = svg.Box(oslo_map.WEST, oslo_map.SOUTH, oslo_map.EAST, oslo_map.NORTH)
TOWN = svg.Box(10.711, 59.906, 10.720, 59.910)  # a few hundred metres round the buildings
DAY = "2026-06-03"


@pytest.fixture(scope="module")
def coast(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return oslo_map.write_coast(tmp_path_factory.mktemp("map") / "coast.pmtiles")


def _parse(text: str) -> ET.Element:
    root = ET.fromstring(text)
    assert root.tag == f"{SVG}svg"
    return root


def _classes(root: ET.Element) -> set[str]:
    return {c for e in root.iter() for c in (e.get("class") or "").split()}


# -- the renderer --------------------------------------------------------------------------------------------


def test_the_coast_is_drawn_as_one_svg_with_its_layers_and_the_attribution(coast: Path) -> None:
    drawn = svg.render(coast, COAST, 390)
    root = _parse(drawn.svg)
    assert root.get("viewBox") == f"0 0 390 {drawn.height}" and drawn.height > 100
    assert {"water", "park", "landuse", "road-highway", "road-major", "road-minor", "road-path"} <= _classes(
        root
    )
    assert "building" not in _classes(root)  # not at this zoom
    text = "".join(root.itertext())
    assert "© OpenStreetMap contributors" in text
    assert "Example basemap" in text  # the file's own attribution, its links dropped
    assert "Solvindbukta" in text
    assert 10 <= drawn.zoom <= 14 and drawn.tiles >= 1


def test_the_map_fetches_nothing_and_runs_nothing(coast: Path) -> None:
    """No script, no link, no image, no font, no url(): the one URL is the SVG namespace."""
    text = svg.render(coast, COAST, 390).svg
    assert "<script" not in text and "<image" not in text and "<a " not in text
    assert "url(" not in text and "@import" not in text and "@font-face" not in text
    assert re.findall(r"https?://[^\s\"'<]+", text) == ["http://www.w3.org/2000/svg"]


def test_light_and_dark_come_from_css_custom_properties(coast: Path) -> None:
    text = svg.render(coast, COAST, 390).svg
    assert "var(--map-water," in text and "var(--map-land," in text
    assert "@media (prefers-color-scheme:dark)" in text
    assert "system-ui" in text


def test_buildings_are_drawn_close_in(coast: Path) -> None:
    drawn = svg.render(coast, TOWN, 390)
    assert drawn.zoom == oslo_map.MAX_ZOOM  # past the file's last zoom, its last zoom drawn larger
    assert "building" in _classes(_parse(drawn.svg))


def test_coordinates_are_rounded_to_a_tenth_of_a_pixel(coast: Path) -> None:
    root = _parse(svg.render(coast, COAST, 390).svg)
    paths = [e.get("d") or "" for e in root.iter(f"{SVG}path")]
    assert paths
    numbers = [n for d in paths for n in re.findall(r"-?\d*\.?\d+", d)]
    assert all(len(n.split(".")[1]) <= 1 for n in numbers if "." in n)


def test_place_labels_never_overlap(coast: Path) -> None:
    for width in (200, 390, 800):
        root = _parse(svg.render(coast, COAST, width).svg)
        boxes = []
        for e in root.iter(f"{SVG}text"):
            if "label" not in (e.get("class") or ""):
                continue
            size = float(e.get("font-size") or 0)
            x, y, w = float(e.get("x") or 0), float(e.get("y") or 0), len(e.text or "") * size * svg.CHAR_EM
            boxes.append((x - w / 2, y - size, x + w / 2, y + size * 0.3))
        assert boxes
        for i, a in enumerate(boxes):
            for b in boxes[i + 1 :]:
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (width, a, b)


def test_the_track_and_its_numbered_stops_are_drawn_on_top(coast: Path) -> None:
    track = svg.Track(
        (
            svg.Stop((1,), oslo_map.CAFE[1], oslo_map.CAFE[0]),
            svg.Stop((2,), oslo_map.MARINA[1], oslo_map.MARINA[0]),
            svg.Stop((3,), 59.915, 10.700),
        ),
        ((0, 1, False), (1, 2, True)),
    )
    drawn = svg.render(coast, COAST, 390, track)
    root = _parse(drawn.svg)
    groups = [e for e in root if e.tag == f"{SVG}g"]
    assert groups[-2].get("class") == "track" and groups[-1].get("class") == "attribution"
    lines = list(groups[-2].iter(f"{SVG}path"))
    assert [e.get("class") for e in lines] == ["move", "move gap"]
    pins = [e for e in groups[-2].iter(f"{SVG}text")]
    assert [e.text for e in pins] == ["1", "2", "3"]
    assert len(list(groups[-2].iter(f"{SVG}circle"))) == 3


def test_a_stop_outside_the_box_draws_the_move_to_the_edge_and_no_pin(coast: Path) -> None:
    track = svg.track_of(
        [{"kind": "stay", "lat": 59.908, "lon": 10.715}, {"kind": "stay", "lat": 59.95, "lon": 10.60}]
    )
    drawn = svg.render(coast, TOWN, 390, track)
    root = _parse(drawn.svg)
    (move,) = [e for e in root.iter(f"{SVG}path") if e.get("class") == "move"]
    x, y = 0.0, 0.0
    for i, (dx, dy) in enumerate(re.findall(r"(-?[\d.]+) (-?[\d.]+)", move.get("d") or "")):
        x, y = (float(dx), float(dy)) if i == 0 else (x + float(dx), y + float(dy))
        assert -0.1 <= x <= drawn.width + 0.1 and -0.1 <= y <= drawn.height + 0.1
    assert [e.text for e in root.iter(f"{SVG}text") if e.get("class") == "pin"] == ["1"]


def test_a_stop_visited_twice_is_one_pin_with_both_numbers(coast: Path) -> None:
    track = svg.track_of(
        [
            {"kind": "stay", "lat": 59.906, "lon": 10.71},
            {"kind": "move"},
            {"kind": "stay", "lat": 59.901, "lon": 10.735},
            {"kind": "stay", "lat": 59.906, "lon": 10.71},
        ]
    )
    root = _parse(svg.render(coast, COAST, 390, track).svg)
    assert [e.text for e in root.iter(f"{SVG}text") if e.get("class") == "pin"] == ["1, 3", "2"]


def test_outside_the_extract_the_track_and_the_attribution_still_draw(coast: Path) -> None:
    track = svg.track_of(
        [{"kind": "stay", "lat": 63.43, "lon": 10.39}, {"kind": "stay", "lat": 63.44, "lon": 10.40}]
    )
    box = svg.Box.around(track)
    drawn = svg.render(coast, box, 390, track)
    root = _parse(drawn.svg)
    assert drawn.tiles == 0 and "track" in _classes(root)
    assert "© OpenStreetMap contributors" in "".join(root.itertext())


def test_a_dense_tile_stays_under_the_size_budget(tmp_path: Path) -> None:
    """Thousands of buildings and roads in one tile: the map drops the finest layers first and stays
    under `svg.BUDGET`, 300 KB, still valid and still attributed."""
    f = oslo_map
    buildings = [
        f.Feature(3, [[(x, y), (x, y + 25), (x + 25, y + 25), (x + 25, y)]], {"kind": "building"})
        for x in range(0, 4096, 40)
        for y in range(0, 4096, 40)
    ]
    roads = [
        f.Feature(2, [[(0, y), (1000, y + 7), (2000, y), (4096, y + 9)]], {"kind": "minor_road"})
        for y in range(0, 4096, 9)
    ]
    x, y = oslo_map.tile_range(14)[0][0], oslo_map.tile_range(14)[1][0]
    path = f.write_pmtiles(
        tmp_path / "dense.pmtiles", {(14, x, y): f.tile_message({"buildings": buildings, "roads": roads})}
    )
    n = 1 << 14
    import math

    west, east = x / n * 360 - 180, (x + 1) / n * 360 - 180
    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    drawn = svg.render(path, svg.Box(west, south, east, north), 390)
    assert len(drawn.svg.encode("utf-8")) < svg.BUDGET
    root = _parse(drawn.svg)
    assert "© OpenStreetMap contributors" in "".join(root.itertext())


def test_a_box_or_a_width_that_is_not_one_is_one_sentence(coast: Path) -> None:
    for text in ("10.7,59.9,10.6,59.95", "a,b,c,d", "10.6,59.9,10.7", "10.6,89.5,10.7,89.9"):
        with pytest.raises(MapError):
            svg.Box.parse(text)
    with pytest.raises(MapError, match="width"):
        svg.render(coast, COAST, 10)


# -- the track, as the Day page draws it ---------------------------------------------------------------------


def test_the_track_numbers_its_stops_as_the_day_page_does() -> None:
    """The stays and stops with a position, numbered in order; a move between two of them a line,
    dashed across a flight, a gap or a stay with no position; the same dots `_track_svg` draws."""
    timeline: list[dict[str, Any]] = [
        {"kind": "stay", "lat": 59.91, "lon": 10.75},
        {"kind": "move"},
        {"kind": "stop", "lat": 59.92, "lon": 10.74},
        {"kind": "flight"},
        {"kind": "stay", "lat": 59.93, "lon": 10.73},
        {"kind": "stay", "lat": None, "lon": None},
        {"kind": "stay", "lat": 59.91, "lon": 10.75},
        {"kind": "stay", "lat": 59.90, "lon": 10.70, "gap": True},
        {"kind": "aboard", "lat": 59.89, "lon": 10.71},
    ]
    track = svg.track_of(timeline)
    assert [(s.numbers, s.lat, s.lon) for s in track.stops] == [
        ((1, 4), 59.91, 10.75),
        ((2,), 59.92, 10.74),
        ((3,), 59.93, 10.73),
        ((5,), 59.89, 10.71),
    ]
    assert track.links == ((0, 1, False), (1, 2, True), (2, 0, True), (0, 3, True))
    page = serve._track_svg(timeline)
    assert page.count("<circle") == len(track.stops)
    assert page.count('class="gap"') == sum(gap for *_, gap in track.links)


# -- the named thing nearest a stay --------------------------------------------------------------------------


def test_the_nearest_named_thing_within_50_m_is_proposed(coast: Path) -> None:
    lon, lat = oslo_map.CAFE
    found = nearest.nearest_named(coast, lat + 0.0002, lon)  # some 22 m north of the café
    assert found is not None
    assert (found.name, found.kind, found.layer) == ("Kafé Kari", "restaurant", "pois")
    assert 15 < found.distance_m < 30
    lon, lat = oslo_map.MARINA
    marina = nearest.nearest_named(coast, lat, lon + 0.0004)  # some 22 m east
    assert marina is not None and marina.name == "Solvind marina"


def test_a_pier_counts_from_its_edge_and_inside_is_nought(coast: Path) -> None:
    (w, s), _, (e, n), _ = oslo_map.PIER
    inside = nearest.nearest_named(coast, (s + n) / 2, (w + e) / 2)
    assert inside is not None and (inside.name, inside.distance_m) == ("Hansenbrygga", 0.0)
    north = nearest.nearest_named(coast, n + 0.0003, (w + e) / 2)  # some 33 m north of its edge
    assert north is not None and north.name == "Hansenbrygga" and 25 < north.distance_m < 40


def test_nothing_named_within_50_m_is_no_proposal(coast: Path) -> None:
    lon, lat = oslo_map.CAFE
    assert nearest.nearest_named(coast, lat + 0.0006, lon) is None  # some 67 m
    assert nearest.nearest_named(coast, 59.9200, 10.7400) is None  # beside the bench, which has no name
    assert nearest.nearest_named(coast, 59.9110, 10.7480) is None  # a town's point is not a stay's place
    assert nearest.nearest_named(coast, 63.43, 10.39) is None  # outside the extract


# -- the setting and the sentence without it -----------------------------------------------------------------


@pytest.fixture
def record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Logbook]:
    root = tmp_path / "Demo"
    cli.main(["demo", "--days", "3", "--seed", "7", "--out", str(root)])
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    yield Logbook(root)


def test_without_the_setting_every_caller_gets_one_sentence(
    record: Logbook, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    with pytest.raises(MapError) as e:
        map_file(record.meta)
    assert str(e.value) == NO_MAP_FILE == "No map file is set: `logbook setup map PATH` (docs/map.md)"
    capsys.readouterr()
    with pytest.raises(SystemExit) as exit_:
        cli.main(
            ["lab", "map", "render", "--bbox", "10.7,59.9,10.75,59.92", "--out", str(tmp_path / "m.svg")]
        )
    assert exit_.value.code == 2
    assert capsys.readouterr().err.strip() == NO_MAP_FILE
    assert not (tmp_path / "m.svg").exists()


def test_setup_map_checks_the_header_says_what_it_writes_and_asks(
    record: Logbook,
    coast: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    before = record.meta
    head = record.meta["head"]
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    cli.main(["setup", "map", str(coast)])
    out = capsys.readouterr().out
    assert (
        "zoom 10 to 14" in out
        and f"map_file: (none) → {maps.shown(coast)}" in out
        and "nothing written" in out
    )
    assert record.meta == before
    cli.main(["setup", "map", str(coast), "--yes"])
    assert record.meta[KEY] == str(coast.resolve())
    assert record.meta["head"] == head  # a setting, not a line
    assert {k: v for k, v in record.meta.items() if k != KEY} == before
    cli.main(["setup", "map"])
    assert maps.shown(coast) in capsys.readouterr().out
    text = tmp_path / "notes.txt"
    text.write_text("not a map\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "map", str(text), "--yes"])
    assert e.value.code == 2
    assert "not a PMTiles file" in capsys.readouterr().err
    assert record.meta[KEY] == str(coast.resolve())
    cli.main(["setup", "map", "--off", "--yes"])
    assert KEY not in record.meta and record.meta == before
    cli.main(["setup", "map", "--off", "--yes"])
    assert "nothing changed" in capsys.readouterr().out


def test_lab_map_render_draws_a_day_s_track_from_the_record(
    record: Logbook, coast: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    cli.main(["setup", "map", str(coast), "--yes"])
    capsys.readouterr()
    out = tmp_path / "map.svg"
    cli.main(["lab", "map", "render", "--width", "390", "--track", DAY, "--out", str(out)])
    said = capsys.readouterr().out
    assert "map.svg" in said and "KB" in said
    root = _parse(out.read_text(encoding="utf-8"))
    assert "track" in _classes(root)
    pins = [e.text for e in root.iter(f"{SVG}text") if e.get("class") == "pin"]
    day = json.loads(_day_json(capsys))
    located = [e for e in day["timeline"] if e["kind"] != "move" and e.get("lat") is not None]
    assert sum(len(p.split(", ")) for p in pins) == len(located)
    cli.main(["lab", "map", "render", "--bbox", ",".join(map(str, (10.70, 59.90, 10.76, 59.92)))])
    assert capsys.readouterr().out.startswith("<svg")


def _day_json(capsys: pytest.CaptureFixture[str]) -> str:
    cli.main(["day", DAY, "--json"])
    return capsys.readouterr().out


# -- what the review found --------------------------------------------------------------------------------


def test_a_box_too_narrow_to_project_is_one_sentence(coast: Path) -> None:
    with pytest.raises(MapError, match="too small"):
        svg.render(coast, svg.Box(10.7, 59.9, 10.700000000000001, 59.91), 390)


def test_a_box_wider_than_the_file_s_widest_zoom_allows_is_one_sentence(tmp_path: Path) -> None:
    """Never a map with its east cut off in silence: the tiles a box needs at the file's first zoom,
    within the file's bounds, are drawn whole, or the box is refused."""
    wide = oslo_map.write_pmtiles(
        tmp_path / "wide.pmtiles", {(10, 540, 300): b""}, bounds=(0.0, 50.0, 30.0, 70.0)
    )
    with pytest.raises(MapError, match="tiles"):
        svg.render(wide, svg.Box(5.0, 58.0, 20.0, 62.0), 4000)


def test_a_hostile_tile_draws_fast_and_under_the_budget(tmp_path: Path) -> None:
    """One tile of a water polygon zigzagging across the whole tile 200,000 times and a road the same:
    the map caps what it draws, stays under `svg.BUDGET` and keeps the track and the attribution."""
    import time

    f = oslo_map
    zig = [(i % 4096, 0 if i % 2 else 4096) for i in range(0, 200_000)]
    x, y = oslo_map.tile_range(14)[0][0], oslo_map.tile_range(14)[1][0]
    tile = f.tile_message(
        {"water": [f.Feature(3, [zig])], "roads": [f.Feature(2, [zig], {"kind": "minor_road"})]}
    )
    path = f.write_pmtiles(tmp_path / "zig.pmtiles", {(14, x, y): tile})
    n = 1 << 14
    west, east = x / n * 360 - 180, (x + 1) / n * 360 - 180
    import math

    north = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    south = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    track = svg.track_of([{"kind": "stay", "lat": (north + south) / 2, "lon": (west + east) / 2}])
    started = time.monotonic()
    drawn = svg.render(path, svg.Box(west, south, east, north), 390, track)
    assert time.monotonic() - started < 20
    assert len(drawn.svg.encode("utf-8")) < svg.BUDGET
    root = _parse(drawn.svg)
    assert "© OpenStreetMap contributors" in "".join(root.itertext())
    assert [e.text for e in root.iter(f"{SVG}text") if e.get("class") == "pin"] == ["1"]


def test_stops_a_few_metres_apart_are_one_pin(coast: Path) -> None:
    """As the Day page merges dots by the pixel: two stays 3 m apart are one pin, both numbers on it."""
    track = svg.track_of(
        [
            {"kind": "stay", "lat": 59.90600, "lon": 10.7100},
            {"kind": "stay", "lat": 59.90100, "lon": 10.7350},
            {"kind": "stay", "lat": 59.90603, "lon": 10.7100},
        ]
    )
    root = _parse(svg.render(coast, COAST, 390, track).svg)
    assert [e.text for e in root.iter(f"{SVG}text") if e.get("class") == "pin"] == ["1, 3", "2"]


def test_one_namer_answers_many_stays_from_one_open_file(coast: Path) -> None:
    with nearest.Namer(coast) as namer:
        lon, lat = oslo_map.CAFE
        found = [namer.nearest(lat + 0.0001 * i, lon) for i in range(5)]
    assert [p.name if p else None for p in found] == ["Kafé Kari"] * 5
