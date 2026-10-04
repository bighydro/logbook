"""What the Withings and MyFitnessPal readers share (`logbook.adapters.health_export`), as properties:
for ANY bytes `rows` returns None or rows keyed by the header; for ANY text `number`, `when`, `stamp`
and `slug` return a value of the promised shape or None and never raise; and for ANY drafts against
ANY standing lines `corrected` yields exactly one draft per draft, in order, each a valid
health-sample/v1 line that appends into a record — the ones the record holds with another sample
rewritten as corrections (`raw_id` suffixed `:v<n>`, `supersedes` the standing line), the rest as
they came. The readers' exact lines are tests/test_withings_export.py's and
tests/test_myfitnesspal_export.py's."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from hypothesis import given, settings
from hypothesis import strategies as st
from jsonschema import Draft202012Validator

from logbook.contrib.adapters import health_export
from logbook.core.store import Logbook, uuid7

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
STAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ")
OSLO = ZoneInfo("Europe/Oslo")

# -- the cells -------------------------------------------------------------------------------------


@settings(max_examples=60, deadline=None)
@given(st.binary(max_size=200))
def test_any_bytes_read_as_none_or_rows_keyed_by_the_header(tmp_path_factory, data):
    p = tmp_path_factory.mktemp("csv") / "export.csv"
    p.write_bytes(data)
    out = health_export.rows(p)
    if out is None:
        return
    header, rows = out
    assert all(cell == cell.strip().lower() for cell in header)
    for row in rows:
        assert set(row) == set(header)
        assert all(isinstance(v, str) and v == v.strip() for v in row.values())
        assert any(row.values()) or not header


def test_a_csv_reads_by_header_name_and_skips_blank_rows(tmp_path):
    p = tmp_path / "weight.csv"
    p.write_text(
        "\ufeffDate , Weight (kg),Comments\n2026-06-08 07:12:33, 81.5 ,\n,,\n2026-06-09,80.9,ok\n",
        encoding="utf-8",
    )
    header, rows = health_export.rows(p)
    assert header == ["date", "weight (kg)", "comments"]
    assert rows == [
        {"date": "2026-06-08 07:12:33", "weight (kg)": "81.5", "comments": ""},
        {"date": "2026-06-09", "weight (kg)": "80.9", "comments": "ok"},
    ]
    assert health_export.column(header, "weight (kg)", "weight") == "weight (kg)"
    assert health_export.column(header, "height") is None


_finite = st.floats(allow_nan=False, allow_infinity=False)


@settings(max_examples=100, deadline=None)
@given(
    st.one_of(
        st.none(), st.integers(), st.floats(), st.text(max_size=12), _finite.map(str), st.integers().map(str)
    )
)
def test_any_cell_is_a_finite_number_or_none(text):
    out = health_export.number(text)
    if out is None:
        return
    assert isinstance(out, int | float) and not isinstance(out, bool)
    assert out == out and out not in (float("inf"), float("-inf"))
    assert isinstance(out, int) or out != int(out)  # a whole number is an int
    assert isinstance(text, str) and float(text) == out


@settings(max_examples=100, deadline=None)
@given(_finite)
def test_rounded_keeps_three_decimals_and_whole_numbers_as_ints(value):
    out = health_export.rounded(value)
    assert isinstance(out, int) or (isinstance(out, float) and out != int(out))
    assert abs(out - round(value, 3)) < 1e-9 or out == round(value, 3)


_clock = st.datetimes(min_value=datetime(1900, 1, 1), max_value=datetime(2100, 1, 1))


@settings(max_examples=100, deadline=None)
@given(
    st.one_of(
        st.text(max_size=20),
        _clock.map(lambda d: d.isoformat(timespec="seconds")),
        _clock.map(lambda d: d.isoformat(timespec="seconds") + "Z"),
        _clock.map(lambda d: d.isoformat(timespec="seconds") + "+02:00"),
        _clock.map(lambda d: d.strftime(" %Y-%m-%d %H:%M:%S ")),
    ),
    st.sampled_from([UTC, OSLO]),
)
def test_any_cell_is_an_instant_in_utc_or_none(text, local):
    out = health_export.when(text, local)
    if out is None:
        return
    assert isinstance(out, datetime) and out.tzinfo is UTC
    assert STAMP.fullmatch(health_export.stamp(out))
    parsed = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    expected = parsed if parsed.tzinfo else parsed.replace(tzinfo=local)
    assert out == expected.astimezone(UTC)


@settings(max_examples=100, deadline=None)
@given(st.text(max_size=20))
def test_any_header_slugs_to_a_plain_key(text):
    out = health_export.slug(text)
    assert all(ch == "_" or ch.isalnum() for ch in out)
    assert out == out.lower() and "__" not in out
    assert not out.startswith("_") and not out.endswith("_")
    assert health_export.slug(out) == out


def test_zone_is_the_record_zone_or_utc():
    assert health_export.zone(None) is UTC
    assert health_export.zone("") is UTC
    assert health_export.zone("Mars/Olympus") is UTC
    assert isinstance(health_export.zone("Europe/Oslo"), tzinfo)


# -- the correction pass ---------------------------------------------------------------------------

_raw_id = st.text("abcdefghijklmnopqrstuvwxyz0123456789:_-", min_size=1, max_size=10)
_stamp = st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2040, 1, 1)).map(
    lambda d: d.replace(microsecond=0).isoformat() + "Z"
)
_payload = st.fixed_dictionaries(
    {
        "schema": st.just("health-sample/v1"),
        "raw_id": _raw_id,
        "type": st.sampled_from(["weight", "steps", "sleep", "heart_rate"]),
        "value": st.one_of(st.integers(0, 100_000), st.floats(0, 500, allow_nan=False)),
        "unit": st.sampled_from(["kg", "count", "min", "bpm"]),
    },
    optional={
        "stage": st.sampled_from(["asleep", "deep", "rem"]),
        "device": st.sampled_from(["Body+", "ScanWatch"]),
        "extra": st.dictionaries(st.sampled_from(["energy_kcal", "fat_g"]), st.integers(0, 999), max_size=2),
    },
)
_draft = st.fixed_dictionaries(
    {
        "at": _stamp,
        "end": st.one_of(st.none(), _stamp),
        "tz": st.none(),
        "source": st.sampled_from(["withings", "myfitnesspal"]),
        "kind": st.just("health-sample"),
        "tier": st.sampled_from([1, 2]),
        "payload": _payload,
    }
)
# what the record holds for a draft's key: nothing, the same sample, another sample, or two versions
# already corrected once (the standing one under `:v2`)
_held = st.sampled_from(["none", "same", "other", "other-twice"])


def _standing(draft: dict[str, Any], same: bool) -> dict[str, Any]:
    payload = dict(draft["payload"])
    if not same:
        payload["value"] = payload["value"] + 1
    return {"id": uuid7(), "at": draft["at"], "end": draft["end"], "payload": payload}


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(_draft, _held), max_size=8))
def test_any_drafts_against_any_record_yield_one_valid_line_each(tmp_path_factory, cases):
    record: dict[tuple[str, str], dict[str, Any]] = {}
    fate: dict[tuple[str, str], str] = {}  # a key's first case decides what the record holds for it
    expected: list[dict[str, Any] | None] = []
    for draft, held in cases:
        key = (draft["source"], draft["payload"]["raw_id"])
        if key in fate:
            expected.append(None)  # a later draft of the same key: checked by shape only
            continue
        fate[key] = held
        if held == "none":
            expected.append(draft)
            continue
        if held == "same":
            record[key] = _standing(draft, same=True)
            expected.append(draft)
            continue
        record[key] = _standing(draft, same=False)
        last = key
        version = 2
        if held == "other-twice":
            last = (key[0], f"{key[1]}:v2")
            record[last] = _standing(draft, same=False)
            version = 3
        payload = {
            **draft["payload"],
            "raw_id": f"{key[1]}:v{version}",
            "supersedes": str(record[last]["id"]),
        }
        expected.append({**draft, "payload": payload})
    asked: list[list[tuple[str, str]]] = []

    def existing(keys):
        keys = list(keys)
        asked.append(keys)
        return {key: record[key] for key in keys if key in record}

    counts: dict[str, int] = {}
    out = list(health_export.corrected([draft for draft, _ in cases], existing, counts))
    assert len(out) == len(cases)
    keys = [(draft["source"], draft["payload"]["raw_id"]) for draft, _ in cases]
    repeated = {key for key in keys if keys.count(key) > 1}  # one lookup per key: a run's repeats are its own
    for got, (draft, _), want in zip(out, cases, expected, strict=True):
        if (draft["source"], draft["payload"]["raw_id"]) in repeated:
            want = None
        assert (got["at"], got["end"], got["source"], got["kind"], got["tier"]) == (
            draft["at"],
            draft["end"],
            draft["source"],
            draft["kind"],
            draft["tier"],
        )
        if want is not None:
            assert got == want
    assert counts.get("corrected", 0) == sum(
        1 for got, (draft, _) in zip(out, cases, strict=True) if got is not draft and got != draft
    )
    assert len(asked) <= 3  # one batched lookup per version round, never one per draft
    lb = Logbook.init(tmp_path_factory.mktemp("lb"), "Europe/Oslo")
    assert lb.append_many(out) == len({(d["source"], d["payload"]["raw_id"]) for d in out})
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == len({(d["source"], d["payload"]["raw_id"]) for d in out})
    validator = Draft202012Validator(SCHEMA)
    for stored in lb.lines():
        validator.validate(stored)


@settings(max_examples=30, deadline=None)
@given(st.lists(_draft, max_size=8))
def test_without_a_record_every_draft_passes_through(drafts):
    counts: dict[str, int] = {}
    assert list(health_export.corrected(drafts, None, counts)) == drafts
    assert counts == {}
