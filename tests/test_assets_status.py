"""`logbook assets status`: per registered asset (ADR 0018), the last known position from its own
location/v1 lines (RFC 0001, `subject`), found through the index, and the age of that fix. Every
identifier here is synthetic: MMSIs in the 970xxxxxx test range, registrations under `ZZ`."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import asset_status, assets, cli, places
from logbook.assets import Asset
from logbook.store import Logbook

NORDLYS = Asset(id="nordlys", kind="yacht", name="Nordlys", mmsi="970000001", registration="ZZ-LOG1")
SKARV = Asset(id="skarv", kind="yacht", name="Skarv", mmsi="970000002")
MARINA = places.Place("Marina", 59.9050, 10.7250, 150.0, kind=places.BERTH)
NOW = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assets.add(lb.root, NORDLYS)
    assets.add(lb.root, SKARV)
    places.add(lb.root, MARINA)
    return lb


def _fix(lb: Logbook, subject: str | None, at: str, lat: float, lon: float, **more: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"schema": "location/v1", "lat": lat, "lon": lon, "tracker": "aisstream"}
    if subject is not None:
        payload["subject"] = subject
        payload["raw_id"] = f"aisstream:970000001:{at}"
    payload.update(more)
    return lb.append(at=at, source="ais", kind="location", tier=1, payload=payload)


# -- the reader --------------------------------------------------------------------------------


def test_the_last_fix_is_the_latest_by_time_not_by_order_of_writing(lb):
    _fix(lb, "nordlys", "2026-06-15T10:00:00Z", 59.9000, 10.7300)
    _fix(lb, "nordlys", "2026-06-15T09:00:00Z", 59.8000, 10.6000)  # written later, happened earlier
    (status,) = asset_status.read(lb, [NORDLYS], [], NOW)
    assert status.asset == NORDLYS
    assert status.fix is not None
    assert status.fix.at == "2026-06-15T10:00:00Z"
    assert (status.fix.lat, status.fix.lon) == (59.9000, 10.7300)
    assert status.fix.age_s == 2 * 3600


def test_an_asset_never_seen_has_no_fix(lb):
    _fix(lb, "nordlys", "2026-06-15T10:00:00Z", 59.9000, 10.7300)
    _fix(lb, None, "2026-06-15T11:00:00Z", 59.9139, 10.7522)  # the owner's own position is not an asset's
    nordlys, skarv = asset_status.read(lb, [NORDLYS, SKARV], [], NOW)
    assert nordlys.fix is not None
    assert skarv.fix is None


def test_a_retracted_fix_does_not_count(lb):
    _fix(lb, "nordlys", "2026-06-15T09:00:00Z", 59.8000, 10.6000)
    wrong = _fix(lb, "nordlys", "2026-06-15T10:00:00Z", 0.0, 0.0)
    lb.retract(int(wrong["seq"]), "bad fix")
    (status,) = asset_status.read(lb, [NORDLYS], [], NOW)
    assert status.fix is not None
    assert status.fix.at == "2026-06-15T09:00:00Z"


def test_the_nearest_named_place_within_five_km_is_named_with_its_distance(lb):
    _fix(lb, "nordlys", "2026-06-15T10:00:00Z", 59.9080, 10.7300)  # some 400 m from the Marina
    _fix(lb, "skarv", "2026-06-15T10:00:00Z", 59.0000, 10.0000)  # nowhere near it
    nordlys, skarv = asset_status.read(lb, [NORDLYS, SKARV], places.read(lb.root), NOW)
    assert nordlys.fix is not None and nordlys.fix.near is not None
    assert nordlys.fix.near[0] == "Marina" and 300 < nordlys.fix.near[1] < 600
    assert skarv.fix is not None and skarv.fix.near is None


def test_speed_is_carried_when_the_line_has_it(lb):
    _fix(lb, "nordlys", "2026-06-15T10:00:00Z", 59.9080, 10.7300, speed_mps=3.1)
    _fix(lb, "skarv", "2026-06-15T10:00:00Z", 59.0000, 10.0000)
    nordlys, skarv = asset_status.read(lb, [NORDLYS, SKARV], [], NOW)
    assert nordlys.fix is not None and nordlys.fix.speed_mps == 3.1
    assert skarv.fix is not None and skarv.fix.speed_mps is None


def test_the_fix_is_found_through_the_index_not_a_sweep_of_the_files(lb, monkeypatch):
    _fix(lb, "nordlys", "2026-06-15T10:00:00Z", 59.9080, 10.7300)
    assert not (lb.root / "index.sqlite").exists()
    (status,) = asset_status.read(lb, [NORDLYS], [], NOW)  # builds the index once
    assert status.fix is not None and (lb.root / "index.sqlite").exists()
    monkeypatch.setattr(Logbook, "located_lines", _never)
    (status,) = asset_status.read(lb, [NORDLYS], [], NOW)  # the index is current: no file is swept
    assert status.fix is not None


def _never(self: Logbook) -> None:
    raise AssertionError("the files were swept although the index is current")


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (20, "just now"),
        (90, "1 min ago"),
        (3600 * 2 + 60 * 15, "2 h 15 min ago"),
        (86400 * 3 + 3600 * 4, "3 days 4 h ago"),
        (86400, "1 day ago"),
    ],
)
def test_the_age_of_a_fix_reads_as_people_say_it(seconds, text):
    assert asset_status.age_text(seconds) == text


# -- the command -------------------------------------------------------------------------------


def test_assets_status_prints_one_line_per_asset_with_the_fix_or_no_fix_yet(lb, capsys):
    _fix(lb, "nordlys", "2026-06-15T10:00:00Z", 59.9080, 10.7300, speed_mps=3.1)
    cli.main(["assets", "status"])
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("nordlys")
    assert "2026-06-15 12:00" in lines[0]  # local time, Europe/Oslo
    assert "59.9080,10.7300" in lines[0] and re.search(r"near Marina, 4\d\d m", lines[0])
    assert "3.1 m/s" in lines[0] and "ago" in lines[0]
    assert lines[1].startswith("skarv") and "no fix yet" in lines[1]


def test_assets_status_json_carries_the_fix_and_null_for_none(lb, capsys):
    _fix(lb, "nordlys", "2026-06-15T10:00:00Z", 59.9080, 10.7300)
    cli.main(["assets", "status", "--json"])
    out = json.loads(capsys.readouterr().out)
    nordlys, skarv = out["assets"]
    assert nordlys["id"] == "nordlys" and nordlys["fix"]["at"] == "2026-06-15T10:00:00Z"
    assert nordlys["fix"]["lat"] == 59.908 and nordlys["fix"]["near"]["name"] == "Marina"
    assert 300 < nordlys["fix"]["near"]["m"] < 600
    assert nordlys["fix"]["age_s"] > 0 and nordlys["fix"]["speed_mps"] is None
    assert skarv["id"] == "skarv" and skarv["fix"] is None


def test_assets_status_with_nothing_registered_says_how_to_add_one(lb, capsys):
    assets.write(lb.root, [])
    cli.main(["assets", "status"])
    out = capsys.readouterr().out
    assert "no assets" in out and "logbook assets add" in out
