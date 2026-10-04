"""Google Takeout Fit/ → health-sample/v1 (RFC 0014): the streams under All Data/ as buckets, readings
and sleep stages, the sessions as workouts, the daily CSVs as the fallback for days no stream touched."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.store import Logbook

from logbook import adapters, cli, health
from logbook.adapters.takeout import fit

ROOT = Path(__file__).resolve().parents[1]
TAKEOUT = ROOT / "tests" / "fixtures" / "takeout"
FIX = TAKEOUT / "Fit"
DATA = FIX / "All Data"
SESSIONS = FIX / "All Sessions"
DAILY = FIX / "Daily activity metrics"
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
TZ = "Europe/Oslo"
LINES = 27
OBSERVATION = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))


def _profile() -> dict:
    """RFC 0014's own JSON schema, read from the RFC so the test follows the profile."""
    text = (ROOT / "rfcs" / "0014-health-sample-v1.md").read_text(encoding="utf-8")
    block = re.search(r"```json\n(\{\"\$schema\".*?)\n```", text, re.DOTALL)
    assert block is not None
    return json.loads(block.group(1))


PROFILE = _profile()


def _lines(path=FIX, **kw):
    return list(fit.run(path, timezone=TZ, **kw))


def _by_id(lines):
    return {line["payload"]["raw_id"]: line for line in lines}


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_has_fit_as_a_file_adapter_and_the_folder_is_its():
    assert adapters.named("google-takeout-fit") is fit
    assert adapters.named("takeout-fit") is fit
    assert isinstance(fit, adapters.Adapter)
    assert adapters.find(FIX) is fit
    for folder in (DATA, SESSIONS, DAILY):
        assert adapters.find(folder) is fit
    assert adapters.find(DATA / "derived_com.google.step_count.delta_com.google.and.json") is fit
    assert adapters.find(SESSIONS / "2026-06-08T06_40_12+02_00_WALKING.json") is fit
    assert adapters.find(DAILY / "Daily activity metrics.csv") is fit
    assert adapters.find(DAILY / "2026-06-12.csv") is fit


def test_sniff_recognises_fit_and_its_files_and_nothing_else(tmp_path):
    assert fit.sniff(FIX) and fit.sniff(DATA) and fit.sniff(SESSIONS) and fit.sniff(DAILY)
    assert not fit.sniff(TAKEOUT)  # the archive's root is walked, not claimed
    assert not fit.sniff(FIX / "Activities")
    assert not fit.sniff(FIX / "Activities" / "2026-06-08T06_40_12+02_00_WALKING.tcx")
    assert not fit.sniff(TAKEOUT / "Tasks" / "Tasks.json")
    assert not fit.sniff(TAKEOUT / "Home App")
    assert not fit.sniff(TAKEOUT / "Google Pay" / "Google transactions" / "transactions_123456789012.csv")
    assert not fit.sniff(TAKEOUT / "Google Meet" / "Call history" / "Call history.csv")
    assert not fit.sniff(tmp_path) and not fit.sniff(tmp_path / "missing.json")
    (tmp_path / "x.json").write_text("[1, 2]", encoding="utf-8")
    assert not fit.sniff(tmp_path / "x.json")
    (tmp_path / "x.csv").write_text("Date,Meal,Calories\n2026-06-08,Breakfast,400\n", encoding="utf-8")
    assert not fit.sniff(tmp_path / "x.csv")
    (tmp_path / "empty.csv").write_text("", encoding="utf-8")
    assert not fit.sniff(tmp_path / "empty.csv")


# -- every line ------------------------------------------------------------------------------------


def test_every_line_is_a_valid_tier_3_health_sample_and_the_rest_is_counted():
    counts: dict[str, int] = {}
    lines = _lines(counts=counts)
    assert len(lines) == LINES
    validator = Draft202012Validator(PROFILE)
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["kind"] == "health" and line["source"] == "google-takeout" and line["tier"] == 3
        assert line["tz"] == TZ
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", line["at"])
        assert line["end"] is None or line["end"] >= line["at"]
        p = line["payload"]
        validator.validate(p)
        assert p["unit"] == fit.UNITS[p["type"]]
        assert ("stage" in p) == (p["type"] == "sleep")
        if p["type"] in fit.BUCKETED:
            assert line["end"] is not None
        if p["type"] in ("heart_rate", "weight", "body_fat_pct"):
            assert line["end"] is None
    assert counts == {
        "skipped_covered_by_merge": 1,
        "skipped_no_date": 1,
        "skipped_no_value": 4,
        "skipped_over_cap": 1,
        "skipped_unknown_stage": 1,
        "skipped_other_type": 1,
        "skipped_bad_span": 1,
        "skipped_covered_by_stream": 2,
    }
    assert len({line["payload"]["raw_id"] for line in lines}) == LINES


def test_the_lines_never_carry_a_coordinate_or_a_device_uid():
    text = json.dumps(_lines())
    assert "latitude" not in text and "longitude" not in text and "59.9" not in text
    assert "7f3a2b1c" not in text and "0a1b2c3d" not in text and "9e8d7c6b" not in text


# -- the streams -----------------------------------------------------------------------------------


def test_steps_and_distance_are_summed_into_quarter_hours_per_device():
    by = _by_id(_lines(DATA))
    phone = by["steps:2026-06-08T04:30:00Z:Google Pixel 8"]
    assert phone["at"] == "2026-06-08T04:30:00Z" and phone["end"] == "2026-06-08T04:45:00Z"
    assert phone["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": "steps:2026-06-08T04:30:00Z:Google Pixel 8",
        "type": "steps",
        "value": 250,
        "unit": "count",
        "device": "Google Pixel 8",
        "source_name": "com.google.android.gms",
        "extra": {"samples": 2},
    }
    assert by["steps:2026-06-08T04:30:00Z:Fossil Gen 6"]["payload"]["value"] == 90
    assert by["steps:2026-06-08T04:30:00Z:Fossil Gen 6"]["payload"]["source_name"] == (
        "com.google.android.wearable.app"
    )
    assert by["steps:2026-06-08T04:45:00Z:Google Pixel 8"]["payload"]["value"] == 200
    assert by["steps:2026-06-08T04:45:00Z:Fossil Gen 6"]["payload"]["value"] == 110
    assert by["steps:2026-06-09T10:00:00Z:Google Pixel 8"]["payload"]["value"] == 300
    distance = by["distance:2026-06-08T04:30:00Z:Google Pixel 8"]["payload"]
    assert distance["value"] == 177.75 and distance["unit"] == "m" and distance["extra"] == {"samples": 2}
    assert by["distance:2026-06-08T04:45:00Z:Google Pixel 8"]["payload"]["value"] == 140
    starts = [line["at"] for line in _lines(DATA) if line["payload"]["type"] == "steps"]
    assert starts == sorted(starts)


def test_heart_rate_keeps_its_resolution_capped_at_one_reading_a_minute():
    readings = [line for line in _lines(DATA) if line["payload"]["type"] == "heart_rate"]
    assert [(line["at"], line["payload"]["value"]) for line in readings] == [
        ("2026-06-08T04:40:05Z", 62),
        ("2026-06-08T04:41:10Z", 70),
        ("2026-06-08T04:46:00Z", 118),
    ]
    first = readings[0]
    assert first["end"] is None
    assert first["payload"]["raw_id"] == "heart_rate:1780893605000000000:Fossil Gen 6"
    assert first["payload"]["device"] == "Fossil Gen 6" and first["payload"]["unit"] == "bpm"


def test_a_weight_and_a_body_fat_reading_name_the_scale():
    by = _by_id(_lines(DATA))
    weight = by["weight:1780894920000000000:Withings Body+"]
    assert weight["at"] == "2026-06-08T05:02:00Z" and weight["end"] is None
    assert weight["payload"]["value"] == 81.4 and weight["payload"]["unit"] == "kg"
    assert weight["payload"]["device"] == "Withings Body+"
    assert weight["payload"]["source_name"] == "com.google.android.apps.fitness"
    fat = by["body_fat_pct:1780894920000000000:Withings Body+"]["payload"]
    assert fat["value"] == 21.5 and fat["unit"] == "%"


def test_sleep_segments_are_spans_with_fit_stages_mapped_to_the_profile():
    stages = [line for line in _lines(DATA) if line["payload"]["type"] == "sleep"]
    assert [
        (line["at"], line["end"], line["payload"]["stage"], line["payload"]["value"]) for line in stages
    ] == [
        ("2026-06-07T21:30:00Z", "2026-06-07T22:00:00Z", "awake", 1800),
        ("2026-06-07T22:00:00Z", "2026-06-07T23:30:00Z", "core", 5400),
        ("2026-06-07T23:30:00Z", "2026-06-08T00:30:00Z", "deep", 3600),
        ("2026-06-08T00:30:00Z", "2026-06-08T01:00:00Z", "rem", 1800),
        ("2026-06-08T01:10:00Z", "2026-06-08T04:30:00Z", "core", 12000),
    ]
    assert stages[0]["payload"]["raw_id"] == "sleep:1780867800000000000:Fossil Gen 6"
    assert all(line["payload"]["device"] == "Fossil Gen 6" for line in stages)


def test_a_stream_without_a_header_or_an_origin_still_reads_and_an_unknown_type_is_counted(tmp_path):
    folder = tmp_path / "All Data"
    folder.mkdir()
    (folder / "raw_com.google.step_count.delta_com.example.json").write_text(
        json.dumps(
            {
                "Data Points": [
                    {
                        "fitValue": [{"value": {"intVal": 40}}],
                        "dataTypeName": "com.google.step_count.delta",
                        "startTimeNanos": "1780893600000000000",
                        "endTimeNanos": "1780893660000000000",
                    },
                    {
                        "fitValue": [{"value": {"fpVal": 1.5}}],
                        "dataTypeName": "com.google.height",
                        "startTimeNanos": 1780893600000000000,
                        "endTimeNanos": 1780893600000000000,
                    },
                    {
                        "fitValue": [{"value": {"intVal": 5}}],
                        "dataTypeName": "com.google.step_count.delta",
                        "startTimeNanos": -5,
                        "endTimeNanos": 0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    assert fit.sniff(folder)
    lines = list(fit.run(folder, counts=counts))
    assert len(lines) == 1
    assert lines[0]["tz"] is None
    assert lines[0]["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": "steps:2026-06-08T04:30:00Z:-",
        "type": "steps",
        "value": 40,
        "unit": "count",
        "extra": {"samples": 1},
    }
    assert counts == {"skipped_other_type": 1, "skipped_no_date": 1}


# -- the sessions ----------------------------------------------------------------------------------


def test_a_session_is_a_workout_span_with_its_aggregates_under_extra():
    by = _by_id(_lines(SESSIONS))
    walk = by["workout:2026-06-08T04:40:12Z:walking"]
    assert walk["at"] == "2026-06-08T04:40:12Z" and walk["end"] == "2026-06-08T05:12:45Z"
    assert walk["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": "workout:2026-06-08T04:40:12Z:walking",
        "type": "workout",
        "value": 1953,
        "unit": "s",
        "source_name": "com.google.android.apps.fitness",
        "extra": {
            "activity": "walking",
            "activity_type": "walking",
            "steps": 2345,
            "distance_m": 1820.4,
            "energy_kcal": 123.4,
            "heart_points": 20,
            "move_minutes": 30,
        },
    }
    ride = by["workout:sess-0002"]
    assert ride["payload"]["value"] == 2730  # no duration in the file: the span
    assert ride["payload"]["extra"]["activity"] == "cycling"
    assert ride["payload"]["extra"]["activity_type"] == "biking"
    assert ride["payload"]["extra"]["name"] == "Evening ride"
    assert (
        ride["payload"]["extra"]["distance_m"] == 12840 and ride["payload"]["extra"]["energy_kcal"] == 410.5
    )


def test_a_sleep_session_is_the_night_in_bed():
    by = _by_id(_lines(SESSIONS))
    night = by["sleep:session:2026-06-07T21:15:00Z"]
    assert night["at"] == "2026-06-07T21:15:00Z" and night["end"] == "2026-06-08T04:35:00Z"
    assert night["payload"]["type"] == "sleep" and night["payload"]["stage"] == "in_bed"
    assert night["payload"]["value"] == 26400 and night["payload"]["unit"] == "s"
    assert night["payload"]["source_name"] == "com.google.android.wearable.app"
    assert "extra" not in night["payload"]


# -- the daily CSVs --------------------------------------------------------------------------------


def test_a_day_no_stream_touched_is_one_span_per_type_with_the_days_figures_under_extra():
    counts: dict[str, int] = {}
    by = _by_id(_lines(counts=counts))
    steps = by["steps:day:2026-06-10"]
    assert steps["at"] == "2026-06-09T22:00:00Z" and steps["end"] == "2026-06-10T22:00:00Z"
    assert steps["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": "steps:day:2026-06-10",
        "type": "steps",
        "value": 1840,
        "unit": "count",
        "extra": {
            "period": "day",
            "day": "2026-06-10",
            "calories_kcal": 1702.6,
            "heart_points": 4,
            "move_minutes": 12,
            "heart_rate_avg_bpm": 64.5,
            "heart_rate_max_bpm": 96,
            "heart_rate_min_bpm": 50,
        },
    }
    distance = by["distance:day:2026-06-10"]
    assert distance["payload"]["value"] == 1210.5 and distance["payload"]["unit"] == "m"
    assert distance["payload"]["extra"] == {"period": "day", "day": "2026-06-10"}
    # the 9th: the stream has its steps, not its distance
    assert "steps:day:2026-06-09" not in by and "distance:day:2026-06-09" in by
    # the 8th and the 12th are covered; the 11th has neither steps nor distance
    assert "steps:day:2026-06-08" not in by and "distance:day:2026-06-08" not in by
    assert "steps:day:2026-06-12" not in by and "steps:day:2026-06-11" not in by
    assert counts["skipped_covered_by_stream"] == 2


def test_a_days_quarter_hour_windows_are_buckets_like_a_stream():
    counts: dict[str, int] = {}
    by = _by_id(list(fit.run(DAILY / "2026-06-12.csv", timezone=TZ, counts=counts)))
    assert set(by) == {
        "steps:2026-06-12T04:00:00Z:-",
        "steps:2026-06-12T04:15:00Z:-",
        "distance:2026-06-12T04:00:00Z:-",
        "distance:2026-06-12T04:15:00Z:-",
    }
    first = by["steps:2026-06-12T04:00:00Z:-"]
    assert first["at"] == "2026-06-12T04:00:00Z" and first["end"] == "2026-06-12T04:15:00Z"
    assert first["payload"]["value"] == 410 and first["payload"]["extra"] == {"samples": 1}
    assert "device" not in first["payload"] and "source_name" not in first["payload"]
    assert by["distance:2026-06-12T04:15:00Z:-"]["payload"]["value"] == 620.5
    assert counts == {"skipped_no_value": 1}


def test_the_daily_folder_alone_falls_back_to_days_for_every_day_but_the_windowed_one():
    by = _by_id(_lines(DAILY))
    days = sorted(k for k in by if ":day:" in k)
    assert days == [
        "distance:day:2026-06-08",
        "distance:day:2026-06-09",
        "distance:day:2026-06-10",
        "steps:day:2026-06-08",
        "steps:day:2026-06-09",
        "steps:day:2026-06-10",
    ]
    assert len(by) == 10


def test_a_csv_without_the_columns_is_counted_not_a_traceback(tmp_path):
    folder = tmp_path / "Daily activity metrics"
    folder.mkdir()
    (folder / "Daily activity metrics.csv").write_text("Date,Step count\n2026-06-08,100\n", encoding="utf-8")
    (folder / "odd.csv").write_text("Something,Else\n1,2\n", encoding="utf-8")
    (folder / "bad.csv").write_bytes(b"\xff\xfe\x00\x00Date,Step count\n")
    counts: dict[str, int] = {}
    lines = list(fit.run(folder, timezone=TZ, counts=counts))
    assert [line["payload"]["raw_id"] for line in lines] == ["steps:day:2026-06-08"]
    assert counts["skipped_unreadable_csv"] == 2


# -- options ---------------------------------------------------------------------------------------


def test_since_cuts_on_at_and_tier_overrides():
    later = _lines(since="2026-06-09T00:00:00Z")
    assert later and all(line["at"] >= "2026-06-09T00:00:00Z" for line in later)
    assert len(later) < LINES
    assert {line["tier"] for line in _lines(tier=2)} == {2}


def test_without_a_timezone_the_lines_carry_none_and_a_day_is_read_in_utc():
    by = _by_id(list(fit.run(FIX)))
    assert {line["tz"] for line in by.values()} == {None}
    assert by["steps:day:2026-06-10"]["at"] == "2026-06-10T00:00:00Z"


# -- the record ------------------------------------------------------------------------------------


def test_lines_append_once_and_the_health_summary_reads_them(tmp_path):
    lb = Logbook.init(tmp_path / "lb", TZ)
    assert lb.append_many(fit.run(FIX, timezone=TZ)) == LINES
    assert lb.append_many(fit.run(FIX, timezone=TZ)) == 0
    _seq, _head, errors = lb.verify()
    assert errors == []
    validator = Draft202012Validator(OBSERVATION)
    lines = list(lb.lines())
    for line in lines:
        validator.validate(line)
    rows = {row["day"]: row for row in health.summary(lines, TZ)}
    assert rows["2026-06-08"]["steps"] == 450  # the larger device per quarter hour, never a sum across
    assert rows["2026-06-09"]["steps"] == 300
    assert rows["2026-06-10"]["steps"] == 1840  # the day-span fallback
    assert rows["2026-06-12"]["steps"] == 1230
    assert rows["2026-06-08"]["sleep_h"] == 6.3  # the stages' union, never the night in bed


def test_cli_add_hands_the_whole_folder_to_the_adapter_and_a_re_add_appends_nothing(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", str(FIX)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from google-takeout-fit" in out
    assert "1 raw stream files whose points the merged stream carries" in out
    assert "2 daily rows for days the quarter-hour streams already cover" in out
    assert "1 over the one-per-minute heart-rate cap" in out
    assert "1 with a sleep stage this version does not know" in out
    assert "Fit: read 1 folder — Fit; 1 file with no adapter" in out  # the TCX under Activities/
    cli.main(["add", str(FIX)])
    assert "added 0 lines from google-takeout-fit" in capsys.readouterr().out


def test_cli_add_by_name_takes_one_file(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("LOGBOOK_HOME", str(tmp_path / "lb"))
    cli.main(["init", str(tmp_path / "lb"), "--timezone", TZ])
    capsys.readouterr()
    cli.main(["add", "takeout-fit", str(SESSIONS / "2026-06-09T18_05_00+02_00_BIKING.json"), "--dry-run"])
    out = capsys.readouterr().out
    assert "1" in out and "google-takeout-fit" in out


@pytest.mark.parametrize("name", ["All Data", "All Sessions", "Daily activity metrics"])
def test_each_family_reads_on_its_own(name):
    assert _lines(FIX / name)
