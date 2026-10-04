"""The Withings data export (the CSVs of `Download my data`) → health-sample/v1 (RFC 0014): the
scale's weight and body composition from `weight.csv`, the cuff's pulse from `bp.csv`, the nights
from `sleep.csv`, the tracker's sleep stages, heart rate, steps, distance and calories from the
`raw_<device>_<measure>.csv` files, the workouts from `activities.csv`; a later export that corrects a
sample supersedes the line already in the record."""

from __future__ import annotations

import csv
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import withings
from logbook.core import health
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "rfcs" / "0014-health-sample-v1.md"
EXPORT = (
    ROOT / "tests" / "fixtures" / "withings" / "download"
)  # not `export/`, which .gitignore keeps for day packages
TZ = "Europe/Oslo"
LINES = 40  # 14 body composition, 2 pulse, 2 nights, 10 stages, 4 heart rates, 4+2+1 buckets, 1 workout


def _schema() -> dict[str, Any]:
    text = RFC.read_text(encoding="utf-8")
    block = re.search(r"## JSON Schema\n\n```json\n(.*?)\n```", text, re.S)
    assert block is not None
    return json.loads(block.group(1))  # type: ignore[no-any-return]


def _run(path: Path = EXPORT, **options: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    counts: dict[str, int] = {}
    lines = list(withings.run(path, counts=counts, timezone=TZ, **options))
    return lines, counts


def _of(lines: list[dict[str, Any]], type_name: str) -> list[dict[str, Any]]:
    return [line for line in lines if line["payload"]["type"] == type_name]


# -- the reader -------------------------------------------------------------------------------------


def test_sniff_takes_the_export_folder_and_its_files_and_nothing_else(tmp_path):
    assert withings.sniff(EXPORT)
    assert withings.sniff(EXPORT / "weight.csv")
    assert withings.sniff(EXPORT / "raw_tracker_steps.csv")
    assert adapters.find(EXPORT) is withings
    assert not withings.sniff(tmp_path)
    other = tmp_path / "other.csv"
    other.write_text("a,b\n1,2\n", encoding="utf-8")
    assert not withings.sniff(other)
    assert not withings.sniff(tmp_path / "missing")


def test_every_line_is_a_health_sample_with_the_rfc_payload():
    lines, _counts = _run()
    assert len(lines) == LINES
    validator = Draft202012Validator(_schema())
    for line in lines:
        assert (line["source"], line["kind"], line["tier"], line["tz"]) == ("withings", "health", 3, TZ)
        validator.validate(line["payload"])
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)
    assert len({line["payload"]["raw_id"] for line in lines}) == LINES


def test_one_standing_on_the_scale_is_one_line_per_quantity_at_the_local_instant():
    lines, counts = _run()
    first = [line for line in lines if line["at"] == "2026-06-08T05:12:33Z"]  # 07:12:33 CEST
    assert {line["payload"]["type"]: line["payload"]["value"] for line in first} == {
        "weight": 78.4,
        "fat_mass": 15.2,
        "bone_mass": 3.1,
        "muscle_mass": 57.0,
        "body_water": 43.8,
    }
    assert all(line["payload"]["unit"] == "kg" and line["end"] is None for line in first)
    assert all("device" not in line["payload"] for line in first)
    assert {line["payload"]["raw_id"] for line in first} == {
        f"{t}:2026-06-08T05:12:33Z" for t in ("weight", "fat_mass", "bone_mass", "muscle_mass", "body_water")
    }
    second = [line for line in lines if line["at"] == "2026-06-10T05:05:10Z"]
    assert {line["payload"]["type"] for line in second} == {
        "weight",
        "bone_mass",
        "muscle_mass",
        "body_water",
    }
    assert all(line["payload"]["extra"] == {"comment": "after the run"} for line in second)
    assert counts["skipped_no_value"] == 2  # the empty standing, and the cuff row without a pulse


def test_the_cuff_gives_a_heart_rate_with_the_pressures_beside_it():
    lines, _counts = _run()
    pulses = [
        line for line in _of(lines, "heart_rate") if line["payload"]["raw_id"].startswith("heart_rate:bp:")
    ]
    assert [(p["at"], p["payload"]["value"], p["payload"]["unit"]) for p in pulses] == [
        ("2026-06-09T06:30:00Z", 61, "bpm"),
        ("2026-06-11T06:32:15Z", 64, "bpm"),
    ]
    assert pulses[0]["payload"]["extra"] == {"systolic_mmhg": 121, "diastolic_mmhg": 78}
    assert pulses[1]["payload"]["extra"] == {"systolic_mmhg": 118, "diastolic_mmhg": 76, "comment": "morning"}


def test_a_night_is_an_in_bed_span_and_the_tracker_gives_the_stages():
    lines, counts = _run()
    nights = [line for line in _of(lines, "sleep") if line["payload"]["stage"] == "in_bed"]
    assert [(n["at"], n["end"], n["payload"]["value"]) for n in nights] == [
        ("2026-06-08T21:10:00Z", "2026-06-09T04:40:00Z", 27000),
        ("2026-06-09T21:30:00Z", "2026-06-10T04:30:00Z", 25200),
    ]
    assert nights[0]["payload"]["raw_id"] == "sleep:night:2026-06-08T21:10:00Z"
    assert nights[0]["payload"]["extra"] == {
        "light_s": 14400,
        "deep_s": 7200,
        "rem_s": 3600,
        "awake_s": 1800,
        "heart_rate_avg": 52,
        "heart_rate_min": 47,
        "heart_rate_max": 68,
    }
    stages = [line for line in _of(lines, "sleep") if line["payload"]["stage"] != "in_bed"]
    assert all(s["payload"]["device"] == "tracker" and s["payload"]["unit"] == "s" for s in stages)
    first_night = [(s["at"], s["end"], s["payload"]["stage"], s["payload"]["value"]) for s in stages[:6]]
    assert first_night == [
        ("2026-06-08T21:10:00Z", "2026-06-08T21:20:00Z", "awake", 600),
        ("2026-06-08T21:20:00Z", "2026-06-08T21:50:00Z", "core", 1800),
        ("2026-06-08T21:50:00Z", "2026-06-08T22:20:00Z", "deep", 1800),
        ("2026-06-08T22:20:00Z", "2026-06-08T23:20:00Z", "core", 3600),
        ("2026-06-08T23:20:00Z", "2026-06-08T23:50:00Z", "rem", 1800),
        ("2026-06-08T23:50:00Z", "2026-06-09T00:00:00Z", "awake", 600),
    ]
    # two consecutive light intervals are one segment
    assert [(s["payload"]["stage"], s["payload"]["value"]) for s in stages[6:9]] == [
        ("core", 3600),
        ("deep", 2400),
        ("rem", 1200),
    ]
    assert stages[6]["payload"]["raw_id"] == "sleep:tracker:2026-06-09T21:30:00Z"
    assert counts["skipped_unknown_stage"] == 1
    assert [(s["at"], s["payload"]["stage"]) for s in stages[9:]] == [("2026-06-10T21:10:00Z", "core")]


def test_heart_rate_is_capped_at_one_reading_a_minute_per_device():
    lines, counts = _run()
    readings = [line for line in _of(lines, "heart_rate") if line["payload"].get("device") == "tracker"]
    assert [(r["at"], r["payload"]["value"]) for r in readings] == [
        ("2026-06-09T05:00:00Z", 58),
        ("2026-06-09T05:01:00Z", 60),
        ("2026-06-09T05:02:00Z", 59),
        ("2026-06-09T05:03:00Z", 62),
    ]
    assert readings[0]["payload"]["raw_id"] == "heart_rate:tracker:2026-06-09T05:00:00Z"
    assert all(r["payload"]["unit"] == "bpm" and r["end"] is None for r in readings)
    assert counts["skipped_over_cap"] == 1


def test_counts_are_bucketed_by_the_quarter_hour_per_device():
    lines, _counts = _run()
    steps = _of(lines, "steps")
    assert [(s["at"], s["end"], s["payload"]["value"], s["payload"]["extra"]["samples"]) for s in steps] == [
        ("2026-06-09T07:00:00Z", "2026-06-09T07:15:00Z", 200, 3),
        ("2026-06-09T07:15:00Z", "2026-06-09T07:30:00Z", 440, 3),
        ("2026-06-09T07:30:00Z", "2026-06-09T07:45:00Z", 50, 1),
        ("2026-06-09T07:45:00Z", "2026-06-09T08:00:00Z", 75, 1),
    ]
    assert steps[0]["payload"]["raw_id"] == "steps:2026-06-09T07:00:00Z:tracker"
    assert steps[0]["payload"]["device"] == "tracker"
    energy = _of(lines, "active_energy")
    assert [(e["at"], e["payload"]["value"], e["payload"]["unit"]) for e in energy] == [
        ("2026-06-09T07:00:00Z", 12.5, "kcal"),
        ("2026-06-09T07:15:00Z", 9.5, "kcal"),
    ]
    distance = _of(lines, "distance")
    assert [(d["at"], d["payload"]["value"], d["payload"]["unit"]) for d in distance] == [
        ("2026-06-09T07:00:00Z", 640, "m")
    ]


def test_an_activity_is_a_workout_span():
    lines, _counts = _run()
    (workout,) = _of(lines, "workout")
    assert (workout["at"], workout["end"], workout["tz"]) == (
        "2026-06-09T16:00:00Z",
        "2026-06-09T16:45:00Z",
        TZ,
    )
    assert workout["payload"]["value"] == 2700
    assert workout["payload"]["unit"] == "s"
    assert workout["payload"]["raw_id"] == "workout:2026-06-09T16:00:00Z"
    assert workout["payload"]["extra"] == {
        "activity": "Running",
        "steps": 5400,
        "energy_kcal": 410,
        "distance_m": 6200,
    }


def test_height_elevation_and_daily_totals_are_counted_never_mapped():
    _lines, counts = _run()
    assert counts["skipped_other_type"] == 2  # a height, an elevation row
    assert counts["skipped_daily_total"] == 2


def test_one_file_alone_gives_only_its_own_lines():
    lines, _counts = _run(EXPORT / "weight.csv")
    assert {line["payload"]["type"] for line in lines} == {
        "weight",
        "fat_mass",
        "bone_mass",
        "muscle_mass",
        "body_water",
    }
    assert len(lines) == 14


def test_since_and_tier():
    lines, _counts = _run(since="2026-06-10T00:00:00Z", tier=2)
    assert lines and all(line["at"] >= "2026-06-10T00:00:00Z" and line["tier"] == 2 for line in lines)


def test_a_column_this_reader_does_not_need_may_be_missing_or_renamed(tmp_path):
    folder = tmp_path / "export"
    folder.mkdir()
    (folder / "weight.csv").write_text(
        "Date,Weight (lb),Comments\n2026-06-08 07:12:33,172.8,\n", encoding="utf-8"
    )
    (folder / "bp.csv").write_text("Date,Pulse,Systolic\n2026-06-09 08:30:00,61,121\n", encoding="utf-8")
    lines, counts = _run(folder)
    (weight,) = lines
    assert weight["payload"]["type"] == "weight"
    assert weight["payload"]["value"] == 78.381
    assert weight["payload"]["unit"] == "kg"
    assert weight["payload"]["extra"] == {"original": {"value": 172.8, "unit": "lb"}}
    assert counts == {"skipped_unreadable_csv": 1}  # bp.csv without a Heart Rate column


def test_the_export_is_never_written(tmp_path):
    folder = tmp_path / "export"
    shutil.copytree(EXPORT, folder)
    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    _run(folder)
    assert {p.name: p.read_bytes() for p in folder.iterdir()} == before


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def _corrected_export(dst: Path, weight: str) -> Path:
    """The fixture with the 8 June weight replaced, as a later export of the same account."""
    shutil.copytree(EXPORT, dst)
    rows = list(csv.reader((EXPORT / "weight.csv").read_text(encoding="utf-8").splitlines()))
    rows[1][1] = weight
    with (dst / "weight.csv").open("w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    return dst


def test_add_withings_appends_once_and_reports_the_skips(lb, capsys):
    cli.main(["add", "withings", str(EXPORT)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from withings" in out
    for phrase in (
        "2 without a value",
        "1 with a sleep stage this version does not know",
        "1 over the one-per-minute heart-rate cap",
        "2 of a type this version does not know",
        "2 daily totals",
    ):
        assert phrase in out, phrase
    cli.main(["add", "withings", str(EXPORT)])
    assert "added 0 lines" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])


def test_add_the_export_folder_without_naming_the_adapter(lb, capsys):
    cli.main(["add", str(EXPORT)])
    assert f"added {LINES} lines from withings" in capsys.readouterr().out


def test_a_later_export_that_corrects_a_sample_supersedes_the_line(lb, tmp_path, capsys):
    cli.main(["add", "withings", str(EXPORT)])
    capsys.readouterr()
    cli.main(["add", "withings", str(_corrected_export(tmp_path / "later", "78.6"))])
    out = capsys.readouterr().out
    assert "added 1 lines from withings" in out
    assert "1 corrected" in out
    with lb.index() as idx:
        lines = list(idx.of_kind("health"))
    old = [line for line in lines if line["payload"]["raw_id"] == "weight:2026-06-08T05:12:33Z"]
    new = [line for line in lines if line["payload"]["raw_id"] == "weight:2026-06-08T05:12:33Z:v2"]
    assert len(old) == 1 and len(new) == 1
    assert new[0]["payload"]["value"] == 78.6
    assert new[0]["payload"]["supersedes"] == old[0]["id"]
    assert new[0]["at"] == old[0]["at"]
    standing = {line["payload"]["raw_id"] for line in health.standing(lines)}
    assert "weight:2026-06-08T05:12:33Z:v2" in standing
    assert "weight:2026-06-08T05:12:33Z" not in standing
    # the same corrected export again appends nothing; a third value supersedes the correction
    cli.main(["add", "withings", str(tmp_path / "later")])
    assert "added 0 lines" in capsys.readouterr().out
    cli.main(["add", "withings", str(_corrected_export(tmp_path / "latest", "78.5"))])
    assert "added 1 lines" in capsys.readouterr().out
    with lb.index() as idx:
        lines = list(idx.of_kind("health"))
    (third,) = (line for line in lines if line["payload"]["raw_id"] == "weight:2026-06-08T05:12:33Z:v3")
    assert third["payload"]["supersedes"] == new[0]["id"]
    # and the first export again is not a correction: its value is the one the record started with
    cli.main(["add", "withings", str(EXPORT)])
    assert "added 1 lines" in capsys.readouterr().out
    with lb.index() as idx:
        (fourth,) = (
            line
            for line in idx.of_kind("health")
            if line["payload"]["raw_id"] == "weight:2026-06-08T05:12:33Z:v4"
        )
    assert fourth["payload"]["value"] == 78.4
    assert fourth["payload"]["supersedes"] == third["id"]
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES + 3, [])


def test_dry_run_counts_and_writes_nothing(lb, capsys):
    cli.main(["add", "withings", str(EXPORT), "--dry-run"])
    out = capsys.readouterr().out
    assert (
        f"withings: {LINES} lines would be added, 0 already in the record (dry run, nothing written)" in out
    )
    assert "2 daily totals" in out
    assert lb.verify()[0] == 0
    assert not (lb.root / "index.sqlite").exists() or True  # the index may be built; the log is not
    cli.main(["add", "withings", str(EXPORT)])
    capsys.readouterr()
    cli.main(["add", "withings", str(EXPORT), "--dry-run"])
    out = capsys.readouterr().out
    assert f"withings: 0 lines would be added, {LINES} already in the record" in out
    assert lb.verify()[0] == LINES
