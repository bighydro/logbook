"""`logbook export world [--out DIR] [--from DATE --to DATE] [--tier 1|1,2]`: the record as one page you
can scrub — the world outline from the bundled Natural Earth land table, the named places as anchors,
the assets as moving dots along their own tracks, the owner's stays as dots, the journeys as tracks,
the chapters as bands on the time scrubber — every byte of it bundled into one HTML file at export time,
under a documented cap, nothing fetched, tier-gated under the `world` entry of the policy (tier 2 when the
file does not name it), recorded as a crossing/v1 line; and the same page at `/world` in the Library.
The synthetic weekend of `tests/world_record.py`; nobody in it is real."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from world_record import (
    ASSETS,
    CHAPTER,
    HOME,
    MARINA,
    OWNER_DECIMALS,
    PLACES,
    PLANE,
    PLANE_DECIMALS,
    PLANE_REGISTRATION,
    YACHT,
    YACHT_DECIMALS,
    YACHT_MMSI,
    fix,
    still,
    world_record,
)

from logbook import cli
from logbook.contrib import serve, world
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite|background)\s*=\s*["']([^"']*)["']""", re.I
)
FETCHERS = ("fetch(", "XMLHttpRequest", "import(", "WebSocket", "EventSource", "sendBeacon", "Worker(")


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return world_record(tmp_path, monkeypatch)


def _run(*args: str) -> None:
    cli.main(["export", "world", *args])


def _fails(*args: str) -> int:
    with pytest.raises(SystemExit) as e:
        _run(*args)
    return int(e.value.code or 0)


def _page(out: Path) -> str:
    return (out / world.FILE_NAME).read_text(encoding="utf-8")


def _export(tmp_path: Path, *args: str) -> tuple[str, dict[str, Any]]:
    out = tmp_path / "World"
    _run("--out", str(out), *args)
    text = _page(out)
    return text, world.bundle_of(text)


def _policy(lb: Logbook, max_tier: int) -> Path:
    path = lb.root / "policy" / "crossing.json"
    path.parent.mkdir(exist_ok=True)
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data["world"] = {"max_tier": max_tier}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _decimals(value: float) -> int:
    text = repr(float(value))
    frac = text.partition(".")[2]
    return 0 if frac == "0" else len(frac)


def _coordinates(bundle: dict[str, Any]) -> dict[str, list[float]]:
    """Every coordinate the bundle carries, by where it came from."""
    out: dict[str, list[float]] = {"places": [], "stays": [], YACHT: [], PLANE: [], "journeys": []}
    for p in bundle["places"]:
        out["places"] += [p["lat"], p["lon"]]
    for s in bundle["stays"]:
        out["stays"] += [s["lat"], s["lon"]]
    for a in bundle["assets"]:
        track = a["track"]
        out[a["id"].removeprefix("asset:")] += [v for i, v in enumerate(track) if i % 3]
    for j in bundle["journeys"]:
        out["journeys"] += j["path"]
    return out


# -- the page -----------------------------------------------------------------------------------------------


def test_the_world_is_one_page_with_the_outline_the_anchors_the_assets_the_stays_the_journey_and_the_chapter(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text, bundle = _export(tmp_path)
    out = capsys.readouterr().out
    assert f"world: 4 days 2026-07-10 {world.EN_DASH} 2026-07-13, tier 1,2" in out, out
    assert str(tmp_path / "World" / world.FILE_NAME) in out

    # One file, the map drawn on a canvas by the page's one script, the scrubber below it.
    assert [p.name for p in (tmp_path / "World").iterdir()] == [world.FILE_NAME]
    assert "<canvas" in text and 'type="range"' in text
    assert text.count("<script>") == 1, "one inline script, the page's own"

    # The world outline: the vendored Natural Earth table, bundled whole.
    land = json.loads(re.search(r'<script type="application/json" id="land">(.*?)</script>', text, re.S)[1])
    assert land == world.land()

    window = bundle["window"]
    assert (window["from"], window["to"], window["tz"]) == ("2026-07-10", "2026-07-13", "Europe/Oslo")
    assert bundle["tiers"] == [1, 2]

    # The three places as anchors, in places.json's order, as the file spells them.
    assert [(p["id"], p["name"], p["kind"]) for p in bundle["places"]] == [
        ("place:Home", "Home", "home"),
        ("place:Marina", "Marina", "asset-berth"),
        ("place:Hytta", "Hytta", "other"),
    ]

    # Both assets, each on its own track: minutes from the window's start, lat, lon.
    assets = {a["id"]: a for a in bundle["assets"]}
    assert list(assets) == [f"asset:{YACHT}", f"asset:{PLANE}"]
    assert (assets[f"asset:{YACHT}"]["name"], assets[f"asset:{YACHT}"]["kind"]) == ("Havbris", "yacht")
    assert (assets[f"asset:{PLANE}"]["name"], assets[f"asset:{PLANE}"]["kind"]) == ("Lerka", "aircraft")
    for asset in assets.values():
        track = asset["track"]
        assert len(track) % 3 == 0 and len(track) >= 6
        minutes = track[0::3]
        assert minutes == sorted(minutes) and minutes[0] >= 0 and minutes[-1] <= window["minutes"]
    plane = assets[f"asset:{PLANE}"]["track"][0::3]
    assert plane[0] >= 3 * 1440 + 11 * 60 and plane[-1] <= 3 * 1440 + 12 * 60 + 30, "Monday's loop only"

    # The owner's stays, folded as the Day folds them: home, aboard Havbris, Hytta, home again.
    stays = bundle["stays"]
    assert [(s["place"], s["aboard"]) for s in stays] == [
        ("place:Home", None),
        (None, f"asset:{YACHT}"),
        ("place:Hytta", None),
        ("place:Home", None),
    ]
    assert [s["night"] for s in stays] == [False, True, True, True]
    assert all(s["t0"] < s["t1"] for s in stays)

    # The one journey that crosses at tier 2: the passage, Havbris's, drawn along its route.
    [journey] = bundle["journeys"]
    assert journey["name"] == "Marina → Hytta" and journey["mode"] == "passage"
    assert journey["subject"] == f"asset:{YACHT}"
    assert journey["places"] == ["place:Marina", "place:Hytta"]
    assert journey["path"][:2] == [59.905, 10.735] and len(journey["path"]) == 8
    assert journey["t0"] == 17 * 60 and journey["t1"] == 20 * 60

    # The chapter, named after the weekend, as a band over the whole window it covers.
    [band] = bundle["chapters"]
    assert band["name"] == CHAPTER and (band["from"], band["to"]) == ("2026-07-01", "2026-08-15")
    assert (band["t0"], band["t1"]) == (0, window["minutes"])


def test_every_referenced_id_exists(lb: Logbook, tmp_path: Path) -> None:
    """A stay names a place and an asset, a journey its asset and its places, the summaries every place
    and asset: each one is in the bundle, and the export refuses to write a page where one is not."""
    _text, bundle = _export(tmp_path)
    assert world.validate(bundle) == []
    ids = {p["id"] for p in bundle["places"]} | {a["id"] for a in bundle["assets"]}
    assert set(bundle["summaries"]) == ids
    referenced = {s["place"] for s in bundle["stays"]} | {s["aboard"] for s in bundle["stays"]}
    for j in bundle["journeys"]:
        referenced |= {j["subject"], *j["places"]}
    assert referenced - {None} <= ids

    broken = json.loads(json.dumps(bundle))
    broken["stays"][0]["place"] = "place:Nowhere"
    broken["journeys"][0]["subject"] = "asset:gone"
    del broken["summaries"]["place:Hytta"]
    problems = world.validate(broken)
    assert any("place:Nowhere" in p for p in problems)
    assert any("asset:gone" in p for p in problems)
    assert any("place:Hytta" in p for p in problems)


def test_clicking_an_anchor_or_an_asset_shows_its_page_summary(lb: Logbook, tmp_path: Path) -> None:
    """Nights, journeys and photos per place and per asset, counted from the whole reading: a night at a
    place is a night whose stay lay there, a night aboard is the asset's; a journey counts for the places
    at its ends and for its asset; a photo for the place of the stay it was taken in, and for the asset
    the owner was aboard (a passage too)."""
    _text, bundle = _export(tmp_path)
    s = bundle["summaries"]
    counts = {key: (v["nights"], v["journeys"], v["photos"]) for key, v in s.items()}
    assert counts == {
        "place:Home": (2, 0, 0),
        "place:Marina": (0, 1, 0),
        "place:Hytta": (1, 1, 2),
        f"asset:{YACHT}": (1, 1, 1),
        f"asset:{PLANE}": (0, 0, 0),
    }
    assert s["place:Hytta"]["first"] == "2026-07-11" and s["place:Hytta"]["last"] == "2026-07-12"
    assert s[f"asset:{YACHT}"]["identifiers"] == {"mmsi": YACHT_MMSI}
    assert s[f"asset:{PLANE}"]["identifiers"] == {"icao24": "000a07", "registration": PLANE_REGISTRATION}
    assert (s[f"asset:{PLANE}"]["first"], s[f"asset:{PLANE}"]["last"]) == ("2026-07-13", "2026-07-13")


def test_no_coordinate_is_more_precise_than_the_records_own(lb: Logbook, tmp_path: Path) -> None:
    """A place as places.json spells it, a fix as its line does, a journey's route as its line does; a
    stay's centre, which the reader computes, at no more decimals than the points it came from."""
    _text, bundle = _export(tmp_path)
    found = _coordinates(bundle)
    allowed = {
        "places": 4,
        "stays": OWNER_DECIMALS,
        YACHT: YACHT_DECIMALS,
        PLANE: PLANE_DECIMALS,
        "journeys": 4,
    }
    for where, values in found.items():
        assert values, where
        assert max(_decimals(v) for v in values) <= allowed[where], where
    assert {(p["lat"], p["lon"]) for p in bundle["places"]} == {(v["lat"], v["lon"]) for v in PLACES.values()}


# -- the cap ------------------------------------------------------------------------------------------------


def test_the_json_is_under_the_cap_and_a_smaller_cap_thins_the_tracks_not_the_counts(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    text, bundle = _export(tmp_path)
    embedded = world.embedded_json(text)
    assert len(embedded.encode("utf-8")) <= world.CAP_BYTES
    assert bundle["thinned"]["track_step_min"] == world.TRACK_STEP_MIN
    assert len(world.land_json().encode("utf-8")) <= world.LAND_BYTES
    capsys.readouterr()

    # A cap just under what the full page needs: the tracks are thinned until it fits, the counts not.
    monkeypatch.setattr(world, "CAP_BYTES", len(embedded.encode("utf-8")) - 1)
    out = tmp_path / "Thinner"
    _run("--out", str(out))
    printed = capsys.readouterr().out
    thinner_text = _page(out)
    thinner = world.bundle_of(thinner_text)
    assert len(world.embedded_json(thinner_text).encode("utf-8")) <= world.CAP_BYTES
    assert thinner["thinned"]["track_step_min"] > world.TRACK_STEP_MIN
    assert "thinned" in printed
    assert sum(len(a["track"]) for a in thinner["assets"]) < sum(len(a["track"]) for a in bundle["assets"])
    assert thinner["summaries"] == bundle["summaries"] and thinner["journeys"] == bundle["journeys"]
    assert world.validate(thinner) == []

    # A cap nothing fits under: refused, naming the cap and the way out, and nothing written.
    monkeypatch.setattr(world, "CAP_BYTES", 400)
    nowhere = tmp_path / "Nowhere"
    assert _fails("--out", str(nowhere)) == 2
    err = capsys.readouterr().err
    assert "cap" in err and "--from" in err
    assert not nowhere.exists()


def test_the_land_table_is_natural_earth_at_110m_under_its_cap() -> None:
    land = world.land()
    assert "Natural Earth" in land["source"] and "public domain" in land["source"]
    assert land["scale"] == 100
    polygons = land["polygons"]
    assert len(polygons) > 100
    for polygon in polygons:
        for ring in polygon:
            assert len(ring) >= 6 and len(ring) % 2 == 0
            lon, lat, points = ring[0], ring[1], [(ring[0], ring[1])]
            for i in range(2, len(ring), 2):
                lon, lat = lon + ring[i], lat + ring[i + 1]
                points.append((lon, lat))
            assert all(-18000 <= x <= 18000 and -9000 <= y <= 9000 for x, y in points)
    raw = (ROOT / "logbook" / "tables" / "land.json").read_bytes()
    assert len(raw) <= world.LAND_BYTES


# -- nothing fetched ----------------------------------------------------------------------------------------


def test_nothing_is_fetched_by_the_export_or_by_the_page(
    lb: Logbook, tmp_path: Path, no_network: list[str]
) -> None:
    text, _bundle = _export(tmp_path)
    assert no_network == [], "the export opened no connection"

    low = text.lower()
    assert REFERENCE.findall(text) == [], "no attribute that can hold a URL"
    for tag in ("<link", "<iframe", "<frame", "<object", "<embed", "<base", "<img", "<audio", "<video"):
        assert tag not in low, tag
    for needle in FETCHERS:
        assert needle not in text, needle
    assert "url(" not in low and "@import" not in low
    assert "http:" not in low and "https:" not in low and "//" not in re.sub(r"\\/", "", _scripts(text))

    # The policy the file carries: nothing from anywhere, the one script by its hash.
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', text)
    assert csp is not None
    assert csp[1].startswith("default-src 'none'") and f"script-src '{world.SCRIPT_HASH}'" in csp[1]
    script = re.search(r"<script>(.*?)</script>", text, re.S)
    assert script is not None
    digest = base64.b64encode(hashlib.sha256(script[1].encode("utf-8")).digest()).decode()
    assert f"sha256-{digest}" == world.SCRIPT_HASH

    # The synthetic check the published site is held to: no identifier outside the allowlist, no URL.
    checked = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_synthetic.py"), str(tmp_path / "World")],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr


def _scripts(text: str) -> str:
    """The page's executable script, the one place a `//` comment could hide a URL."""
    found = re.search(r"<script>(.*?)</script>", text, re.S)
    return "" if found is None else re.sub(r"/\*.*?\*/", "", found[1], flags=re.S)


# -- the gate -----------------------------------------------------------------------------------------------


def test_tier_2_by_default_and_the_policy_entry_world_sets_the_ceiling(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The default: tiers 1 and 2. The chapter (tier 2) is a band; the taxi (tier 3) is nowhere, not even
    # in a count, and the page says one line was held back.
    _text, bundle = _export(tmp_path)
    assert [c["name"] for c in bundle["chapters"]] == [CHAPTER]
    assert [j["mode"] for j in bundle["journeys"]] == ["passage"]
    assert bundle["summaries"]["place:Home"]["journeys"] == 0
    assert bundle["held_back"] == {"lines": 1, "by_kind": {"journey": 1}}
    assert "held back: 1 line above tier 2 (journey 1)" in capsys.readouterr().out

    # --tier 1: the chapter is held back too.
    _text, tier1 = _export(tmp_path, "--tier", "1")
    assert tier1["tiers"] == [1] and tier1["chapters"] == []
    assert tier1["held_back"] == {"lines": 2, "by_kind": {"chapter": 1, "journey": 1}}

    # Tier 3 is above the default ceiling: refused, naming the file and the entry that would allow it.
    assert _fails("--out", str(tmp_path / "x"), "--tier", "1,2,3") == 2
    err = capsys.readouterr().err
    assert "crossing.json" in err and '"world"' in err

    # Raised to 3 by the owner: the taxi crosses, and counts for Home and Hytta.
    _policy(lb, 3)
    _text, tier3 = _export(tmp_path, "--tier", "1,2,3")
    assert sorted(j["mode"] for j in tier3["journeys"]) == ["passage", "ride"]
    assert tier3["summaries"]["place:Home"]["journeys"] == 1
    assert tier3["summaries"]["place:Hytta"]["journeys"] == 2
    assert world.validate(tier3) == []

    # Lowered to 1: the default follows the ceiling down, and 1,2 is refused.
    path = _policy(lb, 1)
    _text, lowered = _export(tmp_path)
    assert lowered["tiers"] == [1]
    assert _fails("--out", str(tmp_path / "x"), "--tier", "1,2") == 2
    assert str(path) in capsys.readouterr().err


def test_from_and_to_narrow_the_window_and_the_bands_are_cut_to_it(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _text, bundle = _export(tmp_path, "--from", "2026-07-11", "--to", "2026-07-12")
    window = bundle["window"]
    assert (window["from"], window["to"], window["minutes"]) == ("2026-07-11", "2026-07-12", 2 * 1440)
    assert [s["place"] for s in bundle["stays"]][-2:] == ["place:Hytta", "place:Home"]
    assert bundle["journeys"] == [], "the passage was on Friday"
    plane = next(a for a in bundle["assets"] if a["id"] == f"asset:{PLANE}")
    assert plane["track"] == [], "Lerka flew on Monday; registered, so still an anchor of the page"
    assert bundle["summaries"][f"asset:{PLANE}"]["first"] is None
    [band] = bundle["chapters"]
    assert (band["t0"], band["t1"]) == (0, window["minutes"])
    assert world.validate(bundle) == []

    capsys.readouterr()
    assert _fails("--from", "2026-07-12", "--to", "2026-07-11") == 2
    assert "--from" in capsys.readouterr().err
    assert _fails("--from", "July") == 2


def test_a_window_across_new_year_is_read_a_year_at_a_time_and_its_stay_is_one_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The readings are a calendar year each and overlap by the night after their last day: the stay at
    home from the 30th of December to the 2nd of January is one stay on the page, its three nights are
    counted once each, the boat's fixes once each. A subject `assets.json` does not name is an asset of
    the page under its own id (ADR 0018 rule 4)."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    drafts = still("2025-12-30", "12:00", "24:00", HOME, 10)
    drafts += still("2025-12-31", "00:00", "24:00", HOME, 10) + still(
        "2026-01-01", "00:00", "24:00", HOME, 10
    )
    drafts += still("2026-01-02", "00:00", "12:00", HOME, 10)
    for day in ("2025-12-30", "2025-12-31", "2026-01-01", "2026-01-02"):
        drafts += still(day, "00:00", "24:00", MARINA, 30, YACHT)
    old = [
        fix(d["at"], (59.9, 10.7), "gamle-baten", 3)
        for d in still("2025-12-31", "10:00", "12:00", MARINA, 30)
    ]
    lb.append_many(drafts + old)
    (lb.root / "assets.json").write_text(json.dumps({"assets": [ASSETS[0]]}), encoding="utf-8")
    (lb.root / "places.json").write_text(json.dumps({"Home": PLACES["Home"]}), encoding="utf-8")

    _text, bundle = _export(tmp_path)
    assert (bundle["window"]["from"], bundle["window"]["to"]) == ("2025-12-30", "2026-01-02")
    assert [(s["place"], s["night"]) for s in bundle["stays"]] == [("place:Home", True)]
    assert bundle["summaries"]["place:Home"]["nights"] == 3
    assert (bundle["summaries"]["place:Home"]["first"], bundle["summaries"]["place:Home"]["last"]) == (
        "2025-12-30",
        "2026-01-02",
    )
    assets = {a["id"]: a for a in bundle["assets"]}
    assert list(assets) == [f"asset:{YACHT}", "asset:gamle-baten"]
    assert (assets["asset:gamle-baten"]["name"], assets["asset:gamle-baten"]["kind"]) == ("gamle-baten", None)
    minutes = assets[f"asset:{YACHT}"]["track"][0::3]
    assert len(minutes) == len(set(minutes)), "a fix the two readings share is drawn once"
    assert bundle["thinned"]["fixes"]["of"] == 4 * 48 + 4
    assert bundle["summaries"]["asset:gamle-baten"]["identifiers"] == {}
    assert world.validate(bundle) == []


# -- the export ---------------------------------------------------------------------------------------------


def test_every_run_appends_one_crossing_line_and_a_rerun_rewrites_nothing(
    lb: Logbook, tmp_path: Path
) -> None:
    out = tmp_path / "World"
    seq = int(lb.meta["seq"])
    _run("--out", str(out))
    first = (out / world.FILE_NAME).read_bytes()
    lines = list(lb.lines())
    assert len(lines) == seq + 1
    line = lines[-1]
    assert line["kind"] == "crossing" and line["tier"] == 1
    payload = line["payload"]
    assert payload["destination"] == "world" and payload["tiers"] == [1, 2]
    assert payload["policy"] == {"file": "policy/crossing.json", "max_tier": 2}
    assert payload["counts"]["held_back"] == 1 and payload["counts"]["by_kind"]["journey"] == 1
    assert (
        payload["package_sha256"]
        == hashlib.sha256(
            hashlib.sha256(first).hexdigest().encode() + b"  " + world.FILE_NAME.encode() + b"\n"
        ).hexdigest()
    )
    extra = payload["extra"]["world"]
    assert (extra["places"], extra["assets"], extra["stays"], extra["journeys"], extra["chapters"]) == (
        3,
        2,
        4,
        1,
        1,
    )
    assert extra["bytes"] == len(first)

    # The page is a function of the record's lines and settings, never of its head: the crossing line
    # just appended changes nothing in it, and the file is not rewritten.
    mtime = (out / world.FILE_NAME).stat().st_mtime_ns
    _run("--out", str(out))
    assert (out / world.FILE_NAME).read_bytes() == first
    assert (out / world.FILE_NAME).stat().st_mtime_ns == mtime
    assert len(list(lb.lines())) == seq + 2


def test_the_default_folder_is_under_the_record_and_an_empty_record_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    empty = Logbook.init(tmp_path / "empty", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(empty.root))
    _run()
    assert "nothing written" in capsys.readouterr().out
    assert not (empty.root / "export").exists() and int(empty.meta["seq"]) == 0

    lb = world_record(tmp_path / "full", monkeypatch)
    _run()
    assert (lb.root / "export" / "world" / world.FILE_NAME).is_file()


# -- the Library --------------------------------------------------------------------------------------------


def test_the_library_serves_the_same_page_at_world(lb: Logbook, tmp_path: Path) -> None:
    text, bundle = _export(tmp_path)
    seq = int(lb.meta["seq"])
    site = serve.Site(lb)
    response = site.respond("/world", "")
    assert response.status == 200
    served = response.body.decode("utf-8")
    assert world.embedded_json(served) == world.embedded_json(text), "the same data, byte for byte"
    assert world.bundle_of(served) == bundle
    assert (
        re.search(r"<script>(.*?)</script>", served, re.S)[1]
        == re.search(r"<script>(.*?)</script>", text, re.S)[1]
    )
    csp = response.headers["Content-Security-Policy"]
    assert csp.startswith("default-src 'none'") and f"script-src '{world.SCRIPT_HASH}'" in csp
    assert "<meta http-equiv" not in served, "the server sends the policy as a header"
    assert 'href="/"' in served, "the Library's navigation, back to the front page"
    assert response.etag is not None, "a page of the record at its head"
    assert site.respond("/world", "", if_none_match=response.etag).status == 304

    narrowed = world.bundle_of(site.respond("/world", "from=2026-07-11&to=2026-07-12").body.decode("utf-8"))
    assert narrowed["window"]["from"] == "2026-07-11" and narrowed["journeys"] == []
    assert site.respond("/world", "from=2026-07-12&to=2026-07-11").status == 400
    assert 'href="/world"' in site.respond("/", "").body.decode("utf-8"), "in the navigation"
    assert int(lb.meta["seq"]) == seq, "serving appends nothing"


def test_a_line_far_in_the_future_does_not_stretch_the_slider_past_today(lb: Logbook) -> None:
    """A calendar names the future (a renewal in 2055, a recurring entry with no end): the default
    window, and with it the time slider, still ends on the owner's today, never on the latest line
    the record holds; asked for by `--to`, the future is still there to read."""
    whole = world.request(lb)
    assert whole is not None
    lb.append(
        at="2055-03-01T09:00:00Z",
        source="ics",
        kind="event",
        tier=1,
        payload={"schema": "event/v1", "title": "Passport renewal", "raw_id": "cal:renewal-2055"},
    )
    req = world.request(lb, today=whole.last)
    assert req is not None and (req.first, req.last) == (whole.first, whole.last)
    later = world.request(lb, today="2026-12-31")
    assert later is not None and later.last == "2026-12-31", "the window reaches today, not 2055"
    asked = world.request(lb, last="2055-03-01", today=whole.last)
    assert asked is not None and asked.last == "2055-03-01"
    site = serve.Site(lb, now=lambda: datetime.fromisoformat(f"{whole.last}T12:00:00+00:00"))
    page = site.respond("/world", "").body.decode("utf-8")
    assert "2055" not in page
