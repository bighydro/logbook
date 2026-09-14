"""`logbook export --day` / `--days`: the day-package/v1 hand-off directory (ADR 0013 §4)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook.export import write_day_package
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
TZ = "Europe/Oslo"  # UTC+1 in March: 23:30Z on the 1st is 00:30 local on the 2nd


@pytest.fixture
def two_days(tmp_path: Path) -> Logbook:
    """Four lines, two per local day, but three of them share UTC date 2026-03-01."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    lb.append(
        at="2026-03-01T07:30:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.911, "lon": 10.75, "raw_id": "trk:1"},
    )
    lb.append(
        at="2026-03-01T22:00:00Z",
        end="2026-03-01T22:45:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "late dinner"},
    )
    lb.append(  # 00:30 local on 2026-03-02
        at="2026-03-01T23:30:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.92, "lon": 10.74, "raw_id": "trk:2"},
    )
    lb.append(
        at="2026-03-02T08:00:00Z",
        source="sim-calendar",
        kind="event",
        tier=1,
        payload={"schema": "event/v1", "title": "Standup"},
    )
    return lb


def _manifest(d: Path) -> dict:
    return json.loads((d / "package.json").read_text(encoding="utf-8"))


# -- library ----------------------------------------------------------------


def test_day_package_groups_by_local_date(two_days: Logbook, tmp_path: Path):
    out = tmp_path / "pkg"
    write_day_package(two_days, "2026-03-01", out)
    m = _manifest(out)
    assert [e["seq"] for e in m["entries"]] == [1, 2]
    write_day_package(two_days, "2026-03-02", out)
    assert [e["seq"] for e in _manifest(out)["entries"]] == [3, 4]


def test_day_package_manifest_shape(two_days: Logbook, tmp_path: Path):
    out = tmp_path / "pkg"
    write_day_package(two_days, "2026-03-01", out, generated_at="2026-09-14T12:00:00Z")
    m = _manifest(out)
    lines = list(two_days.lines())
    assert m == {
        "schema": "day-package/v1",
        "date": "2026-03-01",
        "tz": TZ,
        "owner_id": two_days.meta["owner_id"],
        "generated_at": "2026-09-14T12:00:00Z",
        "logbook_head": two_days.meta["head"],
        "entries": [
            {
                "id": lines[0]["id"],
                "seq": 1,
                "at": "2026-03-01T07:30:00Z",
                "end": None,
                "kind": "location",
                "tier": 1,
                "source": "sim-phone",
                "raw_id": "trk:1",
                "tags": [],
            },
            {
                "id": lines[1]["id"],
                "seq": 2,
                "at": "2026-03-01T22:00:00Z",
                "end": "2026-03-01T22:45:00Z",
                "kind": "note",
                "tier": 2,
                "source": "manual",
                "raw_id": None,
                "tags": [],
            },
        ],
        "derived": {},
        "attachments": [],
    }


def test_day_package_head_equals_verify(two_days: Logbook, tmp_path: Path):
    write_day_package(two_days, "2026-03-02", tmp_path / "pkg")
    _seq, head, errors = two_days.verify()
    assert errors == []
    assert _manifest(tmp_path / "pkg")["logbook_head"] == head


def test_day_package_rerun_overwrites_identically(two_days: Logbook, tmp_path: Path):
    out = tmp_path / "pkg"
    write_day_package(two_days, "2026-03-01", out, generated_at="2026-09-14T12:00:00Z")
    first = (out / "package.json").read_bytes()
    write_day_package(two_days, "2026-03-01", out, generated_at="2026-09-14T12:00:00Z")
    assert (out / "package.json").read_bytes() == first
    assert sorted(p.name for p in out.iterdir()) == ["package.json"]


def test_day_package_empty_day_has_no_entries(two_days: Logbook, tmp_path: Path):
    write_day_package(two_days, "2026-03-03", tmp_path / "pkg")
    assert _manifest(tmp_path / "pkg")["entries"] == []


def test_day_package_rejects_bad_date(two_days: Logbook, tmp_path: Path):
    with pytest.raises(ValueError):
        write_day_package(two_days, "2026-3-1", tmp_path / "pkg")


# -- CLI --------------------------------------------------------------------


def _run(lb: Logbook, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LOGBOOK_HOME": str(lb.root), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", "export", *args], env=env, capture_output=True, encoding="utf-8"
    )


def test_cli_export_day_default_dir(two_days: Logbook):
    r = _run(two_days, "--day", "2026-03-02")
    assert r.returncode == 0, r.stderr
    d = two_days.root / "export" / "2026-03-02"
    assert [e["seq"] for e in _manifest(d)["entries"]] == [3, 4]
    assert str(d) in r.stdout


def test_cli_export_day_out_dir(two_days: Logbook, tmp_path: Path):
    r = _run(two_days, "--day", "2026-03-01", "--out", str(tmp_path / "elsewhere"))
    assert r.returncode == 0, r.stderr
    assert _manifest(tmp_path / "elsewhere")["date"] == "2026-03-01"
    assert not (two_days.root / "export").exists()


def test_cli_export_days_skips_empty_by_default(two_days: Logbook):
    r = _run(two_days, "--days", "2026-02-28", "2026-03-03")
    assert r.returncode == 0, r.stderr
    made = sorted(p.name for p in (two_days.root / "export").iterdir())
    assert made == ["2026-03-01", "2026-03-02"]


def test_cli_export_days_with_empty_writes_every_day(two_days: Logbook, tmp_path: Path):
    r = _run(two_days, "--days", "2026-02-28", "2026-03-03", "--empty", "--out", str(tmp_path / "o"))
    assert r.returncode == 0, r.stderr
    made = sorted(p.name for p in (tmp_path / "o").iterdir())
    assert made == ["2026-02-28", "2026-03-01", "2026-03-02", "2026-03-03"]
    assert _manifest(tmp_path / "o" / "2026-02-28")["entries"] == []


def test_cli_export_days_rejects_reversed_range(two_days: Logbook):
    r = _run(two_days, "--days", "2026-03-03", "2026-03-01")
    assert r.returncode == 2
    assert r.stdout == ""


def test_cli_export_whole_log_unchanged(two_days: Logbook, tmp_path: Path):
    r = _run(two_days, str(tmp_path / "all.jsonl"))
    assert r.returncode == 0, r.stderr
    assert len((tmp_path / "all.jsonl").read_text(encoding="utf-8").splitlines()) == 4
    assert "exported 4 lines" in r.stdout


def test_cli_export_needs_a_target(two_days: Logbook):
    r = _run(two_days)
    assert r.returncode == 2
