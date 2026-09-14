"""Adapters: the registry, the Dawarich adapter, `logbook add` on an export, and dedupe on re-add."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import dawarich
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "dawarich" / "export.json"
TRACKER = "5d1f8e2a-3b4c-4d5e-8f60-718293a4b5c6"


def _feature(i: int) -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["features"][i]


# -- registry ---------------------------------------------------------------


def test_registry_lists_built_in_dawarich():
    names = [a.NAME for a in adapters.all_adapters()]
    assert "dawarich" in names


def test_registry_find_returns_dawarich_for_its_export():
    found = adapters.find(FIXTURE)
    assert found is not None and found.NAME == "dawarich"


def test_registry_find_returns_none_for_unknown_file(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("just words\n", encoding="utf-8")
    assert adapters.find(p) is None


# -- sniff ------------------------------------------------------------------


def test_sniff_accepts_fixture():
    assert dawarich.sniff(FIXTURE) is True


@pytest.mark.parametrize(
    "content",
    [
        "not json at all",
        '{"type": "FeatureCollection", "features": []}',
        '{"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"timestamp": 1}}]}',
        '[{"when": "2026-01-01T00:00:00Z", "title": "x", "id": "1"}]',
    ],
)
def test_sniff_rejects_other_files(tmp_path, content):
    p = tmp_path / "file.json"
    p.write_text(content, encoding="utf-8")
    assert dawarich.sniff(p) is False


def test_sniff_rejects_directory(tmp_path):
    assert dawarich.sniff(tmp_path) is False


# -- run: envelope ------------------------------------------------------------


def test_run_yields_one_location_line_per_point():
    lines = list(dawarich.run(FIXTURE))
    assert len(lines) == 40
    for line in lines:
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert line["end"] is None and line["tz"] is None
        assert line["source"] == "dawarich" and line["kind"] == "location" and line["tier"] == 1
        assert line["payload"]["schema"] == "location/v1"


def test_run_converts_unix_seconds_to_rfc3339_utc():
    first = next(dawarich.run(FIXTURE))
    assert first["at"] == "2026-04-12T05:00:00Z"


def test_run_since_filters_out_earlier_points():
    lines = list(dawarich.run(FIXTURE, since="2026-04-12T10:00:00Z"))
    assert lines and all(line["at"] >= "2026-04-12T10:00:00Z" for line in lines)
    assert len(lines) == 25  # 07:00 to 20:00 Oslo every 20 min; from 12:00 Oslo


# -- run: payload mapping -----------------------------------------------------


def test_run_maps_geometry_lon_first_to_lat_lon():
    f = _feature(0)
    lon, lat = f["geometry"]["coordinates"]
    p = next(dawarich.run(FIXTURE))["payload"]
    assert p["lat"] == lat and p["lon"] == lon
    assert p["lat"] > 59 and 10 < p["lon"] < 11  # Oslo, not the Indian Ocean


def test_run_maps_numeric_fields_and_ids():
    f = _feature(0)["properties"]
    p = next(dawarich.run(FIXTURE))["payload"]
    assert p["accuracy_m"] == f["accuracy"]
    assert p["alt_m"] == float(f["altitude"])
    assert p["speed_mps"] == float(f["velocity"])
    assert p["heading_deg"] == float(f["course"])
    assert p["tracker"] == TRACKER
    assert p["raw_id"] == f"{TRACKER}:{f['timestamp']}"


def test_run_extra_carries_track_anomaly_vertical_accuracy_and_non_null_device_fields():
    f = _feature(0)["properties"]
    extra = next(dawarich.run(FIXTURE))["payload"]["extra"]
    assert extra["track_id"] == f["track_id"]
    assert extra["anomaly"] is None
    assert extra["vertical_accuracy"] == f["vertical_accuracy"]
    assert extra["battery"] == f["battery"]
    assert extra["ssid"] == f["ssid"]
    assert extra["motion_data"] == f["motion_data"]
    assert "bssid" not in extra  # null in the export → not carried


def test_run_extra_place_is_compact_subset_of_geodata():
    f = _feature(0)["properties"]["geodata"]["properties"]
    place = next(dawarich.run(FIXTURE))["payload"]["extra"]["place"]
    assert place == {
        "type": f["type"],
        "street": f["street"],
        "housenumber": f["housenumber"],
        "district": f["district"],
        "city": f["city"],
        "postcode": f["postcode"],
        "country": f["country"],
        "countrycode": f["countrycode"],
        "osm_type": f["osm_type"],
        "osm_id": f["osm_id"],
    }
    assert "extent" not in place and "osm_key" not in place


def test_run_unknown_velocity_and_course_are_omitted():
    f = _feature(7)["properties"]
    assert f["velocity"] == "-1" and f["course"] == "-1.0"
    p = list(dawarich.run(FIXTURE))[7]["payload"]
    assert "speed_mps" not in p and "heading_deg" not in p


def test_run_anomaly_point_omits_zero_altitude_and_flags_anomaly():
    f = _feature(19)["properties"]
    assert f["anomaly"] is True and f["altitude"] == "0.0"
    p = list(dawarich.run(FIXTURE))[19]["payload"]
    assert "alt_m" not in p
    assert p["extra"]["anomaly"] is True


def test_run_zero_altitude_on_normal_point_is_kept():
    f = _feature(35)["properties"]
    assert f["anomaly"] is None and f["altitude"] == "0.0"
    p = list(dawarich.run(FIXTURE))[35]["payload"]
    assert p["alt_m"] == 0.0


def test_run_point_without_geodata_has_no_place():
    assert _feature(30)["properties"]["geodata"] is None
    p = list(dawarich.run(FIXTURE))[30]["payload"]
    assert "place" not in p["extra"]


def test_run_lines_append_into_a_valid_logbook(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(dawarich.run(FIXTURE)) == 40
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 40
    line = next(lb.lines())
    assert line["tz"] == "Europe/Oslo"  # tz None → the logbook's own


# -- dedupe on (source, raw_id) -------------------------------------------------


def test_append_many_skips_lines_already_present_by_source_and_raw_id(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    draft = {
        "at": "2026-04-12T05:00:00Z",
        "source": "dawarich",
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.9, "lon": 10.7, "raw_id": "abc:1"},
    }
    other_source = {**draft, "source": "owntracks"}
    assert lb.append_many([draft]) == 1
    assert lb.append_many([draft, other_source]) == 1  # same raw_id, different source → new
    assert lb.append_many([draft, draft]) == 0  # duplicates inside one batch too
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 2


def test_append_many_without_raw_id_never_dedupes(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    note = {
        "at": "2026-04-12T05:00:00Z",
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": "same words twice"},
    }
    assert lb.append_many([note, note]) == 2


# -- CLI -------------------------------------------------------------------------


def _cli(tmp_path):
    env = {**os.environ, "LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)}

    def run(*a, check=True):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a], env=env, capture_output=True, text=True, check=check
        )

    return run


def test_cli_add_runs_the_matching_adapter(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    out = run("add", str(FIXTURE)).stdout
    assert "added 40 lines from dawarich" in out
    assert "valid — 40 lines" in run("verify").stdout


def test_cli_re_adding_the_same_export_appends_nothing(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    run("add", str(FIXTURE))
    out = run("add", str(FIXTURE)).stdout
    assert "added 0 lines from dawarich" in out
    assert "valid — 40 lines" in run("verify").stdout


def test_cli_add_directory_processes_every_file(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    inbox = tmp_path / "drop"
    inbox.mkdir()
    shutil.copy(FIXTURE, inbox / "a.json")
    # a second export with different raw ids: shift the tracker id
    doc = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for f in doc["features"][:5]:
        f["properties"]["tracker_id"] = "00000000-0000-4000-8000-000000000002"
    (inbox / "b.json").write_text(
        json.dumps(doc["features"][:5] and {**doc, "features": doc["features"][:5]})
    )
    out = run("add", str(inbox)).stdout
    assert "added 40 lines from dawarich" in out
    assert "added 5 lines from dawarich" in out
    assert "valid — 45 lines" in run("verify").stdout


def test_cli_add_unknown_file_still_exits_2(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "UTC")
    p = tmp_path / "mystery.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    r = run("add", str(p), check=False)
    assert r.returncode == 2 and "no adapter" in r.stdout
