"""EasyPark's recent parkings → trip/v1 (RFC 0020, mode `parking`): one line per recently used area,
`at` the app's last-used time, no end. Synthetic areas in Oslo; nobody parked anywhere."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters
from logbook.adapters import easypark
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
LINES = 3
APPLE = 978307200  # 2001-01-01T00:00:00Z as Unix seconds


def _recent(folder: Path) -> Path:
    """`recentparkings_<user>.json` as the app writes it, plus the find-my-car pin it keeps beside it."""
    folder.mkdir(parents=True, exist_ok=True)
    areas = [
        {
            "id": 114681,
            "signageAreaCode": "8291",
            "lastModified": 1789567508.550897 - APPLE,  # 2026-09-16T14:05:08Z
            "areaNumber": 8291,
            "latitude": "59.9139",
            "operatorName": "Oslo kommune",
            "areaDescription": "Storgata 1-36",
            "areaType": "OnStreet",
            "longitude": "10.7522",
            "cluster": "",
        },
        {
            "id": 114245,
            "signageAreaCode": "4296",
            "lastModified": 1789100000.0 - APPLE,  # 2026-09-11T04:13:20Z
            "areaNumber": 4296,
            "latitude": 59.9271,
            "operatorName": "Oslo kommune",
            "areaDescription": "Parkeringshus",
            "areaType": "SurfaceLot",
            "longitude": 10.7461,
            "cluster": "",
        },
        {
            "id": 1,
            "signageAreaCode": "0001",
            "lastModified": 0,  # never used: a placeholder
            "areaNumber": 1,
            "latitude": "0",
            "longitude": "0",
        },
        {
            "id": 2,
            "signageAreaCode": "0002",
            "lastModified": 1788000000.0 - APPLE,
            "areaNumber": 2,
            "latitude": "not a number",
            "longitude": "10.7",
            "areaDescription": "Broken",
        },
        {
            "id": 3,
            "signageAreaCode": "0003",
            "lastModified": 1786000000.0 - APPLE,  # 2026-08-06T07:06:40Z
            "areaNumber": 3,
            "areaDescription": "No coordinates at all",
        },
    ]
    (folder / "recentparkings_12345.json").write_text(json.dumps(areas), encoding="utf-8")
    (folder / "findmycar-pin_12345.json").write_text(
        json.dumps([{"id": 1, "latitude": 59.91, "longitude": 10.75}]), encoding="utf-8"
    )
    return folder


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    return _recent(tmp_path / "easypark")


def _drafts(path: Path, **options) -> tuple[list[dict], dict[str, int]]:
    counts: dict[str, int] = {}
    drafts = list(easypark.run(path, counts=counts, timezone="Europe/Oslo", **options))
    return drafts, counts


def test_registry_has_easypark():
    assert adapters.named("easypark") is easypark


def test_sniff_recognises_the_file_and_the_folder_holding_it(folder, tmp_path):
    assert easypark.sniff(folder)
    assert easypark.sniff(folder / "recentparkings_12345.json")
    assert not easypark.sniff(folder / "findmycar-pin_12345.json")
    assert not easypark.sniff(tmp_path / "missing.json")
    other = tmp_path / "recentparkings_1.json"
    other.write_text("[1, 2]", encoding="utf-8")
    assert not easypark.sniff(other)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not easypark.sniff(empty)


def test_each_recent_area_is_one_parking_trip_with_no_end(folder):
    drafts, counts = _drafts(folder)
    assert len(drafts) == LINES
    d = drafts[0]
    assert d["at"] == "2026-08-06T07:06:40Z" and drafts[-1]["at"] == "2026-09-16T14:05:08Z"  # oldest first
    d = drafts[-1]
    assert (d["end"], d["tz"], d["source"], d["kind"], d["tier"]) == (
        None,
        "Europe/Oslo",
        "easypark",
        "trip",
        1,
    )
    p = d["payload"]
    assert p["schema"] == "trip/v1" and p["mode"] == "parking" and p["provider"] == "easypark"
    assert p["raw_id"] == "easypark:114681@2026-09-16T14:05:08Z"
    assert p["from"] == {
        "name": "Storgata 1-36",
        "code": "8291",
        "operator": "Oslo kommune",
        "latitude": 59.9139,
        "longitude": 10.7522,
    }
    assert "to" not in p
    assert p["extra"] == {"area_type": "OnStreet", "observed": "last_used", "area_number": 8291}
    no_coordinates = drafts[0]["payload"]["from"]
    assert no_coordinates == {"name": "No coordinates at all", "code": "0003"}
    assert counts == {"skipped_no_timestamp": 1, "skipped_bad_coordinates": 1}


def test_since_and_a_folder_with_no_file(folder, tmp_path):
    drafts, _ = _drafts(folder, since="2026-09-12T00:00:00Z")
    assert [d["payload"]["raw_id"] for d in drafts] == ["easypark:114681@2026-09-16T14:05:08Z"]
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _drafts(empty) == ([], {})


def test_lines_append_validate_and_dedupe(folder, tmp_path, monkeypatch):
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    assert lb.append_many(_drafts(folder)[0]) == LINES
    assert lb.append_many(_drafts(folder)[0]) == 0
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])
