"""SPEC §2: `at`, `end` and `recorded_at` are RFC 3339 instants. `append` refuses a stamp that is
not one, whatever it ends in, and `verify` reports one a line already carries as an error naming the
line; a valid stamp is kept as it was written, since the string is hashed verbatim. The bad lines are
built by hand, never through `append`, which cannot write one."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from logbook.core.chain import GENESIS, compute_hash, is_instant
from logbook.core.store import Logbook

ROOT = Path(__file__).resolve().parents[1]

VALID = [
    "2026-03-01T07:30:00Z",
    "2026-03-01T07:30:00.000Z",  # the same instant as the one above, a different string: both stand
    "2026-03-01T07:30:00.123456789Z",  # any number of fraction digits
    "2028-02-29T23:59:59Z",  # a leap day
    "2026-03-01T08:30:00+01:00",  # an instant; not SPEC §2's spelling, which `verify` warns about
    "2026-03-01T07:30:00-00:00",
    "2026-03-01t07:30:00z",  # RFC 3339 §5.6 allows the lower case
]

MALFORMED = [
    "not-a-dateZ",
    "Z",
    "",
    "2026-03-01Z",  # a date, no time
    "2026-03-01T07:30Z",  # no seconds
    "2026-03-01 07:30:00Z",  # a space for the T
    "2026-03-01T07:30:00",  # no zone
    "2026-02-30T07:30:00Z",  # no such day
    "2027-02-29T07:30:00Z",  # not a leap year
    "2026-13-01T07:30:00Z",
    "2026-03-01T24:00:00Z",
    "2026-03-01T07:60:00Z",
    "2026-12-31T23:59:60Z",  # a leap second: no reader here can place it
    "0000-01-01T00:00:00Z",  # year 0000: the same
    "2026-03-01T07:30:00.Z",  # a point with no digits
    "2026-03-01T07:30:00+24:00",
    "2026-03-01T07:30:00+0100",  # RFC 3339 wants the colon
    "2026-03-01T07:30:00Z\n",
    " 2026-03-01T07:30:00Z",
    "\uff12\uff10\uff12\uff16-03-01T07:30:00Z",  # digits, but not ASCII ones (full-width)
    "20260301T073000Z",  # ISO 8601 basic format, not RFC 3339
]


@pytest.mark.parametrize("stamp", VALID)
def test_an_rfc_3339_instant_is_one(stamp: str):
    assert is_instant(stamp)


@pytest.mark.parametrize("stamp", [*MALFORMED, None, 1772350200, ["2026-03-01T07:30:00Z"]])
def test_anything_else_is_not(stamp: object):
    assert not is_instant(stamp)


# -- append ---------------------------------------------------------------------------------------


def _draft(**fields: object) -> dict[str, Any]:
    draft: dict[str, Any] = {
        "at": "2026-03-01T07:30:00Z",
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": "Ferry to Nesodden."},
    }
    draft.update(fields)
    return draft


@pytest.mark.parametrize("field", ["at", "end", "recorded_at"])
@pytest.mark.parametrize("stamp", ["not-a-dateZ", "2026-02-30T07:30:00Z", "2026-03-01T07:30Z"])
def test_append_refuses_a_stamp_that_is_not_an_instant(tmp_path: Path, field: str, stamp: str):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    with pytest.raises(ValueError, match="RFC 3339") as refused:
        lb.append(**_draft(**{field: stamp}))
    assert repr(stamp) in str(refused.value)
    assert lb.files() == [] and lb.verify() == (0, GENESIS, [])


def test_append_many_refuses_it_too_and_writes_nothing(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    with pytest.raises(ValueError, match="'not-a-dateZ' is not an RFC 3339 instant"):
        lb.append_many([_draft(), _draft(at="not-a-dateZ")])
    assert lb.files() == [] and lb.verify() == (0, GENESIS, [])


@pytest.mark.parametrize("stamp", [s for s in VALID if s.endswith("Z")])
def test_a_valid_z_stamp_is_written_as_it_was_given(tmp_path: Path, stamp: str):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    line = lb.append(**_draft(at=stamp, end=stamp, recorded_at=stamp))
    assert (line["at"], line["end"], line["recorded_at"]) == (stamp, stamp, stamp)
    assert lb.verify() == (1, line["hash"], [])


def test_a_numeric_offset_is_still_converted(tmp_path: Path):
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    assert lb.append(**_draft(at="2026-03-01T08:30:00.5+01:00"))["at"] == "2026-03-01T07:30:00.5Z"


# -- verify ---------------------------------------------------------------------------------------


def _hand_line(seq: int, prev: str, **fields: object) -> dict[str, Any]:
    line: dict[str, Any] = {
        "id": f"01900000-0000-7000-8000-00000000000{seq}",
        "seq": seq,
        "at": "2026-03-01T07:30:00Z",
        "end": None,
        "tz": "Europe/Oslo",
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": "by hand"},
        "recorded_at": "2026-03-01T07:31:00Z",
        "prev": prev,
    }
    line.update(fields)
    line["hash"] = compute_hash(line)  # correctly hashed: only the stamp is wrong
    return line


def _by_hand(root: Path, *changes: dict[str, object]) -> Logbook:
    """A record of one line per entry of `changes`, chained and hashed, built without `append`."""
    lb = Logbook.init(root, "Europe/Oslo")
    lines, prev = [], GENESIS
    for seq, fields in enumerate(changes, 1):
        lines.append(_hand_line(seq, prev, **fields))
        prev = lines[-1]["hash"]
    month = root / "logbook" / "2026" / "03.jsonl"
    month.parent.mkdir(parents=True)
    month.write_bytes(b"".join(json.dumps(line).encode("utf-8") + b"\n" for line in lines))
    meta = lb.meta
    meta["seq"], meta["head"] = len(lines), prev
    (root / "logbook.json").write_bytes(json.dumps(meta).encode("utf-8"))
    return lb


def test_verify_reports_a_malformed_at_as_an_error_naming_the_line(tmp_path: Path):
    lb = _by_hand(tmp_path / "lb", {}, {"at": "not-a-dateZ"}, {})
    warnings: list[str] = []
    seq, _head, errors = lb.verify(warnings)
    assert seq == 3
    assert errors == ["line 2: at 'not-a-dateZ' is not an RFC 3339 instant (SPEC §2)"]
    assert warnings == []  # an error, not the warning a numeric offset gets


@pytest.mark.parametrize("field", ["end", "recorded_at"])
def test_verify_checks_end_and_recorded_at_too(tmp_path: Path, field: str):
    lb = _by_hand(tmp_path / "lb", {field: "2026-02-30T07:30:00Z"})
    assert lb.verify()[2] == [f"line 1: {field} '2026-02-30T07:30:00Z' is not an RFC 3339 instant (SPEC §2)"]


@pytest.mark.parametrize("field, value", [("at", None), ("recorded_at", None), ("end", 1772350200)])
def test_verify_refuses_a_stamp_that_is_not_a_string(tmp_path: Path, field: str, value: object):
    lb = _by_hand(tmp_path / "lb", {field: value})
    (error,) = lb.verify()[2]
    assert error.startswith(f"line 1: {field} ") and "is not an RFC 3339 instant" in error


def test_verify_accepts_every_valid_stamp_as_it_was_written(tmp_path: Path):
    lb = _by_hand(tmp_path / "lb", *({"at": s, "end": s, "recorded_at": s} for s in VALID))
    before = {f: f.read_bytes() for f in lb.files()}
    warnings: list[str] = []
    seq, _head, errors = lb.verify(warnings)
    assert (seq, errors) == (len(VALID), [])
    assert {f: f.read_bytes() for f in lb.files()} == before  # nothing respelled
    not_z = [s for s in VALID if not s.endswith("Z")]
    assert len(warnings) == 3 * len(not_z)  # the numeric offsets and the lower-case z, as before


def test_cli_verify_exits_1_and_names_the_line(tmp_path: Path):
    _by_hand(tmp_path / "lb", {}, {"at": "not-a-dateZ"})
    r = subprocess.run(
        [sys.executable, "-m", "logbook.cli", "verify", "--root", str(tmp_path / "lb")],
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        encoding="utf-8",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "INVALID — 1 problem(s); 2 lines read" in r.stdout
    assert "line 2: at 'not-a-dateZ' is not an RFC 3339 instant (SPEC §2)" in r.stdout
