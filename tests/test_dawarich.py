"""Dawarich's GeoJSON export → location/v1 (RFC 0001), as a property: for ANY export in the shape
Dawarich writes — any point attributes of any type, any coordinates, any reverse-geocode block — `run`
yields only valid lines, one per point, each appending into a record that verifies and validates
against the observation schema; `sniff` never raises on ANY bytes and claims an export exactly when
its first feature is a point of a tracker. The fixture's exact lines are tests/test_adapters.py's."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator
from logbook.adapters import dawarich
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
ENVELOPE = {"at", "end", "tz", "source", "kind", "tier", "payload"}
RFC0001_FIELDS = {
    "schema",
    "lat",
    "lon",
    "accuracy_m",
    "alt_m",
    "speed_mps",
    "heading_deg",
    "provider",
    "tracker",
    "raw_id",
    "subject",
    "extra",
}

_text = st.text(max_size=8)
_i64 = st.integers(-(2**63 - 1), 2**63 - 1)  # ijson's C backend refuses wider integers
_finite = st.floats(allow_nan=False, allow_infinity=False)
# what a numeric attribute looks like in the wild: Dawarich writes altitude, velocity and course as
# strings; a number, a bool, nothing and plain text happen too
_numeric = st.one_of(
    st.none(),
    st.booleans(),
    _finite,
    _i64,
    _finite.map(str),
    st.sampled_from(["nan", "inf", "-inf", "1e400", "", " 12 ", "fast"]),
    _text,
)
_scalar = st.one_of(st.none(), st.booleans(), _i64, _finite, _text)
_place = st.one_of(
    st.none(),
    _text,
    st.fixed_dictionaries(
        {},
        optional={
            "properties": st.one_of(
                _text,
                st.dictionaries(
                    st.sampled_from([*dawarich.PLACE_FIELDS, "osm_key", "x"]), _scalar, max_size=6
                ),
            )
        },
    ),
)
_props = st.fixed_dictionaries(
    {
        # `datetime.fromtimestamp` wants a timestamp every platform accepts: 1970 to 2038 covers a tracker
        "timestamp": st.one_of(st.integers(0, 2**31 - 1), st.floats(0, 2**31 - 1, allow_nan=False)),
        "tracker_id": st.one_of(st.uuids().map(str), _text),
    },
    optional={
        "accuracy": _numeric,
        "altitude": _numeric,
        "velocity": _numeric,
        "course": _numeric,
        "anomaly": _scalar,
        "track_id": _scalar,
        "vertical_accuracy": _scalar,
        "battery": _scalar,
        "ssid": _scalar,
        "bssid": _scalar,
        "motion_data": _scalar,
        "geodata": _place,
        "city": _text,
    },
)
_coordinates = st.one_of(
    st.tuples(st.floats(-180, 180, allow_nan=False), st.floats(-90, 90, allow_nan=False)).map(list),
    st.tuples(st.floats(-180, 180, allow_nan=False), st.floats(-90, 90, allow_nan=False), _finite).map(list),
)
_feature = st.fixed_dictionaries(
    {
        "type": st.just("Feature"),
        "geometry": st.fixed_dictionaries({"type": st.just("Point"), "coordinates": _coordinates}),
        "properties": _props,
    }
)


def _export(tmp_path_factory, features: list[dict]) -> Path:
    p = tmp_path_factory.mktemp("dawarich") / "export.json"
    doc = {"type": "FeatureCollection", "features": features}  # `type` first, as Dawarich writes it
    p.write_text(json.dumps(doc, allow_nan=False), encoding="utf-8")
    return p


def _rfc_rules(line: dict) -> None:
    assert set(line) == ENVELOPE
    assert (line["source"], line["kind"], line["tier"], line["end"], line["tz"]) == (
        "dawarich",
        "location",
        1,
        None,
        None,
    )
    assert line["at"].endswith("Z") and len(line["at"]) == 20
    datetime.strptime(line["at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    p = line["payload"]
    assert set(p) <= RFC0001_FIELDS and p["schema"] == "location/v1"
    assert type(p["lat"]) is float and type(p["lon"]) is float
    assert -90 <= p["lat"] <= 90 and -180 <= p["lon"] <= 180
    for key in ("accuracy_m", "alt_m", "speed_mps", "heading_deg"):
        assert key not in p or (isinstance(p[key], float) and math.isfinite(p[key]))
    assert "speed_mps" not in p or p["speed_mps"] >= 0
    assert "heading_deg" not in p or 0 <= p["heading_deg"] <= 360
    assert isinstance(p["raw_id"], str) and p["raw_id"].startswith(f"{p['tracker']}:")
    assert isinstance(p["extra"], dict)
    assert "place" not in p["extra"] or (isinstance(p["extra"]["place"], dict) and p["extra"]["place"])
    json.dumps(line, allow_nan=False)


@settings(max_examples=40, deadline=None)
@given(st.lists(_feature, max_size=8))
def test_any_export_yields_only_valid_lines_one_per_point(tmp_path_factory, features):
    p = _export(tmp_path_factory, features)
    assert dawarich.sniff(p) is (len(features) > 0)
    lines = list(dawarich.run(p))
    assert len(lines) == len(features)
    for line in lines:
        _rfc_rules(line)
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "Europe/Oslo")
    assert lb.append_many(lines) == len({line["payload"]["raw_id"] for line in lines})
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == len({line["payload"]["raw_id"] for line in lines})
    validator = Draft202012Validator(SCHEMA)
    for stored in lb.lines():
        validator.validate(stored)
        assert stored["tz"] == "Europe/Oslo"


@settings(max_examples=40, deadline=None)
@given(st.lists(_feature, max_size=8), st.integers(0, 2**31 - 1))
def test_since_keeps_only_points_at_or_after_it_in_export_order(tmp_path_factory, features, since_s):
    p = _export(tmp_path_factory, features)
    since = datetime.fromtimestamp(since_s, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    kept = list(dawarich.run(p, since=since))
    assert kept == [line for line in dawarich.run(p) if line["at"] >= since]


@settings(max_examples=60, deadline=None)
@given(st.binary(max_size=200))
def test_sniff_never_raises_on_any_bytes(tmp_path_factory, data):
    p = tmp_path_factory.mktemp("sniff") / "export.json"
    p.write_bytes(data)
    assert dawarich.sniff(p) in (True, False)


def test_sniff_is_false_for_a_folder_and_a_missing_file(tmp_path):
    assert dawarich.sniff(tmp_path) is False
    assert dawarich.sniff(tmp_path / "nowhere.json") is False
