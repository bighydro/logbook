"""MyFitnessPal's maindb.sqlite → health-sample/v1 (RFC 0014): logged foods as `energy_intake`,
weights, exercise as `workout`; daily step totals and the other body measurements skipped."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import myfitnesspal
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "rfcs" / "0014-health-sample-v1.md"
TZ = "Europe/Oslo"

DDL = """
CREATE TABLE food_entries (id INTEGER PRIMARY KEY, master_id INTEGER, user_id INTEGER, entry_date TEXT,
    food_id INTEGER, original_food_id INTEGER, meal_id INTEGER, quantity REAL, weight_index INTEGER,
    fraction INTEGER, uid TEXT, sync_flags INTEGER, meal_food_id INTEGER, entry_time TEXT, logged_at TEXT);
CREATE TABLE foods (id INTEGER PRIMARY KEY, master_id INTEGER, original_food_id INTEGER,
    original_food_master_id INTEGER, owner_user_id INTEGER, owner_user_master_id INTEGER, food_type INTEGER,
    deleted INTEGER, destroyed INTEGER, is_public INTEGER, description TEXT, brand TEXT, food_info BLOB,
    grams REAL, barcode TEXT, uid TEXT, original_food_uid TEXT, is_verified INTEGER, sync_flags INTEGER,
    promoted_from_master_id INTEGER, promoted_from_uid TEXT, country_code TEXT);
CREATE TABLE food_portions (food_id INTEGER, weight_index INTEGER, amount REAL, gram_weight REAL,
    description TEXT, is_fraction INTEGER, nutritional_multiplier REAL);
CREATE TABLE nutritional_values (food_id INTEGER, nutrient_id INTEGER, value REAL);
CREATE TABLE measurement_types (id INTEGER PRIMARY KEY, master_id INTEGER, user_id INTEGER, position INTEGER,
    description TEXT, updated_at TEXT, last_sync_at TEXT, uid TEXT);
CREATE TABLE measurements (id INTEGER PRIMARY KEY, master_id INTEGER, user_id INTEGER,
    measurement_type_id INTEGER,
    value REAL, entry_date TEXT, uid TEXT, source TEXT, sync_flags INTEGER);
CREATE TABLE exercises (id INTEGER PRIMARY KEY, uid TEXT, version INTEGER, user_id INTEGER,
    exercise_type INTEGER,
    description TEXT, mets REAL, deleted INTEGER, destroyed INTEGER, is_public INTEGER,
    is_calorie_adjustment INTEGER, sync_flags INTEGER, master_id INTEGER);
CREATE TABLE exercise_entries (id INTEGER PRIMARY KEY, master_id INTEGER, user_id INTEGER, entry_date TEXT,
    exercise_type INTEGER, exercise_id INTEGER, original_exercise_id INTEGER, quantity INTEGER, sets INTEGER,
    weight REAL, calories INTEGER, uid TEXT, deleted INTEGER, sync_flags INTEGER, exercise_master_id INTEGER,
    exercise_version INTEGER, duration_in_seconds INTEGER, repetitions INTEGER, steps INTEGER,
    distance_in_miles REAL, device_id TEXT, client_id TEXT, source TEXT, healthkit_id TEXT, data BLOB,
    fitness_event_data BLOB);
CREATE TABLE steps_entries (id INTEGER PRIMARY KEY, uid TEXT, user_id INTEGER, entry_date TEXT,
    exercise_entry_master_id INTEGER, steps INTEGER, calories INTEGER, client_id TEXT, device_id TEXT,
    step_goal INTEGER, is_primary_step_source INTEGER);
CREATE TABLE user_properties (id INTEGER PRIMARY KEY, user_id INTEGER, property_name TEXT,
    property_value TEXT,
    updated_at TEXT, last_sync_at TEXT, upstream_sync_retry INTEGER);
"""
PROPERTIES = [
    ("meal_names", '"Breakfast","Lunch","Dinner","Snacks"'),
    ("timezone_identifier", "Europe/Oslo"),
    ("body_weight_unit_preference", "kg"),
    ("energy_unit_preference", "0"),
]
FOODS = [  # (id, description, brand, grams)
    (1, "Oatmeal, cooked", None, 234.0),
    (2, "Brunost", "Tine", 100.0),
    (3, "Mystery bar", None, None),
]
PORTIONS = [  # (food id, weight index, amount, gram weight, description, multiplier)
    (1, 0, 1.0, 234.0, "cup", 1.0),
    (1, 1, 0.5, 117.0, "cup", 0.5),
    (2, 0, 100.0, 100.0, "g", 1.0),
    (2, 1, 1.0, 10.0, "slice", 0.1),
    (3, 0, 1.0, 40.0, "bar", 1.0),
]
NUTRIENTS = [(1, 0, 158.0), (1, 1, 3.2), (2, 0, 466.0), (2, 1, 29.0)]  # nutrient 0 is energy in kcal
ENTRIES = [  # (id, entry date, entry time, logged at, food id, meal id, quantity, weight index, uid)
    (1, "2026-03-02", "07:45:00", "2026-03-02T07:46:10+0100", 1, 1, 1.0, 1, "E-1"),
    (2, "2026-03-02", "12:10:00", "2026-03-02T12:11:00+0100", 2, 2, 3.0, 1, "E-2"),
    (3, "2026-03-03", None, "2026-03-04T09:00:00+0100", 2, 3, 0.5, 0, "E-3"),  # no clock: a day
    (4, "2026-03-03", "19:00:00", "2026-03-03T19:00:00+0100", 3, 4, 1.0, 0, "E-4"),  # no energy known
    (5, "2026-03-04", "08:00:00", None, 9, 1, 1.0, 0, "E-5"),  # a food the store no longer has
]
MEASUREMENT_TYPES = [(1, "Weight"), (2, "Neck"), (3, "Waist")]
MEASUREMENTS = [  # (id, type, value, entry date, uid)
    (1, 1, 81.2, "2026-03-02", "M-1"),
    (2, 3, 84.0, "2026-03-02", "M-2"),  # a waist: not a type
    (3, 1, 0.0, "2026-03-03", "M-3"),  # the app's placeholder for "not entered"
]
EXERCISES = [(1, "Running", 0, 9.8)]
EXERCISE_ENTRIES = [  # (id, entry date, exercise id, calories, duration s, uid)
    (1, "2026-03-02", 1, 410, 2400, "X-1"),
    (2, "2026-03-03", 1, 100, None, "X-2"),  # no duration: nothing to span
]
STEPS = [(1, "2026-03-02", 8412, "S-1")]
LINES = 5  # three foods with energy, one weight, one workout
SKIPS = {
    "skipped_no_value": 3,  # a food without energy, a food the store lost, a weight of 0
    "skipped_other_type": 1,
    "skipped_daily_total": 1,
    "skipped_bad_span": 1,
}


def _store(folder: Path, *, properties: list[tuple[str, str]] = PROPERTIES) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / "maindb.sqlite"
    with closing(sqlite3.connect(p)) as con:
        con.executescript(DDL)
        for i, (name, value) in enumerate(properties, 1):
            con.execute(
                "INSERT INTO user_properties VALUES (?,?,?,?,?,?,?)", (i, 1, name, value, None, None, 0)
            )
        for fid, description, brand, grams in FOODS:
            con.execute(
                "INSERT INTO foods VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (fid, fid, None, None, 1, 1, 1, 0, 0, 1, description, brand, b"", grams, None, f"F-{fid}",
                 None, 1,
                 0, None, None, "NO"),
            )  # fmt: skip
        for fid, index, amount, gram_weight, description, multiplier in PORTIONS:
            con.execute(
                "INSERT INTO food_portions VALUES (?,?,?,?,?,?,?)",
                (fid, index, amount, gram_weight, description, 0, multiplier),
            )
        con.executemany("INSERT INTO nutritional_values VALUES (?,?,?)", NUTRIENTS)
        for eid, date, time, logged, fid, meal, quantity, index, uid in ENTRIES:
            con.execute(
                "INSERT INTO food_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, eid, 1, date, fid, None, meal, quantity, index, 1, uid, 0, None, time, logged),
            )
        for tid, description in MEASUREMENT_TYPES:
            con.execute(
                "INSERT INTO measurement_types VALUES (?,?,?,?,?,?,?,?)",
                (tid, tid, 1, tid, description, None, None, f"T-{tid}"),
            )
        for mid, tid, value, date, uid in MEASUREMENTS:
            con.execute(
                "INSERT INTO measurements VALUES (?,?,?,?,?,?,?,?,?)",
                (mid, mid, 1, tid, value, date, uid, "", 0),
            )
        for xid, description, kind, mets in EXERCISES:
            con.execute(
                "INSERT INTO exercises VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (xid, f"EX-{xid}", 1, 1, kind, description, mets, 0, 0, 1, 0, 0, xid),
            )
        for eid, date, xid, calories, duration, uid in EXERCISE_ENTRIES:
            con.execute(
                "INSERT INTO exercise_entries VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (eid, eid, 1, date, 0, xid, None, 1, None, None, calories, uid, 0, 0, xid, 1, duration, None,
                 None,
                 None, None, None, "mfp-mobile-ios", None, None, None),
            )  # fmt: skip
        for sid, date, steps, uid in STEPS:
            con.execute(
                "INSERT INTO steps_entries VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (sid, uid, 1, date, None, steps, 300, None, None, 10000, 1),
            )
        con.commit()
    return p


def _lines(tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(myfitnesspal.run(_store(tmp_path / "mfp"), **kw))


def _by_raw_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


def _profile() -> dict[str, Any]:
    block = re.search(r"## JSON Schema\n\n```json\n(.*?)\n```", RFC.read_text(encoding="utf-8"), re.S)
    assert block is not None
    schema: dict[str, Any] = json.loads(block.group(1))
    return schema


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_lists_myfitnesspal():
    assert myfitnesspal in adapters.file_adapters()
    assert adapters.named("myfitnesspal") is myfitnesspal


def test_sniff_takes_the_store_and_nothing_else(tmp_path):
    assert myfitnesspal.sniff(_store(tmp_path / "mfp"))
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as con:
        con.execute("CREATE TABLE food_entries (x)")
    assert not myfitnesspal.sniff(other)
    assert not myfitnesspal.sniff(tmp_path / "missing.sqlite")


# -- the lines -------------------------------------------------------------------------------------


def test_every_line_is_a_health_sample_with_the_rfc_payload(tmp_path):
    lines = _lines(tmp_path, timezone=TZ)
    assert len(lines) == LINES
    validator = Draft202012Validator(_profile())
    for line in lines:
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert (line["source"], line["kind"], line["tier"], line["tz"]) == (
            "myfitnesspal",
            "health",
            3,
            "Europe/Oslo",
        )
        validator.validate(line["payload"])
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_a_logged_food_is_its_energy_from_the_portion_and_quantity_at_the_local_clock(tmp_path):
    by = _by_raw_id(_lines(tmp_path))
    oats = by["energy_intake:E-1"]
    assert (oats["at"], oats["end"]) == ("2026-03-02T06:45:00Z", None)  # 07:45 Oslo, CET
    assert oats["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": "energy_intake:E-1",
        "type": "energy_intake",
        "value": 79,  # 158 kcal per cup x 0.5 cup x 1
        "unit": "kcal",
        "source_name": "MyFitnessPal",
        "extra": {"meal": "Breakfast", "food": "Oatmeal, cooked", "quantity": 1, "portion": "0.5 cup"},
    }
    cheese = by["energy_intake:E-2"]["payload"]
    assert cheese["value"] == 139.8 and cheese["extra"] == {
        "meal": "Lunch", "food": "Brunost", "brand": "Tine", "quantity": 3, "portion": "1 slice",
    }  # fmt: skip


def test_an_entry_without_a_clock_is_a_span_over_its_local_day(tmp_path):
    line = _by_raw_id(_lines(tmp_path))["energy_intake:E-3"]
    assert (line["at"], line["end"]) == ("2026-03-02T23:00:00Z", "2026-03-03T23:00:00Z")
    assert line["payload"]["value"] == 233 and line["payload"]["extra"]["all_day"] is True
    assert line["payload"]["extra"]["meal"] == "Dinner"


def test_a_weight_and_a_workout(tmp_path):
    by = _by_raw_id(_lines(tmp_path))
    weight = by["weight:M-1"]
    assert weight["at"] == "2026-03-01T23:00:00Z" and weight["end"] == "2026-03-02T23:00:00Z"
    assert weight["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": "weight:M-1",
        "type": "weight",
        "value": 81.2,
        "unit": "kg",
        "source_name": "MyFitnessPal",
        "extra": {"all_day": True},
    }
    workout = by["workout:X-1"]
    assert workout["at"] == "2026-03-01T23:00:00Z" and workout["end"] == "2026-03-02T23:00:00Z"
    assert workout["payload"]["value"] == 2400 and workout["payload"]["unit"] == "s"
    assert workout["payload"]["extra"] == {"activity": "Running", "energy_kcal": 410, "all_day": True}


def test_pounds_are_converted_to_kilograms_and_the_entered_value_kept(tmp_path):
    props = [(k, "lbs" if k == "body_weight_unit_preference" else v) for k, v in PROPERTIES]
    lines = list(myfitnesspal.run(_store(tmp_path / "mfp", properties=props)))
    weight = _by_raw_id(lines)["weight:M-1"]["payload"]
    assert weight["value"] == 36.832 and weight["extra"]["original"] == {"quantity": 81.2, "unit": "lbs"}


def test_skips_are_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(tmp_path, counts=counts)
    assert len(lines) == LINES
    assert {k: v for k, v in counts.items() if k.startswith("skipped_")} == SKIPS


def test_without_a_zone_in_the_store_the_records_zone_places_the_clock(tmp_path):
    props = [(k, v) for k, v in PROPERTIES if k != "timezone_identifier"]
    lines = list(myfitnesspal.run(_store(tmp_path / "mfp", properties=props), timezone="America/New_York"))
    oats = _by_raw_id(lines)["energy_intake:E-1"]
    assert oats["at"] == "2026-03-02T12:45:00Z" and oats["tz"] == "America/New_York"
    bare = list(myfitnesspal.run(_store(tmp_path / "bare", properties=props)))
    assert _by_raw_id(bare)["energy_intake:E-1"]["at"] == "2026-03-02T07:45:00Z"  # UTC when nobody says


def test_since_and_tier(tmp_path):
    lines = _lines(tmp_path, since="2026-03-02T12:00:00Z", tier=2)
    assert sorted(line["payload"]["raw_id"] for line in lines) == ["energy_intake:E-3"]
    assert {line["tier"] for line in lines} == {2}


def test_the_store_is_never_written(tmp_path):
    store = _store(tmp_path / "mfp")
    before = store.read_bytes()
    list(myfitnesspal.run(store))
    assert store.read_bytes() == before and [p.name for p in store.parent.iterdir()] == ["maindb.sqlite"]


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def test_add_myfitnesspal_appends_once(lb, tmp_path, capsys):
    store = _store(tmp_path / "mfp")
    cli.main(["add", "myfitnesspal", str(store)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from myfitnesspal" in out and "1 daily totals" in out
    cli.main(["add", "myfitnesspal", str(store)])
    assert "added 0 lines" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])
