"""`logbook export world --style chart`: the record on paper. The chart drawn on the canvas (no image,
nothing fetched), the owner's own chart as the paper (`--chart FILE --control-points FILE
--chart-credit TEXT`), and `--journey ID`, one page per journey. Two rules: the chart is paper, the
track is evidence — every position as recorded, every date the record's — and nothing is fetched. The
globe's page stays byte for byte what it was.

The synthetic weekend of `tests/world_record.py` and the synthetic chart of `tests/chart_paper.py`: a
grid of the Oslo fjord made pixel by pixel under a known transform; nobody and nothing in them is
real."""

from __future__ import annotations

import base64
import hashlib
import itertools
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
from html import escape
from pathlib import Path
from typing import Any

import chart_paper as cp
import pytest
from world_record import ANCHORAGE, FRI, HOME, HYTTA, MARINA, YACHT, world_record

from logbook import cli
from logbook.contrib import chart_fit, chart_image, world, world_chart
from logbook.core import store
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite|background)\s*=\s*["']([^"']*)["']""", re.I
)
FETCHERS = ("fetch(", "XMLHttpRequest", "import(", "WebSocket", "EventSource", "sendBeacon", "Worker(")
CREDIT = "a synthetic grid of the fjord, made by the test suite"
# The globe's page of the synthetic weekend, with line ids minted in order (`_ids`), as `main` wrote it
# before the chart: the default window, tier 1 alone, and two days of it.
MODERN_PAGES = {
    (None, None, None): "449123a515d68b7df6967da99b38581393e1f25c22317ac333fbb4deec527b91",
    (None, None, (1,)): "4140b9510a20539e06f347529b96896de533c5fdbaf28e15f9bc37c78dd06070",
    ("2026-07-11", "2026-07-12", None): "0547dd0097bc4c4d0e67dc742e0305b490c142585051d13655551f966212c4f3",
}
MODERN_SCRIPT_HASH = "sha256-2UJjyKq8+S4nh1gUAt6bE2tx3rbDCERgq93AJSSp2RA="
# A 24 × 16 JPEG of a sepia gradient, made for this test and nothing else.
TINY_JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAAAAAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYn"
    "KSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgo"
    "KCgoKCgoKCj/wAARCAAQABgDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAf/xAAXEAADAQAAAAAAAAAAAAAAAAAAFmKh"
    "/8QAFgEBAQEAAAAAAAAAAAAAAAAAAAQF/8QAFREBAQAAAAAAAAAAAAAAAAAAABL/2gAMAwEAAhEDEQA/AKUx3oY70jLHehjvTKhc"
    "szHegjLHegQP/9k="
)
NOTE = b"taken aboard at 59.6950 10.5850 by a phone"  # what a phone's photograph of a chart would add


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return world_record(tmp_path, monkeypatch)


def _ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Line ids minted in order, so the page of the weekend is the same bytes on every run."""
    counter = itertools.count(1)
    monkeypatch.setattr(store, "uuid7", lambda: f"00000000-0000-7000-8000-{next(counter):012d}")


def _run(*args: str) -> None:
    cli.main(["export", "world", *args])


def _fails(*args: str) -> int:
    with pytest.raises(SystemExit) as e:
        _run(*args)
    return int(e.value.code or 0)


def _block(text: str, name: str) -> str:
    found = re.search(rf'<script type="[^"]+" id="{name}">(.*?)</script>', text, re.S)
    assert found is not None, name
    return found[1]


def _chart(text: str) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(_block(text, "chart"))
    return found


def _paper(tmp_path: Path, tilt: float = 0.0, where: list[tuple[float, float]] | None = None) -> list[str]:
    """The synthetic chart and its control points on disk; the flags that give them."""
    to_pixel = cp.known(tilt)
    image = tmp_path / "paper.png"
    cp.png(image, to_pixel)
    points = cp.write_points(tmp_path / "points.json", cp.points(to_pixel, where))
    return ["--chart", str(image), "--control-points", str(points), "--chart-credit", CREDIT]


def _transform(chart: dict[str, Any]) -> chart_fit.Transform:
    fit = chart["fit"]
    return chart_fit.Transform(
        fit["kind"], fit["lon0"], tuple(fit["src"]), tuple(fit["dst"]), tuple(fit["h"])
    )


def _positions(bundle: dict[str, Any]) -> list[tuple[float, float]]:
    """Every position of Havbris's track on the page, as recorded."""
    [boat] = [a for a in bundle["assets"] if a["id"] == f"asset:{YACHT}"]
    return list(zip(boat["track"][1::3], boat["track"][2::3], strict=True))


def _passage(lb: Logbook) -> str:
    [line] = [line for line in lb.lines() if (line.get("payload") or {}).get("mode") == "passage"]
    return str(line["id"])


def _exif(orientation: int, note: bytes = NOTE) -> bytes:
    """A little-endian TIFF structure as EXIF carries it: the orientation, and a description."""
    note = note + b"\x00"
    entries = [
        (0x0112, 3, 1, struct.pack("<HH", orientation, 0)),
        (0x010E, 2, len(note), struct.pack("<I", 38)),
    ]
    ifd = struct.pack("<H", len(entries))
    ifd += b"".join(struct.pack("<HHI", tag, kind, count) + value for tag, kind, count, value in entries)
    return b"II*\x00" + struct.pack("<I", 8) + ifd + struct.pack("<I", 0) + note


def _jpeg_with(*segments: bytes) -> bytes:
    """The tiny JPEG with `segments` (whole, marker and length) after its start of image, and a
    second picture after its end, as a phone's gain map would be."""
    return TINY_JPEG[:2] + b"".join(segments) + TINY_JPEG[2:] + b"\xff\xd8" + NOTE + b"\xff\xd9"


def _segment(marker: int, body: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


# -- the globe stays what it was ----------------------------------------------------------------------------


def test_the_modern_page_is_byte_for_byte_what_it_was(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _ids(monkeypatch)
    lb = world_record(tmp_path, monkeypatch)
    for (first, last, tiers), digest in MODERN_PAGES.items():
        built = world.build(lb, world.request(lb, first, last, tiers))
        assert hashlib.sha256(built.page).hexdigest() == digest, (first, last, tiers)
        assert built.file_name == world.FILE_NAME and built.style == world_chart.MODERN
    assert world.SCRIPT_HASH == MODERN_SCRIPT_HASH, "world.js is the globe's, unchanged"

    # and the line the export appends says what it said: no key of the chart's
    out = tmp_path / "World"
    _run("--out", str(out))
    extra = list(lb.lines())[-1]["payload"]["extra"]["world"]
    assert set(extra) == {
        "bytes",
        "json_bytes",
        "places",
        "assets",
        "stays",
        "journeys",
        "chapters",
        "thinned",
        "written",
    }


# -- the drawn chart ----------------------------------------------------------------------------------------


def test_the_chart_draws_with_no_image_and_fetches_nothing(
    lb: Logbook, tmp_path: Path, no_network: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "World"
    _run("--out", str(out), "--style", "chart")
    _run("--out", str(out))
    assert no_network == [], "the export opened no connection"
    printed = capsys.readouterr().out
    assert f"the chart: {world_chart.DRAWN_CREDIT}" in printed
    assert sorted(p.name for p in out.iterdir()) == ["world-chart.html", world.FILE_NAME], "side by side"
    text = (out / "world-chart.html").read_text(encoding="utf-8")
    globe = (out / world.FILE_NAME).read_text(encoding="utf-8")

    # The record on the chart is the globe's record, byte for byte: the same positions, the same minutes.
    assert world.embedded_json(text) == world.embedded_json(globe)
    # The paper: the land table bundled whole, the record's days, no image.
    assert json.loads(_block(text, "land")) == world.land()
    chart = _chart(text)
    assert chart["paper"] == "drawn" and chart["credit"] == world_chart.DRAWN_CREDIT
    assert chart["days"] == {"first": "2026-07-10", "years": False}
    assert "fit" not in chart and 'id="chart-image"' not in text
    bundle = world.bundle_of(text)
    [passage] = bundle["journeys"]
    marks = chart["marks"]["journeys"][passage["id"]]
    assert (marks["from"], marks["to"]) == (0, 0), "the passage began and ended on 10 July"
    [boat] = [a for a in bundle["assets"] if a["id"] == passage["subject"]]
    [[first, day]] = marks["marks"]
    assert day == 0 and boat["track"][first * 3] >= passage["t0"] > boat["track"][first * 3 - 3], (
        "the first fix of the day at or after the passage set out"
    )
    assert chart["marks"]["stays"] == [0, 0, 1, 2], "each stay's first day"
    assert escape(f"the chart: {world_chart.DRAWN_CREDIT}") in text, "the legend names the source"

    # Nothing fetched: no URL anywhere, no element that loads, the one script by its hash.
    low = text.lower()
    assert REFERENCE.findall(text) == []
    for tag in ("<link", "<iframe", "<frame", "<object", "<embed", "<base", "<img", "<audio", "<video"):
        assert tag not in low, tag
    for needle in FETCHERS:
        assert needle not in text, needle
    assert "url(" not in low and "@import" not in low and "@font-face" not in low
    assert "http:" not in low and "https:" not in low
    assert text.count("<script>") == 1
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', text)
    assert csp is not None and csp[1] == world_chart.POLICY and csp[1].startswith("default-src 'none'")
    script = re.search(r"<script>(.*?)</script>", text, re.S)
    assert script is not None and script[1] == world_chart.SCRIPT
    digest = base64.b64encode(hashlib.sha256(script[1].encode("utf-8")).digest()).decode()
    assert (
        f"sha256-{digest}" == world_chart.SCRIPT_HASH and f"script-src '{world_chart.SCRIPT_HASH}'" in csp[1]
    )
    assert "//" not in re.sub(r"/\*.*?\*/", "", script[1], flags=re.S), "no comment that could hide a URL"
    checked = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_synthetic.py"), str(out)],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr

    # The paper is paper: no dark scheme, in the style or in the script.
    assert "prefers-color-scheme" not in text and "color-scheme:light" in world_chart.STYLE
    assert len(text.encode("utf-8")) <= world_chart.PAGE_BYTES


def _section(script: str, start: str, end: str) -> str:
    return script[script.index(start) : script.index(end)]


def test_the_chart_script_shares_the_globes_scrubber_and_clock_line_for_line() -> None:
    """The scrubber unchanged: the chart's script carries the globe's scrubber, its clock and date
    formats and its stay lookup verbatim, and nothing the globe uses to slide a dot between fixes."""
    globe, chart = world.SCRIPT, world_chart.SCRIPT
    scrubber = _section(
        globe, "/* -- the scrubber: ticks, the chapters as bands, the time -- */", "/* -- the view:"
    )
    assert scrubber in chart
    time = _section(globe, "/* -- time -- */\n", "function positionOf(")
    assert time in chart
    stay_at = _section(globe, "function stayAt(", "function ownerAt(")
    assert stay_at in chart


def test_the_track_is_evidence_in_the_chart_script() -> None:
    """Nothing in the chart's script smooths a line, moves a position or invents one: no curve, no
    chance, no interpolation along a route or between two fixes."""
    script = world_chart.SCRIPT
    for needle in ("bezierCurveTo", "quadraticCurveTo", "Math.random", "function along", "positionOf"):
        assert needle not in script, needle
    assert "function fixAt(" in script and "function trace(" in script


def _node_eval(source: str, expression: str) -> Any:
    node = shutil.which("node")
    if node is None:
        if os.environ.get("CI"):
            pytest.fail(
                "node is on every CI runner, and these tests hold the chart's script to Python's arithmetic"
            )
        pytest.skip("node is not installed: the chart's script is held to Python's arithmetic where it is")
    done = subprocess.run(
        [node, "-e", f"{source}\nprocess.stdout.write(JSON.stringify({expression}));"],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_an_asset_on_the_chart_is_at_its_last_fix_never_between_two() -> None:
    script = world_chart.SCRIPT
    fix_at = script[script.index("function fixAt(") :]
    fix_at = fix_at[: fix_at.index("\n}\n") + 3]
    track = [0, 59.9, 10.7, 60, 59.8, 10.6, 2000, 59.7, 10.5]
    found = _node_eval(
        f"var gap = 720;\n{fix_at}",
        f"[30, 60, 90, 799, 1999, 2000, 5000].map(function (m) {{ return fixAt({{track: {track}}}, m); }})",
    )
    assert [(f["lat"], f["lon"], f["seen"]) for f in found] == [
        (59.9, 10.7, True),
        (59.8, 10.6, True),
        (59.8, 10.6, True),
        (59.8, 10.6, False),
        (59.8, 10.6, False),
        (59.7, 10.5, True),
        (59.7, 10.5, False),
    ], "each a recorded fix, as recorded"


def test_the_chart_writes_a_day_as_the_calendar_counts_it() -> None:
    script = world_chart.SCRIPT
    source = script[script.index("var MONTHS") :]
    source = (
        source[: source.index("\n")]
        + "\n"
        + _section(script, "function dateText(", "/* -- drawing the record")
    )
    found = _node_eval(
        f"var firstDay = [2026, 7, 10], chart = {{days: {{years: false}}}};\n{source}",
        "[dateText(-1), dateText(0), dateText(22), dateText(175)]",
    )
    assert found == ["9 Jul", "10 Jul", "1 Aug", "1 Jan"]
    found = _node_eval(
        f"var firstDay = [2026, 12, 31], chart = {{days: {{years: true}}}};\n{source}",
        "[dateText(0), dateText(1)]",
    )
    assert found == ["31 Dec 2026", "1 Jan 2027"]


def test_the_dates_on_the_chart_are_the_records_not_a_rounded_minute(lb: Logbook, tmp_path: Path) -> None:
    """A journey that sets out twenty seconds before midnight is the minute after it on the page (the
    record's JSON counts whole minutes, as the globe's does), and on the chart it is the day it set out."""
    lb.append(
        at=f"{FRI}T21:59:40Z",
        end=f"{FRI}T22:30:00Z",
        source="passages",
        kind="journey",
        tier=1,
        payload={
            "schema": "journey/v1",
            "raw_id": f"passages:{YACHT}:{FRI}T23:59:40",
            "mode": "passage",
            "subject": YACHT,
            "name": "a midnight shift of anchorage",
            "from": {"latitude": ANCHORAGE[0], "longitude": ANCHORAGE[1]},
            "to": {"latitude": 59.6955, "longitude": 10.5862},
        },
    )
    out = tmp_path / "World"
    _run("--out", str(out), "--style", "chart", "--from", FRI, "--to", "2026-07-11")
    text = (out / "world-chart.html").read_text(encoding="utf-8")
    [late] = [j for j in world.bundle_of(text)["journeys"] if j["name"] == "a midnight shift of anchorage"]
    assert late["t0"] == 1440, "rounded, the page's minute is the next day's first"
    marks = _chart(text)["marks"]["journeys"][late["id"]]
    assert (marks["from"], marks["to"]) == (0, 1), "set out on 10 July, arrived on the 11th"


# -- the owner's chart --------------------------------------------------------------------------------------


def test_four_control_points_warp_a_known_track_to_known_pixels(
    lb: Logbook, tmp_path: Path, no_network: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "World"
    _run("--out", str(out), *_paper(tmp_path))
    assert no_network == []
    printed = capsys.readouterr().out
    assert f"the chart: {CREDIT}" in printed and "the fit: affine, 4 control points" in printed
    text = (out / "world-chart.html").read_text(encoding="utf-8")
    chart = _chart(text)
    assert chart["paper"] == "image" and chart["credit"] == CREDIT
    assert (chart["fit"]["width"], chart["fit"]["height"]) == (cp.WIDTH, cp.HEIGHT)
    assert all(p["residual_px"] == 0.0 for p in chart["fit"]["points"])

    # Every fix of Havbris's track lands on the pixel the paper's own transform gives it, and the three
    # places on the rings drawn into the image for them.
    bundle = world.bundle_of(text)
    transform, truth = _transform(chart), cp.known()
    positions = _positions(bundle)
    assert len(positions) > 20
    for lat, lon in [*positions, HOME, MARINA, HYTTA]:
        at = transform.to_pixel(lat, lon)
        assert at is not None
        assert math.dist(at, truth(lat, lon)) < 0.01, (lat, lon)

    # The page draws with the same arithmetic: the script's transform agrees with Python's.
    script = world_chart.SCRIPT
    source = _section(script, "function chartTransform(", "/* -- end of the fit -- */")
    pixels = _node_eval(
        f"{source}\nvar t = chartTransform({json.dumps(chart['fit'])});",
        f"{json.dumps(positions)}.map(function (q) {{ return t(q[0], q[1]); }})",
    )
    for (lat, lon), at in zip(positions, pixels, strict=True):
        assert math.dist(at, transform.to_pixel(lat, lon) or (math.inf, math.inf)) < 1e-6

    # The record is the globe's; the image is in the page as given, and named in the crossing line.
    globe = world.build(lb, world.request(lb))
    assert world.embedded_json(text) == globe.json
    image = base64.b64decode(_block(text, "chart-image"))
    assert image == (tmp_path / "paper.png").read_bytes()
    assert json.loads(_block(text, "land")) == {"scale": 100, "polygons": []}, "the globe's coasts not drawn"
    line = list(lb.lines())[-1]
    extra = line["payload"]["extra"]["world"]
    assert extra["style"] == "chart" and extra["chart"]["image_sha256"] == hashlib.sha256(image).hexdigest()
    assert (extra["chart"]["fit"], extra["chart"]["points"], extra["chart"]["credit"]) == (
        "affine",
        4,
        CREDIT,
    )
    assert "of the diagonal" in text and "affine" in text, "the residuals in a corner"

    # The positions off the paper, and those on it beyond the points' spread (the four corners of the
    # grid, 59.70 to 59.90 N, 10.55 to 10.75 E), counted where the paper's own transform puts them.
    every = [(p["lat"], p["lon"]) for p in bundle["places"]] + [(s["lat"], s["lon"]) for s in bundle["stays"]]
    for a in bundle["assets"]:
        every += list(zip(a["track"][1::3], a["track"][2::3], strict=True))
    for j in bundle["journeys"]:
        every += list(zip(j["path"][0::2], j["path"][1::2], strict=True))
    off = [q for q in every if not (0 <= truth(*q)[0] <= cp.WIDTH and 0 <= truth(*q)[1] <= cp.HEIGHT)]
    beyond = [q for q in every if q not in off and not (59.70 <= q[0] <= 59.90 and 10.55 <= q[1] <= 10.75)]
    assert off and beyond, "the synthetic weekend reaches past the grid, and Lerka off the paper"
    assert (extra["chart"]["outside"], extra["chart"]["beyond_spread"]) == (len(off), len(beyond))
    assert f"{len(beyond):,} positions lie beyond the control points" in text
    assert f"{len(beyond):,} positions of the page lie beyond the control points' spread" in printed


def test_a_chart_photographed_at_an_angle_is_fitted_from_six_points(lb: Logbook, tmp_path: Path) -> None:
    """A homography: never through four or five points, which could not check it; from six, each
    checked by the other five."""
    out = tmp_path / "World"
    assert _fails("--out", str(out), *_paper(tmp_path, 0.15)) == 2
    assert not out.exists()
    six = [*cp.CORNERS, (59.80, 10.55), (59.80, 10.75)]
    _run("--out", str(out), *_paper(tmp_path, 0.15, six))
    text = (out / "world-chart.html").read_text(encoding="utf-8")
    chart = _chart(text)
    assert chart["fit"]["kind"] == "projective"
    transform, truth = _transform(chart), cp.known(0.15)
    for lat, lon in [*_positions(world.bundle_of(text)), HOME, MARINA, HYTTA]:
        at = transform.to_pixel(lat, lon)
        assert at is not None and math.dist(at, truth(lat, lon)) < 0.05, (lat, lon)


def test_a_bad_fit_is_refused_and_nothing_is_written(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    seq = int(lb.meta["seq"])
    out = tmp_path / "World"
    flags = _paper(tmp_path, where=[*cp.CORNERS, cp.MIDDLE])
    points = json.loads((tmp_path / "points.json").read_text(encoding="utf-8"))
    capsys.readouterr()

    # One latitude mistyped by five hundredths of a degree: refused, the threshold and the worst point named.
    points["points"][2]["lat"] = 59.85
    (tmp_path / "points.json").write_text(json.dumps(points), encoding="utf-8")
    assert _fails("--out", str(out), *flags) == 2
    err = capsys.readouterr().err
    assert "the fit is refused" in err and "1% of the chart's diagonal" in err and "crossing" in err
    assert not out.exists() and int(lb.meta["seq"]) == seq

    def refused(found: list[dict[str, Any]]) -> str:
        (tmp_path / "points.json").write_text(json.dumps({"points": found}), encoding="utf-8")
        assert _fails("--out", str(out), *flags) == 2
        return capsys.readouterr().err

    good = cp.points(cp.known())
    # a latitude and a longitude swapped everywhere: a mirror
    mirrored = [{**p, "x": cp.WIDTH - float(p["x"])} for p in good]
    assert "mirror" in refused(mirrored)
    # three points in a line
    assert "in a line" in refused([{**p, "y": 450.0} for p in good[:3]])
    # two points
    assert "three or more" in refused(good[:2])
    # a point off the image
    assert "off the chart" in refused([*good[:3], {**good[3], "x": cp.WIDTH + 40}])
    # a name past its cap
    assert "at most 80" in refused([{**good[0], "name": "N" * 81}, *good[1:]])
    assert not out.exists() and int(lb.meta["seq"]) == seq


def test_a_homography_whose_horizon_crosses_the_chart_folds_it() -> None:
    """The denominator of a projective transform is zero on its horizon: an image it crosses would be,
    in part, positions at infinity. The inverse's denominator, linear in the pixel, says where."""
    unit = (0.0, 0.0, 1.0)
    tilted = chart_fit.Transform(chart_fit.PROJECTIVE, 0.0, unit, unit, (1, 0, 0, 0, 1, 0, 0.01, 0))
    assert tilted.folds(200, 100), "the horizon at x = 100 crosses an image 200 wide"
    assert not tilted.folds(50, 100)
    flat = chart_fit.Transform(chart_fit.AFFINE, 0.0, unit, unit, (1, 0, 0, 0, -1, 0, 0, 0))
    assert not flat.folds(10_000, 10_000) and flat.jacobian_sign() < 0, "north up, y down: not a mirror"


def test_three_points_fit_exactly_and_say_they_cannot_be_checked(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "World"
    _run("--out", str(out), *_paper(tmp_path, where=cp.CORNERS[:3]))
    assert "exact through three points, unchecked" in capsys.readouterr().out
    text = (out / "world-chart.html").read_text(encoding="utf-8")
    chart = _chart(text)
    assert chart["fit"]["kind"] == "affine" and all(p["residual_px"] is None for p in chart["fit"]["points"])
    assert "unchecked" in text
    transform, truth = _transform(chart), cp.known()
    for lat, lon in _positions(world.bundle_of(text)):
        assert math.dist(transform.to_pixel(lat, lon) or (math.inf, math.inf), truth(lat, lon)) < 0.01


def test_the_image_crosses_without_what_its_file_says_about_it(lb: Logbook, tmp_path: Path) -> None:
    """A phone's photograph of a chart says where it was taken: none of it is in the page."""
    to_pixel = cp.known()
    points = cp.write_points(tmp_path / "points.json", cp.points(to_pixel))
    extra = cp.chunk(b"tEXt", b"Comment\x00" + NOTE) + cp.chunk(b"eXIf", _exif(1))
    image = tmp_path / "phone.png"
    given = cp.png(image, to_pixel, extra)
    out = tmp_path / "World"
    _run("--out", str(out), "--chart", str(image), "--control-points", str(points), "--chart-credit", CREDIT)
    text = (out / "world-chart.html").read_text(encoding="utf-8")
    embedded = base64.b64decode(_block(text, "chart-image"))
    assert NOTE not in embedded and b"tEXt" not in embedded and b"eXIf" not in embedded
    assert NOTE.decode() not in text
    kept = chart_image.png_chunks(embedded)
    assert [kind for kind, _data in kept] == [b"IHDR", b"IDAT", b"IEND"]
    assert chart_image.decode_png(kept).rows == chart_image.decode_png(chart_image.png_chunks(given)).rows

    # a JPEG: the frame, the tables and the scan kept byte for byte; EXIF, a comment and what follows
    # the end of the image left out
    phone = tmp_path / "phone.jpg"
    phone.write_bytes(_jpeg_with(_segment(0xE1, b"Exif\x00\x00" + _exif(1)), _segment(0xFE, NOTE)))
    read = chart_image.read(phone)
    assert read.mime == chart_image.JPEG and (read.width, read.height) == (24, 16)
    assert NOTE not in read.data and b"Exif" not in read.data and read.data.endswith(b"\xff\xd9")
    assert set(read.dropped) == {"APP0", "APP1", "COM"}
    scan = TINY_JPEG[TINY_JPEG.index(b"\xff\xda") :]
    assert read.data.endswith(scan), "the entropy-coded scan as it was"

    # stored turned: refused, whichever file carries it
    for turned, name in (
        (cp.png(tmp_path / "turned.png", to_pixel, cp.chunk(b"eXIf", _exif(6))), "turned.png"),
        (_jpeg_with(_segment(0xE1, b"Exif\x00\x00" + _exif(6))), "turned.jpg"),
    ):
        (tmp_path / name).write_bytes(turned)
        with pytest.raises(chart_image.ChartImageError, match="orientation 6"):
            chart_image.read(tmp_path / name)
    (tmp_path / "chart.gif").write_bytes(b"GIF89a")
    with pytest.raises(chart_image.ChartImageError, match="not a PNG or a JPEG"):
        chart_image.read(tmp_path / "chart.gif")


def test_a_png_over_the_cap_is_downscaled_and_a_jpeg_over_it_refused(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    flags = _paper(tmp_path)
    given = (tmp_path / "paper.png").read_bytes()
    monkeypatch.setattr(chart_image, "IMAGE_BYTES", len(given) // 3)
    out = tmp_path / "World"
    _run("--out", str(out), *flags)
    assert "downscaled by" in capsys.readouterr().out
    text = (out / "world-chart.html").read_text(encoding="utf-8")
    chart = _chart(text)
    factor = chart["image"]["factor"]
    assert factor >= 2
    assert (chart["image"]["width"], chart["image"]["height"]) == (
        math.ceil(cp.WIDTH / factor),
        math.ceil(cp.HEIGHT / factor),
    )
    embedded = base64.b64decode(_block(text, "chart-image"))
    assert len(embedded) <= chart_image.IMAGE_BYTES
    pixels = chart_image.decode_png(chart_image.png_chunks(embedded))
    assert (pixels.width, pixels.height) == (chart["image"]["width"], chart["image"]["height"])
    # the control points stay in the pixels of the file as given: the track lands where it did
    assert (chart["fit"]["width"], chart["fit"]["height"]) == (cp.WIDTH, cp.HEIGHT)
    transform, truth = _transform(chart), cp.known()
    for lat, lon in _positions(world.bundle_of(text)):
        assert math.dist(transform.to_pixel(lat, lon) or (math.inf, math.inf), truth(lat, lon)) < 0.01

    jpeg = tmp_path / "big.jpg"
    jpeg.write_bytes(TINY_JPEG)
    monkeypatch.setattr(chart_image, "IMAGE_BYTES", 100)
    with pytest.raises(chart_image.ChartImageError, match="pixels wide"):
        chart_image.read(jpeg)


def test_the_page_stays_under_its_cap(lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    whole = world.CAP_BYTES + world.LAND_BYTES + 4 * math.ceil(chart_image.IMAGE_BYTES / 3)
    assert whole < world_chart.PAGE_BYTES, "the record, the land and the largest image fit, with room"
    out = tmp_path / "World"
    flags = _paper(tmp_path)
    _run("--out", str(out), *flags)
    assert (out / "world-chart.html").stat().st_size <= world_chart.PAGE_BYTES

    seq = int(lb.meta["seq"])
    monkeypatch.setattr(world_chart, "PAGE_BYTES", 20_000)
    other = tmp_path / "Other"
    assert _fails("--out", str(other), *flags) == 2
    assert not other.exists() and int(lb.meta["seq"]) == seq


def test_the_flags_of_the_chart_go_together(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    flags = _paper(tmp_path)
    image, points = flags[1], flags[3]
    out = str(tmp_path / "World")
    capsys.readouterr()
    for args, says in (
        (["--chart", image, "--chart-credit", CREDIT], "--control-points"),
        (["--control-points", points], "--chart FILE"),
        (["--chart", image, "--control-points", points], "--chart-credit"),
        (["--chart", image, "--control-points", points, "--chart-credit", "  "], "--chart-credit"),
        (["--style", "modern", *flags], "--style chart"),
        (
            ["--chart", str(tmp_path / "missing.png"), "--control-points", points, "--chart-credit", CREDIT],
            "--chart",
        ),
    ):
        assert _fails("--out", out, *args) == 2, args
        assert says in capsys.readouterr().err, args
    assert not Path(out).exists()

    # the credit is the owner's words, written as text
    _run("--out", out, "--chart", image, "--control-points", points, "--chart-credit", "<b>my scan</b> & co")
    text = (Path(out) / "world-chart.html").read_text(encoding="utf-8")
    assert "&lt;b&gt;my scan&lt;/b&gt; &amp; co" in text and "<b>my scan" not in text


# -- one page per journey -----------------------------------------------------------------------------------


def test_a_journey_is_one_page(lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "World"
    passage = _passage(lb)
    _run(
        "--out", str(out), "--style", "chart", "--journey", passage, "--journey", "trip:2026-07-10:2026-07-11"
    )
    printed = capsys.readouterr().out
    assert f"the journey Marina → Hytta ({passage})" in printed
    assert sorted(p.name for p in out.iterdir()) == [
        f"world-journey-{passage}-chart.html",
        "world-trip-2026-07-10-2026-07-11-chart.html",
    ]

    # The passage: its day, it alone, the chart's day marks from that day.
    text = (out / f"world-journey-{passage}-chart.html").read_text(encoding="utf-8")
    bundle = world.bundle_of(text)
    assert (bundle["window"]["from"], bundle["window"]["to"]) == ("2026-07-10", "2026-07-10")
    assert [j["id"] for j in bundle["journeys"]] == [passage]
    assert _chart(text)["days"] == {"first": "2026-07-10", "years": False}
    assert "Marina → Hytta" in text
    assert world.validate(bundle) == []

    # The trip, as `show trips` names it: its days to the return day, every journey of them.
    trip = world.bundle_of((out / "world-trip-2026-07-10-2026-07-11-chart.html").read_text(encoding="utf-8"))
    assert (trip["window"]["from"], trip["window"]["to"]) == ("2026-07-10", "2026-07-12")
    assert [j["id"] for j in trip["journeys"]] == [passage]

    # Each page its own crossing line, naming the journey.
    lines = list(lb.lines())[-2:]
    assert [line["payload"]["extra"]["world"]["journey"] for line in lines] == [
        passage,
        "trip:2026-07-10:2026-07-11",
    ]
    assert all(line["payload"]["extra"]["world"]["style"] == "chart" for line in lines)

    # The globe's page of a journey, beside it; one page for a journey asked for twice; a trip asked for
    # by a day inside it.
    seq = int(lb.meta["seq"])
    _run("--out", str(out), "--journey", passage, "--journey", passage)
    assert (out / f"world-journey-{passage}.html").is_file() and int(lb.meta["seq"]) == seq + 1
    _run("--out", str(tmp_path / "Day"), "--style", "chart", "--journey", "2026-07-11")
    assert [p.name for p in (tmp_path / "Day").iterdir()] == ["world-trip-2026-07-10-2026-07-11-chart.html"]


def test_a_journey_the_page_may_not_show_is_refused(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = list(lb.lines())
    [taxi] = [line for line in lines if (line.get("payload") or {}).get("mode") == "ride"]
    [photo, *_rest] = [line for line in lines if line["kind"] == "photo"]
    out = str(tmp_path / "World")
    capsys.readouterr()
    for journey, says in (
        (str(taxi["id"]), "tier-3"),
        (str(photo["id"]), "not a journey"),
        ("00000000-0000-7000-8000-000000000000", "no line has that id"),
        ("trip:2026-07-12:2026-07-13", "no trip"),
    ):
        assert _fails("--out", out, "--journey", journey) == 2, journey
        assert says in capsys.readouterr().err, journey
    assert _fails("--out", out, "--journey", _passage(lb), "--from", "2026-07-10") == 2
    assert "--journey" in capsys.readouterr().err
    assert not Path(out).exists()
