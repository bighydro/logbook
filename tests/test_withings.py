"""The Withings app's stores → health-sample/v1 (RFC 0014): the scale's weight and body composition
from `<profile>_WTHealth.sqlite`, heart-rate readings from `<profile>_Measure.sqlite`; readings the app
relayed from another app skipped."""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli
from logbook.contrib import adapters
from logbook.contrib.adapters import withings
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
RFC = ROOT / "rfcs" / "0014-health-sample-v1.md"
TZ = "Europe/Oslo"
APPLE_EPOCH = 978_307_200
PROFILE = "10000002"

HEALTH_DDL = """
CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR, Z_SUPER INTEGER, Z_MAX INTEGER);
CREATE TABLE ZWTOBJECT (
    Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZISREMOVED INTEGER, ZISSYNCHRONIZED INTEGER,
    ZREMOTEIDENTIFIER INTEGER, ZSEARCHABLEMETADATA INTEGER, ZSOURCE INTEGER, ZSAMPLE INTEGER, ZACTIVE INTEGER,
    ZQUANTITY INTEGER, ZENDDATE TIMESTAMP, ZSTARTDATE TIMESTAMP, ZLOCALIDENTIFIER VARCHAR,
    ZTYPEIDENTIFIER VARCHAR, ZMETADATA BLOB);
CREATE TABLE ZWTQUANTITY (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZALGORITHMVERSION INTEGER,
    ZSAMPLE INTEGER, ZVALUE FLOAT);
CREATE TABLE ZWTSEARCHABLEMETADATA (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZATTRIB INTEGER,
    ZCATEGORY INTEGER, ZISALLDAY INTEGER, ZISPROCESSING INTEGER, ZPOSITION INTEGER, ZOBJECT INTEGER,
    Z1_OBJECT INTEGER, ZMODIFIEDDATE TIMESTAMP, ZTIMEZONE VARCHAR);
CREATE TABLE ZWTSOURCE (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZBRAND INTEGER,
    ZDEVICEIDENTIFIER INTEGER, ZDEVICEMODEL INTEGER, ZDEVICETYPE INTEGER, ZPRIORITY INTEGER,
    ZBUNDLEIDENTIFIER VARCHAR);
"""
MEASURE_DDL = """
CREATE TABLE Z_PRIMARYKEY (Z_ENT INTEGER PRIMARY KEY, Z_NAME VARCHAR, Z_SUPER INTEGER, Z_MAX INTEGER);
CREATE TABLE ZWTMEASURE (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZALGOVERSION INTEGER,
    ZAPPLIVER INTEGER, ZAPPPFMID INTEGER, ZEXPONENT INTEGER, ZMANTISSA INTEGER, ZPOSITION INTEGER,
    ZSERIALIZEDALGOPARAMS BLOB, Z4_SPECIALIZEDGROUP INTEGER, ZSPECIALIZEDGROUP INTEGER);
CREATE TABLE ZWTMEASUREGROUP (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZATTRIB INTEGER,
    ZBRAND INTEGER, ZCATEGORY INTEGER, ZDEVTYPE INTEGER, ZDEVICEID INTEGER, ZDEVICEMODEL INTEGER,
    ZISPROCESSING INTEGER, ZNETWORK INTEGER, ZREMOTEIDENTIFIER INTEGER, ZREMOVED INTEGER,
    ZSYNCHRONIZED INTEGER, ZUSERID INTEGER, ZCREATIONDATE TIMESTAMP, ZDATE TIMESTAMP,
    ZMODIFIEDDATE TIMESTAMP, ZIDENTIFIER VARCHAR, ZNOTE VARCHAR, ZTIMEZONE VARCHAR);
CREATE TABLE ZWTSPECIALIZEDGROUP (Z_PK INTEGER PRIMARY KEY, Z_ENT INTEGER, Z_OPT INTEGER, ZGROUP INTEGER,
    Z2_GROUP INTEGER, ZDIA INTEGER, ZSYS INTEGER, ZHEARTRATE INTEGER, ZHEIGHT INTEGER, ZMEASURE INTEGER);
"""
HEALTH_ENTITIES = [(1, "WTObject", None, 0), (5, "WTQuantitySample", 2, 0), (6, "WTQuantity", None, 0)]
MEASURE_ENTITIES = [
    (1, "WTMeasure", None, 0),
    (2, "WTMeasureGroup", None, 0),
    (4, "WTSpecializedGroup", None, 0),
    (8, "WTBloodPressureGroup", 4, 0),
    (13, "WTHeartRateGroup", 4, 0),
    (15, "WTHeightGroup", 4, 0),
]
SCALE, RELAY_HEALTH, RELAY_GARMIN = 1, 2, 3  # ZWTSOURCE rows
SOURCES = [
    (SCALE, 8, 1, 1, None, 16, 1, 0, ""),  # the owner's Withings scale
    (RELAY_HEALTH, 8, 1, 22, None, 1059, 1001, 0, "com.apple.Health"),  # a watch's readings, via Health
    (RELAY_GARMIN, 8, 1, 22, None, 1058, 1001, 0, "com.garmin.connect.mobile"),
]
OSLO, LISBON = 1, 2  # ZWTSEARCHABLEMETADATA rows
ZONES = [
    (OSLO, 7, 1, 0, 0, 0, 0, 0, None, None, 0, "Europe/Oslo"),
    (LISBON, 7, 1, 0, 0, 0, 0, 0, None, None, 0, "Europe/Lisbon"),
]


def _apple(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp() - APPLE_EPOCH


STANDING = "2026-03-02T06:31:00Z"  # one standing on the scale: several quantities, one instant
D4, D5, D6, D7 = (
    "2026-03-04T06:30:00Z",
    "2026-03-05T06:30:00Z",
    "2026-03-06T06:30:00Z",
    "2026-03-07T06:30:00Z",
)
# (pk, type identifier, value, start, end, source, zone, removed, local id)
SAMPLES: list[tuple[Any, ...]] = [
    (1, "WTQuantityType.weight", 81.35, STANDING, STANDING, SCALE, OSLO, 0, "L-1"),
    (2, "WTQuantityType.fatMassPercentage", 21.4, STANDING, STANDING, SCALE, OSLO, 0, "L-2"),
    (3, "WTQuantityType.fatMass", 17.409, STANDING, STANDING, SCALE, OSLO, 0, "L-3"),
    (4, "WTQuantityType.fatFreeMass", 63.941, STANDING, STANDING, SCALE, OSLO, 0, "L-4"),
    (5, "WTQuantityType.muscleMass", 60.7, STANDING, STANDING, SCALE, OSLO, 0, "L-5"),
    (6, "WTQuantityType.boneMass", 3.2, STANDING, STANDING, SCALE, OSLO, 0, "L-6"),
    (7, "WTQuantityType.hydration", 44.1, STANDING, STANDING, SCALE, OSLO, 0, "L-7"),
    (8, "WTQuantityType.bmi", 24.87, STANDING, STANDING, SCALE, OSLO, 0, "L-8"),
    (9, "WTQuantityType.vo2Max", 41, "2026-03-03T17:00:00Z", "2026-03-03T17:00:00Z", SCALE, LISBON, 0, "L-9"),
    (10, "WTQuantityType.weight", 81.0, D4, D4, RELAY_HEALTH, OSLO, 0, "L-10"),
    (11, "WTQuantityType.weight", 80.9, D5, D5, RELAY_GARMIN, OSLO, 0, "L-11"),
    (12, "WTQuantityType.r50kHzSegment", 512.3, STANDING, STANDING, SCALE, OSLO, 0, "L-12"),  # impedance
    (13, "WTQuantityType.weight", 79.0, D6, D6, SCALE, OSLO, 1, "L-13"),
    (14, "WTQuantityType.weight", None, D7, D7, SCALE, OSLO, 0, "L-14"),
    (15, "WTQuantityType.weight", 80.5, None, None, SCALE, OSLO, 0, "L-15"),
]  # fmt: skip
CORRELATIONS = [(16, "WTCorrelationType.weight", STANDING, SCALE, OSLO)]  # groups quantities; not a sample
# (group pk, entity, date, zone, device model, removed, identifier, heart rate bpm or height m)
GROUPS: list[tuple[Any, ...]] = [
    (1, 13, "2026-03-02T06:32:00Z", "Europe/Oslo", 16, 0, "G-1", 61),
    (2, 13, "2026-03-03T06:32:00Z", "Europe/Oslo", 16, 0, "G-2", 58),
    (3, 15, "2026-03-02T06:32:00Z", "Europe/Oslo", 16, 0, "G-3", 1.81),  # a height: not a type
    (4, 13, "2026-03-04T06:32:00Z", "Europe/Oslo", 16, 1, "G-4", 90),  # removed
    (5, 8, "2026-03-05T06:32:00Z", "Europe/Oslo", 16, 0, "G-5", None),  # blood pressure: not a type
]  # fmt: skip
HEALTH_LINES = 9  # eight quantities of one standing plus the vo2 max
MEASURE_LINES = 2
LINES = HEALTH_LINES + MEASURE_LINES
SKIPS = {
    "skipped_relayed": 2,
    "skipped_other_type": 3,  # impedance, height, blood pressure
    "skipped_deleted": 2,  # one removed sample, one removed group
    "skipped_no_value": 2,  # a quantity without a value, a correlation row
    "skipped_no_date": 1,
}


def _health_store(folder: Path, profile: str = PROFILE) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{profile}_WTHealth.sqlite"
    with closing(sqlite3.connect(p)) as con:
        con.executescript(HEALTH_DDL)
        con.executemany("INSERT INTO Z_PRIMARYKEY VALUES (?,?,?,?)", HEALTH_ENTITIES)
        con.executemany("INSERT INTO ZWTSOURCE VALUES (?,?,?,?,?,?,?,?,?)", SOURCES)
        con.executemany("INSERT INTO ZWTSEARCHABLEMETADATA VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", ZONES)
        for pk, kind, value, start, end, source, zone, removed, local_id in SAMPLES:
            quantity = None
            if value is not None:
                con.execute("INSERT INTO ZWTQUANTITY VALUES (?,?,?,?,?,?)", (pk, 6, 1, 1, pk, value))
                quantity = pk
            con.execute(
                "INSERT INTO ZWTOBJECT VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pk, 5, 1, removed, 1, None, zone, source, None, 1, quantity, _apple(end) if end else None,
                 _apple(start) if start else None, local_id, kind, None),
            )  # fmt: skip
        for pk, kind, start, source, zone in CORRELATIONS:
            con.execute(
                "INSERT INTO ZWTOBJECT VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    pk,
                    3,
                    1,
                    0,
                    1,
                    None,
                    zone,
                    source,
                    None,
                    1,
                    None,
                    _apple(start),
                    _apple(start),
                    f"C-{pk}",
                    kind,
                    None,
                ),
            )
        con.commit()
    return p


def _measure_store(folder: Path, profile: str = PROFILE) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / f"{profile}_Measure.sqlite"
    with closing(sqlite3.connect(p)) as con:
        con.executescript(MEASURE_DDL)
        con.executemany("INSERT INTO Z_PRIMARYKEY VALUES (?,?,?,?)", MEASURE_ENTITIES)
        for pk, entity, date, zone, model, removed, identifier, reading in GROUPS:
            con.execute(
                "INSERT INTO ZWTMEASUREGROUP VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (pk, 2, 1, 0, 1, 1, 1, None, model, 0, 0, None, removed, 1, int(PROFILE), _apple(date),
                 _apple(date),
                 _apple(date), identifier, None, zone),
            )  # fmt: skip
            measure = None
            if reading is not None:
                exponent = -2 if isinstance(reading, float) else 0
                con.execute(
                    "INSERT INTO ZWTMEASURE VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (pk, 1, 1, 0, 0, 0, exponent, round(reading * 10**-exponent), None, None, None, None),
                )
                measure = pk
            heart_rate = measure if entity == 13 else None
            height = measure if entity == 15 else None
            con.execute(
                "INSERT INTO ZWTSPECIALIZEDGROUP VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    pk,
                    entity,
                    1,
                    pk,
                    2,
                    80 if entity == 8 else None,
                    120 if entity == 8 else None,
                    heart_rate,
                    height,
                    None,
                ),
            )
        con.commit()
    return p


def _stores(folder: Path, *, measure: bool = True) -> Path:
    """Both stores of one profile in one folder, as the app keeps them; the WTHealth store's path."""
    p = _health_store(folder)
    if measure:
        _measure_store(folder)
    return p


def _lines(tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    return list(withings.run(_stores(tmp_path / "withings"), **kw))


def _by_raw_id(lines: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {line["payload"]["raw_id"]: line for line in lines}


def _profile() -> dict[str, Any]:
    block = re.search(r"## JSON Schema\n\n```json\n(.*?)\n```", RFC.read_text(encoding="utf-8"), re.S)
    assert block is not None
    schema: dict[str, Any] = json.loads(block.group(1))
    return schema


# -- registry and sniff ----------------------------------------------------------------------------


def test_registry_lists_withings():
    assert withings in adapters.file_adapters()
    assert adapters.named("withings") is withings


def test_sniff_takes_either_store_and_nothing_else(tmp_path):
    health = _stores(tmp_path / "w")
    assert withings.sniff(health) and withings.sniff(health.parent / f"{PROFILE}_Measure.sqlite")
    other = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(other)) as con:
        con.execute("CREATE TABLE ZWTOBJECT (x)")
    assert not withings.sniff(other)  # the table without its quantities is not the store
    assert not withings.sniff(tmp_path / "missing.sqlite")


# -- the lines -------------------------------------------------------------------------------------


def test_every_line_is_a_health_sample_with_the_rfc_payload(tmp_path):
    lines = _lines(tmp_path, timezone=TZ)
    assert len(lines) == LINES
    validator = Draft202012Validator(_profile())
    for line in lines:
        assert set(line) == {"at", "end", "tz", "source", "kind", "tier", "payload"}
        assert (line["source"], line["kind"], line["tier"]) == ("withings", "health", 3)
        validator.validate(line["payload"])
    assert [line["at"] for line in lines] == sorted(line["at"] for line in lines)


def test_one_standing_on_the_scale_is_one_line_per_quantity_at_one_instant(tmp_path):
    by = _by_raw_id(_lines(tmp_path))
    weight = by[f"weight:{PROFILE}:L-1"]
    assert (weight["at"], weight["end"], weight["tz"]) == (STANDING, None, "Europe/Oslo")
    assert weight["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": f"weight:{PROFILE}:L-1",
        "type": "weight",
        "value": 81.35,
        "unit": "kg",
        "device": "16",
        "extra": {"profile": PROFILE},
    }
    standing = {
        p["type"]: (p["value"], p["unit"])
        for line in by.values()
        if (p := line["payload"]) and line["at"] == STANDING
    }
    assert standing == {
        "weight": (81.35, "kg"),
        "body_fat_pct": (21.4, "%"),
        "fat_mass": (17.409, "kg"),
        "fat_free_mass": (63.941, "kg"),
        "muscle_mass": (60.7, "kg"),
        "bone_mass": (3.2, "kg"),
        "body_water": (44.1, "kg"),
        "bmi": (24.87, "kg/m2"),
    }
    vo2 = by[f"vo2_max:{PROFILE}:L-9"]
    assert (
        vo2["payload"]["value"] == 41
        and vo2["payload"]["unit"] == "mL/kg/min"
        and vo2["tz"] == "Europe/Lisbon"
    )


def test_heart_rate_readings_come_from_the_measure_store_beside_it(tmp_path):
    by = _by_raw_id(_lines(tmp_path))
    hr = by[f"heart_rate:{PROFILE}:G-1"]
    assert hr["at"] == "2026-03-02T06:32:00Z" and hr["tz"] == "Europe/Oslo"
    assert hr["payload"] == {
        "schema": "health-sample/v1",
        "raw_id": f"heart_rate:{PROFILE}:G-1",
        "type": "heart_rate",
        "value": 61,
        "unit": "bpm",
        "device": "16",
        "extra": {"profile": PROFILE},
    }
    assert by[f"heart_rate:{PROFILE}:G-2"]["payload"]["value"] == 58


def test_relayed_removed_valueless_undated_and_unknown_rows_are_skipped_and_counted(tmp_path):
    counts: dict[str, int] = {}
    lines = _lines(tmp_path, counts=counts)
    assert len(lines) == LINES
    assert {k: v for k, v in counts.items() if k.startswith("skipped_")} == SKIPS
    raw_ids = set(_by_raw_id(lines))
    assert (
        not {
            f"weight:{PROFILE}:L-10",
            f"weight:{PROFILE}:L-11",
            f"weight:{PROFILE}:L-13",
            f"weight:{PROFILE}:L-14",
            f"weight:{PROFILE}:L-15",
        }
        & raw_ids
    )


def test_either_store_brings_its_partner_and_a_store_alone_gives_only_its_own(tmp_path):
    folder = tmp_path / "w"
    _stores(folder)
    assert len(list(withings.run(folder / f"{PROFILE}_Measure.sqlite"))) == LINES  # the partner came along
    hr_only = list(withings.run(_measure_store(tmp_path / "m")))
    assert {line["payload"]["type"] for line in hr_only} == {"heart_rate"} and len(hr_only) == MEASURE_LINES
    health_only = list(withings.run(_stores(tmp_path / "h", measure=False)))
    assert len(health_only) == HEALTH_LINES and "heart_rate" not in {
        line["payload"]["type"] for line in health_only
    }


def test_a_folder_reads_every_profile_in_it(tmp_path):
    folder = tmp_path / "coredata"
    _stores(folder)
    _health_store(folder, "10000001")
    _measure_store(folder, "10000001")
    lines = list(withings.run(folder))
    assert len(lines) == 2 * LINES
    assert {line["payload"]["extra"]["profile"] for line in lines} == {PROFILE, "10000001"}
    assert len({line["payload"]["raw_id"] for line in lines}) == 2 * LINES  # the profile is in the key


def test_since_and_tier(tmp_path):
    lines = _lines(tmp_path, since="2026-03-03T00:00:00Z", tier=2)
    assert sorted(line["payload"]["raw_id"] for line in lines) == [
        f"heart_rate:{PROFILE}:G-2",
        f"vo2_max:{PROFILE}:L-9",
    ]
    assert {line["tier"] for line in lines} == {2}


def test_the_stores_are_never_written(tmp_path):
    store = _stores(tmp_path / "w")
    before = {p.name: p.read_bytes() for p in store.parent.iterdir()}
    list(withings.run(store))
    assert {p.name: p.read_bytes() for p in store.parent.iterdir()} == before


# -- through the CLI --------------------------------------------------------------------------------


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook.init(root, TZ)


def test_add_withings_appends_once_and_reports_the_skips(lb, tmp_path, capsys):
    store = _stores(tmp_path / "w")
    cli.main(["add", "withings", str(store)])
    out = capsys.readouterr().out
    assert f"added {LINES} lines from withings" in out
    for phrase in ("2 relayed from another app", "3 of a type this version does not know", "2 deleted"):
        assert phrase in out, phrase
    cli.main(["add", "withings", str(store)])
    assert "added 0 lines" in capsys.readouterr().out
    seq, _head, errors = lb.verify()
    assert (seq, errors) == (LINES, [])
