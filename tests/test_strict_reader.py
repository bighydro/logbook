"""Issue #47: the reference implementation must be as strict as SPEC §2 and §3 after #46.

Every bad line here is built by hand, never through `append`, because `append` cannot produce one."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from logbook.chain import GENESIS, compute_hash
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]


def _events_of(monkeypatch: pytest.MonkeyPatch, lb: Logbook) -> list[str]:
    """Record, in order, every fsync of a month file and every save of logbook.json."""
    events: list[str] = []
    real_fsync, real_save = os.fsync, Logbook._save_meta

    def fsync(fd: int) -> None:
        real_fsync(fd)
        st = os.fstat(fd)
        for month in lb.files():
            if os.stat(month).st_ino == st.st_ino and os.stat(month).st_dev == st.st_dev:
                events.append(f"fsync {lb._relative(month)}")

    def save(self: Logbook, meta: dict[str, object]) -> None:
        real_save(self, meta)
        events.append("save logbook.json")

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(Logbook, "_save_meta", save)
    return events


def _draft(at: str) -> dict[str, object]:
    return {"at": at, "source": "manual", "kind": "note", "tier": 2, "payload": {"schema": "note/v1"}}


# -- fsync before the meta save (SPEC §3, write order) ---------------------------------------


def test_append_fsyncs_the_month_file_before_saving_meta(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    events = _events_of(monkeypatch, lb)
    lb.append(**_draft("2026-03-01T07:30:00Z"))
    assert events == ["fsync logbook/2026/03.jsonl", "save logbook.json"]


def test_append_many_fsyncs_every_month_file_before_saving_meta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    events = _events_of(monkeypatch, lb)
    lb.append_many([_draft("2026-03-01T07:30:00Z"), _draft("2026-04-01T07:30:00Z")])
    assert events == ["fsync logbook/2026/03.jsonl", "fsync logbook/2026/04.jsonl", "save logbook.json"]


# -- lines built by hand ----------------------------------------------------------------------


def _hand_line(**overrides: object) -> dict[str, Any]:
    """A complete, correctly hashed line, built without `append`; `overrides` change fields
    before hashing, and a field set to MISSING is left out after hashing."""
    line: dict[str, Any] = {
        "id": "01900000-0000-7000-8000-000000000001",
        "seq": 1,
        "at": "2026-03-01T07:30:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": "by hand"},
        "recorded_at": "2026-03-01T07:31:00Z",
        "prev": GENESIS,
    }
    line.update({k: v for k, v in overrides.items() if v is not MISSING})
    line["hash"] = compute_hash(line)  # over the defaults, so dropping `end` still recomputes
    return {k: v for k, v in line.items() if overrides.get(k) is not MISSING}


MISSING = object()


def _write_by_hand(root: Path, *texts: str) -> Logbook:
    """A logbook whose only month file holds exactly `texts`, one per line, with logbook.json
    pointing at the last of them."""
    lb = Logbook.init(root, "Europe/Oslo")
    month = root / "logbook" / "2026" / "03.jsonl"
    month.parent.mkdir(parents=True)
    month.write_text("".join(t + "\n" for t in texts), encoding="utf-8")
    last = json.loads(texts[-1])
    meta = json.loads((root / "logbook.json").read_text(encoding="utf-8"))
    meta["seq"], meta["head"] = last.get("seq", len(texts)), last.get("hash", GENESIS)
    (root / "logbook.json").write_text(json.dumps(meta), encoding="utf-8")
    return lb


# -- duplicate JSON keys are invalid (SPEC §2) -------------------------------------------------


def test_duplicate_key_in_a_line_makes_verify_report_invalid(tmp_path: Path):
    text = json.dumps(_hand_line())
    duplicated = text[:-1] + ', "tier": 2}'  # the same key twice, same value: json.loads would not notice
    lb = _write_by_hand(tmp_path / "lb", duplicated)
    _seq, _head, errors = lb.verify()
    assert len(errors) == 1
    assert "duplicate key" in errors[0] and "tier" in errors[0] and "03.jsonl" in errors[0]


def test_duplicate_key_nested_in_payload_is_invalid_too(tmp_path: Path):
    line = _hand_line()
    text = json.dumps(line).replace('"text": "by hand"', '"text": "by hand", "text": "by hand"')
    assert text != json.dumps(line)
    lb = _write_by_hand(tmp_path / "lb", text)
    _seq, _head, errors = lb.verify()
    assert len(errors) == 1 and "duplicate key" in errors[0] and "text" in errors[0]


def test_reader_refuses_a_line_with_a_duplicate_key(tmp_path: Path):
    text = json.dumps(_hand_line())
    lb = _write_by_hand(tmp_path / "lb", text[:-1] + ', "tier": 2}')
    with pytest.raises(ValueError, match="duplicate key"):
        list(lb.lines())


# -- every envelope field is present; `end` is null, never absent (SPEC §2) --------------------

ENVELOPE = (
    "id",
    "seq",
    "at",
    "end",
    "tz",
    "source",
    "kind",
    "tier",
    "payload",
    "recorded_at",
    "prev",
    "hash",
)


def test_line_without_end_is_invalid_even_though_its_hash_recomputes(tmp_path: Path):
    line = _hand_line(end=MISSING)
    assert "end" not in line and compute_hash(line) == line["hash"]  # absent hashes like null today
    lb = _write_by_hand(tmp_path / "lb", json.dumps(line))
    _seq, _head, errors = lb.verify()
    assert errors == ["line 1: end is missing"]


@pytest.mark.parametrize("field", ENVELOPE)
def test_verify_names_any_missing_envelope_field(tmp_path: Path, field: str):
    lb = _write_by_hand(tmp_path / "lb", json.dumps(_hand_line(**{field: MISSING})))
    _seq, _head, errors = lb.verify()
    assert f"line 1: {field} is missing" in errors


def test_schema_requires_end_and_allows_null():
    schema = json.loads((ROOT / "schema" / "observation.schema.json").read_text(encoding="utf-8"))
    assert "end" in schema["required"]
    assert set(schema["required"]) == set(ENVELOPE)
    assert schema["properties"]["end"]["type"] == ["string", "null"]
    jsonschema.validate(_hand_line(), schema)  # a hand-built line with `end: null` conforms
    with pytest.raises(jsonschema.ValidationError, match="'end' is a required property"):
        jsonschema.validate(_hand_line(end=MISSING), schema)


# -- timestamps: UTC with a literal Z (SPEC §2) -----------------------------------------------


def test_append_normalises_offsets_to_utc_with_z(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    line = lb.append(
        at="2026-03-01T08:30:00+01:00",
        end="2026-03-01T09:30:00.25+01:00",
        recorded_at="2026-03-01T04:31:00-03:00",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1"},
    )
    assert (line["at"], line["end"], line["recorded_at"]) == (
        "2026-03-01T07:30:00Z",
        "2026-03-01T08:30:00.25Z",  # the fraction is kept as written; it is hashed verbatim
        "2026-03-01T07:31:00Z",
    )
    assert lb.files() == [tmp_path / "lb" / "logbook" / "2026" / "03.jsonl"]
    assert lb.verify() == (1, line["hash"], [])


def test_append_files_the_line_by_its_utc_month(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    line = lb.append(**_draft("2026-04-01T00:30:00+02:00"))  # 31 March in UTC
    assert line["at"] == "2026-03-31T22:30:00Z"
    assert lb.files() == [tmp_path / "lb" / "logbook" / "2026" / "03.jsonl"]


def test_append_many_normalises_at_to_utc_with_z(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    lb.append_many([_draft("2026-04-01T00:30:00+02:00")])  # 31 March in UTC: lands in the March file
    (line,) = lb.lines()
    assert line["at"] == "2026-03-31T22:30:00Z"
    assert lb.files() == [tmp_path / "lb" / "logbook" / "2026" / "03.jsonl"]


def test_a_z_timestamp_is_written_verbatim(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    line = lb.append(**_draft("2026-03-01T07:30:00.000Z"))
    assert line["at"] == "2026-03-01T07:30:00.000Z"


@pytest.mark.parametrize("bad", ["2026-03-01T07:30:00", "2026-03-01 07:30", "yesterday"])
def test_a_timestamp_without_a_zone_is_refused(tmp_path: Path, bad: str):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    with pytest.raises(ValueError, match="UTC"):
        lb.append(**_draft(bad))
    assert lb.verify() == (0, GENESIS, [])


def test_verify_warns_about_a_numeric_offset_but_stays_valid(tmp_path: Path):
    lb = _write_by_hand(tmp_path / "lb", json.dumps(_hand_line(at="2026-03-01T08:30:00+01:00")))
    warnings: list[str] = []
    seq, _head, errors = lb.verify(warnings=warnings)
    assert (seq, errors) == (1, [])
    assert len(warnings) == 1
    assert "line 1: at '2026-03-01T08:30:00+01:00'" in warnings[0]
    assert "Z" in warnings[0] and "warning in this release" in warnings[0]


def test_verify_warns_about_end_and_recorded_at_too(tmp_path: Path):
    lb = _write_by_hand(
        tmp_path / "lb",
        json.dumps(_hand_line(end="2026-03-01T08:00:00+00:00", recorded_at="2026-03-01T07:31:00+00:00")),
    )
    warnings: list[str] = []
    assert lb.verify(warnings=warnings)[2] == []
    assert [w.split("'")[0] for w in warnings] == ["line 1: end ", "line 1: recorded_at "]


def test_cli_verify_prints_the_warning_and_exits_zero(tmp_path: Path):
    _write_by_hand(tmp_path / "lb", json.dumps(_hand_line(at="2026-03-01T08:30:00+01:00")))
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    r = subprocess.run(
        [sys.executable, "-m", "logbook.cli", "verify", "--root", str(tmp_path / "lb")],
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert r.returncode == 0, r.stderr
    assert "valid — 1 lines" in r.stdout
    assert "WARNING" in r.stdout and "+01:00" in r.stdout and "warning in this release" in r.stdout
