"""Apple Health's healthdb_secure.sqlite → health-sample/v1 (RFC 0014): buckets, readings, sleep
stages and workouts, and the daily summary `logbook stats --health` derives from them."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import adapters, cli
from logbook.adapters import apple_health, ios_calls
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
APPLE_EPOCH = 978_307_200  # 2001-01-01T00:00:00Z

# Apple's own layout, as far as the adapter reads it: dates are seconds since 2001-01-01 UTC.
DDL = """
CREATE TABLE samples (data_id INTEGER PRIMARY KEY, start_date REAL, end_date REAL, data_type INTEGER);
CREATE TABLE quantity_samples (
    data_id INTEGER PRIMARY KEY, quantity REAL, original_quantity REAL, original_unit INTEGER);
CREATE TABLE category_samples (data_id INTEGER PRIMARY KEY, value INTEGER);
CREATE TABLE workouts (
    data_id INTEGER PRIMARY KEY, activity_type INTEGER, duration REAL, total_energy_burned REAL,
    total_distance REAL, goal_type INTEGER, goal REAL);
CREATE TABLE objects (
    data_id INTEGER PRIMARY KEY, uuid BLOB, provenance INTEGER, type INTEGER, creation_date REAL);
CREATE TABLE data_provenances (
    ROWID INTEGER PRIMARY KEY, sync_provenance INTEGER, origin_product_type TEXT, origin_build TEXT,
    local_product_type TEXT, local_build TEXT, source_id INTEGER, device_id INTEGER, contributor_id INTEGER,
    source_version TEXT, tz_name TEXT);
CREATE TABLE unit_strings (ROWID INTEGER PRIMARY KEY, unit_string TEXT);
"""
COMPANION_DDL = """
CREATE TABLE sources (
    ROWID INTEGER PRIMARY KEY, uuid BLOB, bundle_id TEXT, name TEXT, source_options INTEGER,
    local_device INTEGER, product_type TEXT, deleted INTEGER, mod_date REAL, provenance TEXT,
    sync_anchor INTEGER);
"""

WATCH, PHONE, BARE = 1, 2, 3  # provenance rows: an Apple Watch, an iPhone, one that names nothing
PROVENANCES = [
    (WATCH, 0, "Watch7,1", "22S89", "iPhone14,2", "23C71", 2, 1, 0, "11.2", "Europe/Oslo"),
    (PHONE, 0, "iPhone14,2", "23C71", "iPhone14,2", "23C71", 1, 2, 0, "19.2", "Europe/Oslo"),
    (BARE, 0, None, None, None, None, None, None, 0, None, ""),
]
SOURCES = [
    (1, None, "com.apple.Health", "iPhone", 0, 1, "iPhone14,2", 0, 0.0, None, 0),
    (2, None, "com.apple.health.Watch", "Apple Watch", 0, 1, "Watch7,1", 0, 0.0, None, 0),
]
UNITS = [(1, "kg"), (2, "count/min")]

HEART_RATE, STEPS, DISTANCE, BASAL, ACTIVE, FLIGHTS, SLEEP, WEIGHT = 5, 7, 8, 9, 10, 12, 63, 3
RESTING, HRV, WORKOUT_TYPE = 118, 183, 79


def _apple(stamp: str) -> float:
    return float(
        int(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()) - APPLE_EPOCH
    )


def q(
    data_id: int,
    kind: int,
    start: object,
    end: object,
    quantity: object,
    prov: int | None = WATCH,
    **original: Any,
) -> dict[str, Any]:
    """A quantity sample: `quantity` in Apple's canonical unit (count, m, kcal, count/s, kg, s)."""
    return {
        "id": data_id,
        "type": kind,
        "start": start,
        "end": end,
        "quantity": quantity,
        "prov": prov,
        **original,
    }


def c(data_id: int, start: str, end: str, value: int, prov: int = WATCH) -> dict[str, Any]:
    """A category sample (sleep analysis: 0 in bed, 1 asleep, 2 awake, 3 core, 4 deep, 5 REM)."""
    return {
        "id": data_id,
        "type": SLEEP,
        "start": _apple(start),
        "end": _apple(end),
        "value": value,
        "prov": prov,
    }


def w(
    data_id: int, start: str, end: str, activity: int, duration: float, energy: float, distance: float
) -> dict[str, Any]:
    return {
        "id": data_id,
        "type": WORKOUT_TYPE,
        "start": _apple(start),
        "end": _apple(end),
        "prov": WATCH,
        "workout": (activity, duration, energy, distance),
    }


# The synthetic Oslo persona's two days. Nobody in it exists. Oslo is UTC+1 in March.
ROWS: list[dict[str, Any]] = [
    # steps: three watch samples in the 07:00Z quarter, one in the next, one from the phone
    q(1, STEPS, _apple("2026-03-02T07:00:10Z"), _apple("2026-03-02T07:05:00Z"), 120),
    q(2, STEPS, _apple("2026-03-02T07:05:00Z"), _apple("2026-03-02T07:10:00Z"), 80),
    q(3, STEPS, _apple("2026-03-02T07:12:00Z"), _apple("2026-03-02T07:14:00Z"), 50),
    q(4, STEPS, _apple("2026-03-02T07:20:00Z"), _apple("2026-03-02T07:25:00Z"), 300),
    q(5, STEPS, _apple("2026-03-02T07:02:00Z"), _apple("2026-03-02T07:04:00Z"), 200, PHONE),
    q(6, DISTANCE, _apple("2026-03-02T07:00:10Z"), _apple("2026-03-02T07:05:00Z"), 150.5),
    q(7, ACTIVE, _apple("2026-03-02T07:00:00Z"), _apple("2026-03-02T07:01:00Z"), 12.5),
    q(8, ACTIVE, _apple("2026-03-02T07:10:00Z"), _apple("2026-03-02T07:11:00Z"), 8.0),
    q(9, BASAL, _apple("2026-03-02T07:00:00Z"), _apple("2026-03-02T07:15:00Z"), 30.0),
    q(10, FLIGHTS, _apple("2026-03-02T07:03:00Z"), _apple("2026-03-02T07:03:30Z"), 2),
    # heart rate in count/s: 72, then one 35 s later (capped), then 66; the phone's own 75
    q(
        11,
        HEART_RATE,
        _apple("2026-03-02T07:00:05Z"),
        _apple("2026-03-02T07:00:05Z"),
        1.2,
        original_quantity=72,
        original_unit=2,
    ),
    q(12, HEART_RATE, _apple("2026-03-02T07:00:40Z"), _apple("2026-03-02T07:00:40Z"), 1.3),
    q(13, HEART_RATE, _apple("2026-03-02T07:01:00Z"), _apple("2026-03-02T07:01:00Z"), 1.1),
    q(14, HEART_RATE, _apple("2026-03-02T07:00:20Z"), _apple("2026-03-02T07:00:20Z"), 1.25, PHONE),
    q(15, RESTING, _apple("2026-03-02T05:00:00Z"), _apple("2026-03-02T05:00:00Z"), 0.9333333),
    q(16, HRV, _apple("2026-03-02T07:30:00Z"), _apple("2026-03-02T07:30:00Z"), 0.045),
    q(
        17,
        WEIGHT,
        _apple("2026-03-02T06:30:00Z"),
        _apple("2026-03-02T06:30:00Z"),
        78.4,
        PHONE,
        original_quantity=78.4,
        original_unit=1,
    ),
    # the night of 1-2 March as the watch staged it, and as the phone saw it (in bed)
    c(18, "2026-03-01T22:30:00Z", "2026-03-02T00:30:00Z", 3),
    c(19, "2026-03-02T00:30:00Z", "2026-03-02T01:30:00Z", 4),
    c(20, "2026-03-02T01:30:00Z", "2026-03-02T02:00:00Z", 5),
    c(21, "2026-03-02T02:00:00Z", "2026-03-02T02:10:00Z", 2),
    c(22, "2026-03-02T02:10:00Z", "2026-03-02T06:00:00Z", 3),
    c(23, "2026-03-01T22:20:00Z", "2026-03-02T06:10:00Z", 0, PHONE),
    c(24, "2026-03-02T06:00:00Z", "2026-03-02T06:05:00Z", 9),  # a stage this version does not know
    w(25, "2026-03-02T16:00:00Z", "2026-03-02T16:35:00Z", 37, 2100.0, 350.5, 5200.0),
    # the next day: the watch and the phone both count the 10:00Z quarter
    q(26, STEPS, _apple("2026-03-03T10:00:00Z"), _apple("2026-03-03T10:05:00Z"), 400),
    q(27, RESTING, _apple("2026-03-03T05:00:00Z"), _apple("2026-03-03T05:00:00Z"), 1.0),
    q(28, STEPS, _apple("2026-03-03T10:01:00Z"), _apple("2026-03-03T10:03:00Z"), 450, PHONE),
    # what is skipped and counted
    q(29, 999, _apple("2026-03-03T11:00:00Z"), _apple("2026-03-03T11:00:00Z"), 1.0),
    q(30, STEPS, -13_000_000_000.0, -13_000_000_000.0, 10),
    q(31, STEPS, _apple("2026-03-03T12:00:00Z"), _apple("2026-03-03T12:05:00Z"), None),
    q(32, HEART_RATE, None, None, 1.0),
    # a reading whose provenance names no device and no zone
    q(33, HEART_RATE, _apple("2026-03-03T12:00:00Z"), _apple("2026-03-03T12:00:00Z"), 1.0, BARE),
]
LINES = 24
SKIPS = {
    "skipped_over_cap": 1,
    "skipped_unknown_stage": 1,
    "skipped_other_type": 1,
    "skipped_placeholder_date": 1,
    "skipped_no_value": 1,
    "skipped_no_date": 1,
}


def _store(
    folder: Path,
    rows: list[dict[str, Any]] = ROWS,
    *,
    companion: bool = True,
    name: str = "healthdb_secure.sqlite",
) -> Path:
    """A synthetic healthdb_secure.sqlite (and, beside it, the healthdb.sqlite that names the sources)."""
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    with closing(sqlite3.connect(p)) as con:
        con.executescript(DDL)
        con.executemany("INSERT INTO data_provenances VALUES (?,?,?,?,?,?,?,?,?,?,?)", PROVENANCES)
        con.executemany("INSERT INTO unit_strings VALUES (?,?)", UNITS)
        for r in rows:
            con.execute("INSERT INTO samples VALUES (?,?,?,?)", (r["id"], r["start"], r["end"], r["type"]))
            if r.get("prov") is not None:
                con.execute(
                    "INSERT INTO objects VALUES (?,?,?,?,?)", (r["id"], None, r["prov"], 1, r["start"])
                )
            if "quantity" in r and r["quantity"] is not None:
                con.execute(
                    "INSERT INTO quantity_samples VALUES (?,?,?,?)",
                    (r["id"], r["quantity"], r.get("original_quantity"), r.get("original_unit")),
                )
            if "value" in r:
                con.execute("INSERT INTO category_samples VALUES (?,?)", (r["id"], r["value"]))
            if "workout" in r:
                con.execute(
                    "INSERT INTO workouts VALUES (?,?,?,?,?,?,?)", (r["id"], *r["workout"], None, None)
                )
        con.commit()
    if companion:
        with closing(sqlite3.connect(folder / "healthdb.sqlite")) as con:
            con.executescript(COMPANION_DDL)
            con.executemany("INSERT INTO sources VALUES (?,?,?,?,?,?,?,?,?,?,?)", SOURCES)
            con.commit()
    return p


def _lines(tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(apple_health.run(_store(tmp_path / "health"), **kw))


def _by_raw_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_lists_apple_health():
    assert any(a.NAME == "apple-health" for a in adapters.file_adapters())


def test_registry_named_resolves_the_name_and_its_short_form():
    assert adapters.named("apple-health") is apple_health
    assert adapters.named("health") is apple_health
    assert adapters.named("calls") is ios_calls  # the same rule the backup importer uses


def test_registry_find_returns_apple_health_for_the_store(tmp_path):
    assert adapters.find(_store(tmp_path)) is apple_health


def test_sniff_accepts_the_store_under_any_name(tmp_path):
    assert apple_health.sniff(_store(tmp_path, name="whatever.db"))


def test_sniff_rejects_other_sqlite_files(tmp_path):
    p = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(p)) as con:
        con.execute("CREATE TABLE samples (data_id INTEGER)")  # samples alone is not Health
        con.commit()
    assert not apple_health.sniff(p)
    assert not apple_health.sniff(tmp_path / "healthdb.sqlite")  # the companion is not the store


def test_sniff_rejects_non_sqlite_and_missing(tmp_path):
    p = tmp_path / "healthdb_secure.sqlite"
    p.write_text("not a database", encoding="utf-8")
    assert not apple_health.sniff(p)
    assert not apple_health.sniff(tmp_path / "missing.sqlite")
    assert not apple_health.sniff(tmp_path)


def test_other_adapters_reject_the_store(tmp_path):
    p = _store(tmp_path)
    for a in adapters.file_adapters():
        if a is not apple_health:
            assert not a.sniff(p), a.NAME


def test_sniff_and_run_never_touch_the_source(tmp_path):
    p = _store(tmp_path)
    before = {f.name: f.read_bytes() for f in tmp_path.iterdir()}
    apple_health.sniff(p)
    list(apple_health.run(p))
    assert {f.name: f.read_bytes() for f in tmp_path.iterdir()} == before


# -- the mapping -----------------------------------------------------------------------------------


def test_run_yields_health_lines(tmp_path):
    lines = _lines(tmp_path)
    assert len(lines) == LINES
    for line in lines:
        assert set(line) == ENVELOPE
        assert line["source"] == "apple-health" and line["kind"] == "health" and line["tier"] == 3
        assert line["payload"]["schema"] == "health-sample/v1"


def test_run_tier_is_3_by_default_and_tier_overrides_it(tmp_path):
    p = _store(tmp_path / "health")
    assert {line["tier"] for line in apple_health.run(p)} == {3}
    assert {line["tier"] for line in apple_health.run(p, tier=2)} == {2}
    assert {line["tier"] for line in apple_health.run(p, tier=None)} == {3}


def test_run_counts_what_it_skipped(tmp_path):
    counts: dict[str, int] = {}
    _lines(tmp_path, counts=counts)
    assert counts == SKIPS


def test_run_steps_are_summed_into_quarter_hours_per_device(tmp_path):
    lines = _by_raw_id(_lines(tmp_path))
    watch = lines["steps:2026-03-02T07:00:00Z:Watch7,1"]
    assert watch["at"] == "2026-03-02T07:00:00Z" and watch["end"] == "2026-03-02T07:15:00Z"
    assert watch["payload"]["type"] == "steps" and watch["payload"]["unit"] == "count"
    assert watch["payload"]["value"] == 250 and watch["payload"]["extra"]["samples"] == 3
    assert watch["payload"]["device"] == "Watch7,1" and watch["payload"]["source_name"] == "Apple Watch"
    assert lines["steps:2026-03-02T07:15:00Z:Watch7,1"]["payload"]["value"] == 300
    phone = lines["steps:2026-03-02T07:00:00Z:iPhone14,2"]
    assert phone["payload"]["value"] == 200 and phone["payload"]["source_name"] == "iPhone"


def test_run_buckets_the_other_high_frequency_types(tmp_path):
    lines = _by_raw_id(_lines(tmp_path))
    assert lines["distance:2026-03-02T07:00:00Z:Watch7,1"]["payload"]["value"] == 150.5
    assert lines["distance:2026-03-02T07:00:00Z:Watch7,1"]["payload"]["unit"] == "m"
    assert lines["active_energy:2026-03-02T07:00:00Z:Watch7,1"]["payload"]["value"] == 20.5
    assert lines["active_energy:2026-03-02T07:00:00Z:Watch7,1"]["payload"]["unit"] == "kcal"
    assert lines["basal_energy:2026-03-02T07:00:00Z:Watch7,1"]["payload"]["value"] == 30
    assert lines["flights_climbed:2026-03-02T07:00:00Z:Watch7,1"]["payload"]["value"] == 2


def test_run_heart_rate_is_bpm_at_native_resolution_capped_per_minute(tmp_path):
    lines = _by_raw_id(_lines(tmp_path))
    first = lines["heart_rate:11"]
    assert first["at"] == "2026-03-02T07:00:05Z" and first["end"] is None
    assert first["payload"]["value"] == 72 and first["payload"]["unit"] == "bpm"
    assert first["payload"]["extra"]["original"] == {"quantity": 72, "unit": "count/min"}
    assert "heart_rate:12" not in lines  # 35 s after the first, same device: capped
    assert lines["heart_rate:13"]["payload"]["value"] == 66
    assert lines["heart_rate:14"]["payload"]["value"] == 75  # the phone's own reading in the same minute


def test_run_resting_hr_hrv_and_weight(tmp_path):
    lines = _by_raw_id(_lines(tmp_path))
    assert (
        lines["resting_hr:15"]["payload"]["value"] == 56
        and lines["resting_hr:15"]["payload"]["unit"] == "bpm"
    )
    assert lines["hrv:16"]["payload"]["value"] == 45 and lines["hrv:16"]["payload"]["unit"] == "ms"
    weight = lines["weight:17"]["payload"]
    assert weight["value"] == 78.4 and weight["unit"] == "kg" and weight["device"] == "iPhone14,2"
    assert weight["extra"]["original"] == {"quantity": 78.4, "unit": "kg"}


def test_run_sleep_stages_are_spans(tmp_path):
    lines = _by_raw_id(_lines(tmp_path))
    deep = lines["sleep:19"]
    assert deep["at"] == "2026-03-02T00:30:00Z" and deep["end"] == "2026-03-02T01:30:00Z"
    assert deep["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": "sleep:19",
        "type": "sleep",
        "value": 3600,
        "unit": "s",
        "stage": "deep",
        "device": "Watch7,1",
        "source_name": "Apple Watch",
    }
    assert {lines[f"sleep:{n}"]["payload"]["stage"] for n in (18, 20, 21, 22)} == {"core", "rem", "awake"}
    assert (
        lines["sleep:23"]["payload"]["stage"] == "in_bed" and lines["sleep:23"]["payload"]["value"] == 28200
    )
    assert "sleep:24" not in lines


def test_run_workout_is_a_span_with_its_totals(tmp_path):
    line = _by_raw_id(_lines(tmp_path))["workout:25"]
    assert line["at"] == "2026-03-02T16:00:00Z" and line["end"] == "2026-03-02T16:35:00Z"
    p = line["payload"]
    assert p["type"] == "workout" and p["value"] == 2100 and p["unit"] == "s"
    assert p["extra"] == {
        "activity": "running",
        "activity_type": 37,
        "energy_kcal": 350.5,
        "distance_m": 5200,
    }


def test_run_tz_is_the_provenance_zone_else_the_records(tmp_path):
    lines = _by_raw_id(_lines(tmp_path))
    assert lines["weight:17"]["tz"] == "Europe/Oslo"
    bare = lines["heart_rate:33"]
    assert bare["tz"] is None and "device" not in bare["payload"] and "source_name" not in bare["payload"]


def test_run_without_the_companion_has_no_source_names(tmp_path):
    lines = _by_raw_id(apple_health.run(_store(tmp_path, companion=False)))
    p = lines["steps:2026-03-02T07:00:00Z:Watch7,1"]["payload"]
    assert p["device"] == "Watch7,1" and "source_name" not in p


def test_run_honours_since(tmp_path):
    lines = _lines(tmp_path, since="2026-03-03T00:00:00Z")
    assert all(line["at"] >= "2026-03-03T00:00:00Z" for line in lines)
    assert len(lines) == 4


def test_run_with_the_minimal_tables_only(tmp_path):
    p = tmp_path / "healthdb_secure.sqlite"
    with closing(sqlite3.connect(p)) as con:
        con.execute(
            "CREATE TABLE samples"
            " (data_id INTEGER PRIMARY KEY, start_date REAL, end_date REAL, data_type INTEGER)"
        )
        con.execute("CREATE TABLE quantity_samples (data_id INTEGER PRIMARY KEY, quantity REAL)")
        con.execute(
            "INSERT INTO samples VALUES (1, ?, ?, 7)",
            (_apple("2026-03-02T07:00:10Z"), _apple("2026-03-02T07:05:00Z")),
        )
        con.execute("INSERT INTO quantity_samples VALUES (1, 120)")
        con.commit()
    assert apple_health.sniff(p)
    [line] = apple_health.run(p)
    assert line["payload"]["raw_id"] == "steps:2026-03-02T07:00:00Z:-" and line["payload"]["value"] == 120
    assert "device" not in line["payload"] and line["tz"] is None


def test_run_lines_append_and_re_running_appends_nothing(tmp_path):
    p = _store(tmp_path / "health")
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append_many(apple_health.run(p)) == LINES
    assert lb.append_many(apple_health.run(p)) == 0
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == LINES
    validator = Draft202012Validator(SCHEMA)
    for line in lb.lines():
        validator.validate(line)
        assert line["tz"] == "Europe/Oslo"


# -- the CLI ---------------------------------------------------------------------------------------


def _cli(tmp_path):
    env = dict(os.environ)
    env.update({"LOGBOOK_HOME": str(tmp_path / "lb"), "PYTHONPATH": str(ROOT)})

    def run(*a):
        return subprocess.run(
            [sys.executable, "-m", "logbook.cli", *a],
            env=env,
            capture_output=True,
            encoding="utf-8",
            check=True,
        )

    return run


def test_cli_add_health_by_name_reports_lines_and_skips(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _store(tmp_path / "health")
    out = run("add", "health", str(p)).stdout
    assert f"added {LINES} lines from apple-health" in out
    assert "skipped " in out and "1 over the one-per-minute heart-rate cap" in out
    assert "1 with a sleep stage this version does not know" in out
    assert "1 of a type this version does not know" in out
    assert "1 with a placeholder start (before 1900)" in out and "1 without a value" in out
    assert "1 without a date" in out
    assert "added 0 lines from apple-health" in run("add", "apple-health", str(p)).stdout
    assert f"valid — {LINES} lines" in run("verify").stdout


def test_cli_add_tier_overrides_the_default(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    run("add", "health", str(_store(tmp_path / "health")), "--tier", "2")
    lb = Logbook(tmp_path / "lb")
    assert {line["tier"] for line in lb.lines()} == {2}


def test_cli_add_by_sniff_writes_the_same_lines(tmp_path):
    run = _cli(tmp_path)
    run("init", str(tmp_path / "lb"), "--timezone", "Europe/Oslo")
    p = _store(tmp_path / "health")
    assert f"added {LINES} lines from apple-health" in run("add", str(p)).stdout
    assert "added 0 lines from apple-health" in run("add", "health", str(p)).stdout


# -- `stats --health` ------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(apple_health.run(_store(tmp_path / "health")))
    return lb


def _stats(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["stats", *args])
    return capsys.readouterr().out


def test_stats_health_json_one_row_per_day(lb: Logbook, capsys):
    data = json.loads(_stats(capsys, "--health", "--json"))
    assert data["days"] == [
        {"day": "2026-03-02", "sleep_h": 7.3, "steps": 550, "resting_hr": 56},
        {"day": "2026-03-03", "sleep_h": None, "steps": 450, "resting_hr": 60},
    ]


def test_stats_health_prints_the_table(lb: Logbook, capsys):
    out = _stats(capsys, "--health")
    rows = [line.split() for line in out.splitlines() if line.startswith("  20")]
    assert rows == [["2026-03-02", "7.3", "550", "56"], ["2026-03-03", "-", "450", "60"]]
    assert "day" in out and "sleep" in out and "steps" in out and "resting" in out
    assert "Watch" not in out and "Oslo" not in out


def test_stats_health_sleep_is_the_night_that_ends_on_the_day_asleep_stages_only(lb: Logbook, capsys):
    # 2h core + 1h deep + 30m rem + 3h50 core = 7h20; awake and the phone's in-bed span do not count
    data = json.loads(_stats(capsys, "--health", "--json"))
    assert data["days"][0]["sleep_h"] == 7.3


def test_stats_health_steps_take_the_larger_device_per_quarter_hour(lb: Logbook, capsys):
    # 07:00Z: watch 250 vs phone 200 → 250; 07:15Z: watch 300 → 550. Next day: watch 400 vs phone 450 → 450
    data = json.loads(_stats(capsys, "--health", "--json"))
    assert [d["steps"] for d in data["days"]] == [550, 450]


def test_stats_health_ignores_retracted_lines(lb: Logbook, capsys):
    with lb.index() as idx:
        (line,) = (ln for ln in idx.day("2026-03-03") if ln["payload"].get("raw_id") == "resting_hr:27")
    lb.retract(int(line["seq"]), "sensor fault")
    data = json.loads(_stats(capsys, "--health", "--json"))
    assert data["days"][1]["resting_hr"] is None


def test_stats_health_on_a_record_without_health_lines(tmp_path: Path, monkeypatch, capsys):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert json.loads(_stats(capsys, "--health", "--json")) == {"days": []}
    assert "no health lines" in _stats(capsys, "--health")


# -- property: every emitted line is a valid health-sample/v1 observation ----------------------------

PROFILE = {
    "type": "object",
    "required": ["schema", "raw_id", "type", "value", "unit"],
    "properties": {
        "schema": {"const": "health-sample/v1"},
        "raw_id": {"type": "string", "minLength": 1},
        "type": {"enum": list(apple_health.UNITS)},
        "value": {"type": "number"},
        "unit": {"enum": ["count", "m", "kcal", "bpm", "ms", "kg", "s"]},
        "stage": {"enum": ["in_bed", "asleep", "awake", "core", "deep", "rem"]},
        "device": {"type": "string", "minLength": 1},
        "source_name": {"type": "string", "minLength": 1},
        "extra": {"type": "object"},
    },
    "additionalProperties": False,
}


def _rfc_rules(line: dict[str, Any]) -> None:
    assert set(line) == ENVELOPE
    assert line["kind"] == "health" and line["tier"] == 3 and line["source"] == "apple-health"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", line["at"])
    assert line["end"] is None or line["end"] >= line["at"]
    assert datetime.strptime(line["at"], "%Y-%m-%dT%H:%M:%SZ").year >= 1900
    p = line["payload"]
    Draft202012Validator(PROFILE).validate(p)
    assert p["unit"] == apple_health.UNITS[p["type"]]
    assert ("stage" in p) == (p["type"] == "sleep")
    assert p["value"] == p["value"] and p["value"] not in (float("inf"), float("-inf"))
    if p["type"] in apple_health.BUCKETED:
        assert line["end"] is not None and p["raw_id"].startswith(f"{p['type']}:{line['at']}:")
    if p["type"] in ("heart_rate", "resting_hr", "hrv", "weight"):
        assert line["end"] is None


def test_fixture_lines_follow_the_rfc(tmp_path):
    for line in _lines(tmp_path):
        _rfc_rules(line)


_date = st.one_of(
    st.none(),
    st.floats(min_value=-13_000_000_000, max_value=3_000_000_000, allow_nan=False, allow_infinity=False),
)
_quantity = st.one_of(
    st.none(), st.floats(min_value=-10, max_value=1_000_000, allow_nan=False, allow_infinity=False)
)
_type = st.sampled_from(
    [HEART_RATE, STEPS, DISTANCE, BASAL, ACTIVE, FLIGHTS, SLEEP, WEIGHT, RESTING, HRV, 999]
)
_prov = st.sampled_from([WATCH, PHONE, BARE, None])
_stage = st.integers(min_value=-1, max_value=7)


@settings(max_examples=60, deadline=None)
@given(rows=st.lists(st.tuples(_type, _date, _date, _quantity, _prov, _stage), min_size=1, max_size=8))
def test_every_line_from_any_row_follows_the_rfc(tmp_path_factory, rows):
    tmp_path = tmp_path_factory.mktemp("health")
    fixture = []
    for n, (kind, start, end, quantity, prov, stage) in enumerate(rows):
        r: dict[str, Any] = {"id": n + 1, "type": kind, "start": start, "end": end, "prov": prov}
        if kind == SLEEP:
            r["value"] = stage
        else:
            r["quantity"] = quantity
        fixture.append(r)
    counts: dict[str, int] = {}
    lines = list(apple_health.run(_store(tmp_path, rows=fixture), counts=counts))
    for line in lines:
        _rfc_rules(line)
    assert len({line["payload"]["raw_id"] for line in lines}) == len(lines)
    bucketed = sum(
        line["payload"]["extra"]["samples"]
        for line in lines
        if line["payload"]["type"] in apple_health.BUCKETED
    )
    single = sum(1 for line in lines if line["payload"]["type"] not in apple_health.BUCKETED)
    assert bucketed + single + sum(counts.values()) == len(rows)
