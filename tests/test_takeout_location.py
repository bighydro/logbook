"""Google Takeout → location/v1: Records.json (the archive) and Timeline.json (the on-device export)."""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import dawarich
from logbook.adapters.takeout import location
from logbook.export import write_day_package
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "takeout"
RECORDS = FIXTURES / "Records.json"
TIMELINE = FIXTURES / "Timeline.json"
DAWARICH = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}


def _records(i: int) -> dict:
    return json.loads(RECORDS.read_text(encoding="utf-8"))["locations"][i]


def _day_package(tmp_path: Path) -> Path:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append(
        at="2026-03-01T07:30:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.911, "lon": 10.75},
    )
    out = tmp_path / "pkg"
    write_day_package(lb, "2026-03-01", out)
    return out / "package.json"


# -- registry ---------------------------------------------------------------


def test_registry_lists_google_takeout_location():
    assert "google-takeout-location" in [a.NAME for a in adapters.all_adapters()]


@pytest.mark.parametrize("fixture", [RECORDS, TIMELINE])
def test_registry_find_returns_takeout_for_both_shapes(fixture):
    found = adapters.find(fixture)
    assert found is not None and found.NAME == "google-takeout-location"


def test_registry_find_still_returns_dawarich_for_its_export():
    found = adapters.find(DAWARICH)
    assert found is not None and found.NAME == "dawarich"


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_records():
    assert location.sniff(RECORDS) is True


def test_sniff_accepts_timeline():
    assert location.sniff(TIMELINE) is True


def test_sniff_rejects_dawarich_export():
    assert location.sniff(DAWARICH) is False


def test_dawarich_sniff_rejects_takeout():
    assert dawarich.sniff(RECORDS) is False and dawarich.sniff(TIMELINE) is False


def test_sniff_rejects_day_package(tmp_path):
    assert location.sniff(_day_package(tmp_path)) is False


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        "",
        "[]",
        '{"locations": []}',
        '{"semanticSegments": []}',
        '{"locations": [{"timestamp": "2026-03-01T07:30:00Z"}]}',
        '{"locations": "nope"}',
        '{"semanticSegments": [42]}',
        '{"features": [{"properties": {"latitudeE7": 1, "longitudeE7": 2}}]}',
        '[{"latitudeE7": 599110000, "longitudeE7": 107500000, "timestamp": "2026-03-01T07:30:00Z"}]',
    ],
)
def test_sniff_rejects_other_files(tmp_path, content):
    p = tmp_path / "file.json"
    p.write_text(content, encoding="utf-8")
    assert location.sniff(p) is False


def test_sniff_rejects_directory(tmp_path):
    assert location.sniff(tmp_path) is False


def test_sniff_rejects_missing_file(tmp_path):
    assert location.sniff(tmp_path / "nope.json") is False


def test_sniff_gives_up_on_a_large_unrelated_document(tmp_path):
    """A big JSON object whose Takeout key comes after a huge array is not streamed to the end."""
    p = tmp_path / "big.json"
    with p.open("w", encoding="utf-8") as fh:
        fh.write('{"rows": [')
        fh.write(",".join('{"a": 1, "b": [1, 2, 3]}' for _ in range(200_000)))
        fh.write('], "locations": [{"latitudeE7": 1, "longitudeE7": 2, "timestamp": "x"}]}')
    assert location.sniff(p) is False


# -- run: envelope -----------------------------------------------------------


@pytest.mark.parametrize(("fixture", "n"), [(RECORDS, 6), (TIMELINE, 7)])
def test_run_yields_location_lines_with_the_takeout_source(fixture, n):
    lines = list(location.run(fixture))
    assert len(lines) == n
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "google-takeout"
        assert line["kind"] == "location" and line["tier"] == 1
        assert line["payload"]["schema"] == "location/v1"
        assert type(line["payload"]["lat"]) is float and type(line["payload"]["lon"]) is float
        json.dumps(line)


def test_run_since_filters_out_earlier_points():
    lines = list(location.run(RECORDS, since="2026-03-01T08:30:00Z"))
    assert lines and all(line["at"] >= "2026-03-01T08:30:00Z" for line in lines)
    assert len(lines) == 3


# -- run: Records.json ---------------------------------------------------------


def test_records_maps_e7_coordinates_and_iso_timestamp_to_the_second():
    first = next(location.run(RECORDS))
    assert first["at"] == "2026-03-01T07:30:00Z"
    p = first["payload"]
    assert p["lat"] == 59.911 and p["lon"] == 10.75
    assert p["accuracy_m"] == 12 and p["alt_m"] == 14
    assert p["provider"] == "wifi"
    assert p["tracker"] == "123456789"
    assert p["raw_id"] == "records:123456789:2026-03-01T07:30:00.123Z"


def test_records_extra_keeps_every_field_it_could_not_map():
    raw = _records(0)
    extra = next(location.run(RECORDS))["payload"]["extra"]
    assert extra["verticalAccuracy"] == raw["verticalAccuracy"]
    assert extra["platformType"] == raw["platformType"]
    assert extra["formFactor"] == raw["formFactor"]
    assert extra["batteryCharging"] is False
    assert extra["serverTimestamp"] == raw["serverTimestamp"]
    assert extra["deviceTimestamp"] == raw["deviceTimestamp"]
    assert extra["osLevel"] == raw["osLevel"]
    for mapped in ("latitudeE7", "longitudeE7", "accuracy", "altitude", "timestamp", "deviceTag", "source"):
        assert mapped not in extra


def test_records_maps_velocity_heading_and_activity():
    raw = _records(1)
    p = list(location.run(RECORDS))[1]["payload"]
    assert p["speed_mps"] == 1 and p["heading_deg"] == 37 and p["provider"] == "gps"
    assert p["extra"]["activity"] == raw["activity"]


def test_records_provider_cell_and_unknown():
    lines = list(location.run(RECORDS))
    assert lines[2]["payload"]["provider"] == "cell"
    unknown = lines[3]["payload"]
    assert "provider" not in unknown and unknown["extra"]["source"] == "UNKNOWN"


def test_records_old_shape_timestamp_ms_and_no_source():
    line = list(location.run(RECORDS))[4]
    assert line["at"] == datetime.fromtimestamp(1772354700, __import__("datetime").UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    p = line["payload"]
    assert "provider" not in p and "source" not in p["extra"]
    assert p["tracker"] == "987654321"
    assert p["raw_id"] == "records:987654321:1772354700000"


def test_records_skips_entries_without_timestamp_or_with_missing_coordinate():
    counts: dict[str, int] = {}
    lines = list(location.run(RECORDS, counts=counts))
    assert [line["at"] for line in lines] == [
        "2026-03-01T07:30:00Z",
        "2026-03-01T08:05:00Z",
        "2026-03-01T08:20:00Z",
        "2026-03-01T08:40:00Z",
        "2026-03-01T08:45:00Z",
        "2026-03-01T09:40:00Z",
    ]
    assert counts == {"skipped_no_timestamp": 1, "skipped_bad_coordinates": 1}


def test_records_skips_non_numeric_and_out_of_range_coordinates(tmp_path):
    """JSON cannot carry NaN or infinity (ijson refuses them), so what reaches the adapter is a
    number outside the globe, a string, or nothing; all three are unusable."""
    doc = {
        "locations": [
            {"latitudeE7": 1e300, "longitudeE7": 107500000, "timestamp": "2026-03-01T07:30:00Z"},
            {"latitudeE7": "59.9", "longitudeE7": 107500000, "timestamp": "2026-03-01T07:31:00Z"},
            {"latitudeE7": 999000000, "longitudeE7": 107500000, "timestamp": "2026-03-01T07:32:00Z"},
            {"latitudeE7": 599110000, "longitudeE7": 1900000000, "timestamp": "2026-03-01T07:33:00Z"},
            {"latitudeE7": 599110000, "longitudeE7": 107500000, "timestamp": "not a time"},
            {"latitudeE7": 599110000, "longitudeE7": 107500000, "timestamp": "2026-03-01T07:35:00Z"},
        ]
    }
    p = tmp_path / "Records.json"
    p.write_text(json.dumps(doc), encoding="utf-8")
    counts: dict[str, int] = {}
    lines = list(location.run(p, counts=counts))
    assert [line["at"] for line in lines] == ["2026-03-01T07:35:00Z"]
    assert counts == {"skipped_no_timestamp": 1, "skipped_bad_coordinates": 4}


# -- run: Timeline.json --------------------------------------------------------


def test_timeline_path_points_are_raw_lines_in_utc():
    path_lines = [
        line for line in location.run(TIMELINE) if line["payload"]["extra"]["segment"] == "timelinePath"
    ]
    assert [line["at"] for line in path_lines] == [
        "2026-03-01T08:01:00Z",
        "2026-03-01T08:12:00Z",
        "2026-03-01T08:34:00Z",
    ]
    p = path_lines[0]["payload"]
    assert p["lat"] == 59.911 and p["lon"] == 10.75
    assert p["raw_id"] == "path:2026-03-01T09:01:00.000+01:00"
    assert "accuracy_m" not in p and "provider" not in p
    assert path_lines[1]["payload"]["extra"]["mode"] == "WALKING"
    assert "mode" not in p["extra"]


def test_timeline_visit_emits_start_and_end_at_the_place_and_nothing_else():
    lines = list(location.run(TIMELINE))
    start, end = lines[0], lines[1]
    assert start["at"] == "2026-03-01T06:00:00Z" and end["at"] == "2026-03-01T08:00:00Z"
    for line in (start, end):
        p = line["payload"]
        assert p["lat"] == 59.911 and p["lon"] == 10.75
        assert line["end"] is None
        assert p["extra"]["segment"] == "visit"
        assert p["extra"]["visit"]["topCandidate"]["semanticType"] == "HOME"
        assert p["extra"]["segment_start"] == "2026-03-01T07:00:00.000+01:00"
        assert p["extra"]["segment_end"] == "2026-03-01T09:00:00.000+01:00"
    assert start["payload"]["extra"]["edge"] == "start" and end["payload"]["extra"]["edge"] == "end"
    assert start["payload"]["raw_id"] == "visit:2026-03-01T07:00:00.000+01:00:start"
    assert end["payload"]["raw_id"] == "visit:2026-03-01T09:00:00.000+01:00:end"
    assert start["kind"] == "location"  # never a "stay": that is engine work (ADR 0011)


def test_timeline_activity_emits_start_and_end_coordinates():
    lines = list(location.run(TIMELINE))
    start, end = lines[2], lines[3]
    assert start["at"] == "2026-03-01T08:00:00Z" and end["at"] == "2026-03-01T08:35:00Z"
    assert (start["payload"]["lat"], start["payload"]["lon"]) == (59.911, 10.75)
    assert (end["payload"]["lat"], end["payload"]["lon"]) == (59.913, 10.742)
    assert start["payload"]["extra"]["segment"] == "activity"
    assert start["payload"]["extra"]["activity"]["topCandidate"]["type"] == "WALKING"
    assert start["payload"]["extra"]["activity"]["distanceMeters"] == 640.5
    assert start["payload"]["raw_id"] == "activity:2026-03-01T09:00:00.000+01:00:start"
    assert end["payload"]["raw_id"] == "activity:2026-03-01T09:35:00.000+01:00:end"


def test_timeline_skips_bad_points_and_visits_without_a_place_and_counts_them():
    counts: dict[str, int] = {}
    lines = list(location.run(TIMELINE, counts=counts))
    assert len(lines) == 7
    assert counts == {"skipped_no_timestamp": 1, "skipped_bad_coordinates": 3}
    assert all(math.isfinite(line["payload"]["lat"]) for line in lines)


def test_timeline_segment_without_coordinates_emits_nothing():
    lines = list(location.run(TIMELINE))
    assert not any("timelineMemory" in line["payload"]["extra"] for line in lines)


def test_timeline_since_compares_in_utc_and_keeps_export_order():
    lines = list(location.run(TIMELINE, since="2026-03-01T08:30:00Z"))
    assert [line["at"] for line in lines] == ["2026-03-01T08:35:00Z", "2026-03-01T08:34:00Z"]


# -- the log --------------------------------------------------------------------


def test_lines_from_both_shapes_append_into_one_valid_logbook(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(location.run(RECORDS)) == 6
    assert lb.append_many(location.run(TIMELINE)) == 7
    assert lb.append_many(location.run(RECORDS)) == 0  # stable raw_id → re-adding appends nothing
    assert lb.append_many(location.run(TIMELINE)) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 13
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


# -- property: every emitted line is a valid location/v1 observation -------------------


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "location" and line["tier"] == 1 and line["end"] is None
    assert line["source"] == "google-takeout"
    assert line["at"].endswith("Z") and len(line["at"]) == 20
    p = line["payload"]
    assert p["schema"] == "location/v1"
    assert type(p["lat"]) is float and type(p["lon"]) is float
    assert -90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180
    for key in ("accuracy_m", "alt_m", "speed_mps", "heading_deg"):
        if key in p:
            assert isinstance(p[key], int | float) and math.isfinite(p[key])
    if "heading_deg" in p:
        assert 0 <= p["heading_deg"] <= 360
    if "provider" in p:
        assert p["provider"] in {"gps", "wifi", "cell", "fused", "manual"}
    assert isinstance(p["raw_id"], str) and p["raw_id"]
    assert isinstance(p.get("extra", {}), dict)
    json.dumps(line, allow_nan=False)


def _validate_through_the_log(tmp_path_factory, drafts: list[dict]) -> None:
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "UTC")
    assert lb.append_many(drafts) == len({d["payload"]["raw_id"] for d in drafts})
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)


_iso = st.datetimes(
    min_value=datetime(2005, 1, 1),
    max_value=datetime(2040, 1, 1),
).map(lambda d: d.isoformat(timespec="milliseconds") + "Z")
_i64 = st.integers(
    -(2**63 - 1), 2**63 - 1
)  # ijson's C backend refuses wider integers, as JSON in the wild never has them
_maybe = st.one_of(st.none(), st.floats(allow_nan=False, allow_infinity=False), st.text(max_size=8), _i64)
_e7 = st.one_of(st.integers(-2_000_000_000, 2_000_000_000), _maybe)
_record = st.fixed_dictionaries(
    {},
    optional={
        "latitudeE7": _e7,
        "longitudeE7": _e7,
        "timestamp": st.one_of(_iso, st.text(max_size=12)),
        "timestampMs": st.one_of(st.integers(0, 2_000_000_000_000).map(str), st.text(max_size=6)),
        "accuracy": _maybe,
        "altitude": _maybe,
        "velocity": _maybe,
        "heading": st.one_of(_maybe, st.integers(-10, 400)),
        "source": st.sampled_from(["GPS", "WIFI", "CELL", "UNKNOWN", "other", 3]),
        "deviceTag": st.one_of(_i64, st.text(max_size=4), st.none()),
        "activity": st.lists(st.dictionaries(st.text(max_size=3), _i64, max_size=2), max_size=2),
    },
)


@settings(max_examples=40, deadline=None)
@given(st.lists(_record, max_size=8))
def test_any_records_export_yields_only_valid_lines(tmp_path_factory, records):
    p = tmp_path_factory.mktemp("takeout") / "Records.json"
    p.write_text(json.dumps({"locations": records}, allow_nan=False), encoding="utf-8")
    counts: dict[str, int] = {}
    lines = list(location.run(p, counts=counts))
    for line in lines:
        _rfc_rules(line)
    assert len(lines) + sum(counts.values()) == len(records)
    _validate_through_the_log(tmp_path_factory, lines)


_lat = st.floats(-90, 90, allow_nan=False, allow_infinity=False)
_lon = st.floats(-180, 180, allow_nan=False, allow_infinity=False)
_offset_time = st.datetimes(
    min_value=datetime(2015, 1, 1),
    max_value=datetime(2040, 1, 1),
).map(lambda d: d.isoformat(timespec="milliseconds") + "+01:00")
_latlng = st.one_of(
    st.tuples(_lat, _lon).map(lambda t: f"{t[0]}°, {t[1]}°"),
    st.text(max_size=10),
    st.none(),
)
_geo = st.one_of(
    st.tuples(_lat, _lon).map(lambda t: f"geo:{t[0]},{t[1]}"),
    st.just("geo:nan,1"),
    st.text(max_size=10),
    st.none(),
)
_point = st.fixed_dictionaries(
    {}, optional={"point": _geo, "time": st.one_of(_offset_time, st.text(max_size=5))}
)
_visit = st.fixed_dictionaries(
    {
        "topCandidate": st.fixed_dictionaries(
            {}, optional={"placeLocation": st.fixed_dictionaries({"latLng": _latlng})}
        )
    },
    optional={"probability": st.floats(0, 1)},
)
_activity = st.fixed_dictionaries(
    {},
    optional={
        "start": st.fixed_dictionaries({"latLng": _latlng}),
        "end": st.fixed_dictionaries({"latLng": _latlng}),
        "distanceMeters": st.floats(0, 1e6),
    },
)
_segment = st.fixed_dictionaries(
    {},
    optional={
        "startTime": st.one_of(_offset_time, st.text(max_size=5)),
        "endTime": st.one_of(_offset_time, st.text(max_size=5)),
        "timelinePath": st.lists(_point, max_size=4),
        "visit": _visit,
        "activity": _activity,
        "timelineMemory": st.dictionaries(st.text(max_size=3), _i64, max_size=2),
    },
)


@settings(max_examples=40, deadline=None)
@given(st.lists(_segment, max_size=6))
def test_any_timeline_export_yields_only_valid_lines(tmp_path_factory, segments):
    p = tmp_path_factory.mktemp("takeout") / "Timeline.json"
    p.write_text(json.dumps({"semanticSegments": segments}, allow_nan=False), encoding="utf-8")
    counts: dict[str, int] = {}
    lines = list(location.run(p, counts=counts))
    for line in lines:
        _rfc_rules(line)
    _validate_through_the_log(tmp_path_factory, lines)


# -- streaming ------------------------------------------------------------------


def _truncated_records(tmp_path: Path) -> Path:
    """Records.json cut off inside its third entry: only a streaming reader gets anything out."""
    text = RECORDS.read_text(encoding="utf-8")
    starts = [i for i, line in enumerate(text.splitlines(keepends=True)) if line.startswith("    {")]
    head = "".join(text.splitlines(keepends=True)[: starts[2] + 3])
    p = tmp_path / "truncated.json"
    p.write_text(head, encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(head)
    return p


def test_sniff_reads_only_the_head_of_records(tmp_path):
    assert location.sniff(_truncated_records(tmp_path)) is True


def test_run_yields_records_before_the_end_of_the_file(tmp_path):
    points = location.run(_truncated_records(tmp_path))
    first, second = next(points), next(points)
    assert first["at"] == "2026-03-01T07:30:00Z" and second["at"] == "2026-03-01T08:05:00Z"
    with pytest.raises(location.ijson.JSONError):
        next(points)


# -- CLI -------------------------------------------------------------------------


def _cli(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}

    def run(*a, check=True):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=check,
        )

    return run


def test_cli_add_imports_records_and_reports_skips(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    out = run("add", str(RECORDS)).stdout
    assert "added 6 lines from google-takeout-location" in out
    assert "skipped 1 without a timestamp, 1 with unusable coordinates" in out
    assert "valid — 6 lines" in run("verify").stdout


def test_cli_add_takeout_folder_imports_both_files(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    folder = tmp_path / "Takeout" / "Location History (Timeline)"
    folder.mkdir(parents=True)
    shutil.copy(RECORDS, folder / "Records.json")
    shutil.copy(TIMELINE, folder / "Timeline.json")
    out = run("add", str(folder)).stdout
    assert "added 6 lines from google-takeout-location" in out
    assert "added 7 lines from google-takeout-location" in out
    assert "valid — 13 lines" in run("verify").stdout
    assert "added 0 lines from google-takeout-location" in run("add", str(folder)).stdout


def test_cli_add_dawarich_export_is_not_claimed_by_takeout(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    assert "added 40 lines from dawarich" in run("add", str(DAWARICH)).stdout
