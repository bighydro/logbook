"""`logbook retract <seq> "<reason>"`: a correction is a new line (SPEC §3, payload.supersedes).
Nothing is rewritten; show hides the retracted line, export keeps it and points at the retraction."""

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


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    lb.append(
        at="2026-03-01T07:30:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.911, "lon": 10.75, "raw_id": "trk:1"},
    )
    lb.append(
        at="2026-03-01T12:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "lunch at the wrong cafe"},
    )
    lb.append(
        at="2026-03-01T18:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "walk home"},
    )
    return lb


def _run(lb: Logbook, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "LOGBOOK_HOME": str(lb.root), "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", *args], env=env, capture_output=True, encoding="utf-8"
    )


# -- library ----------------------------------------------------------------


def test_retract_appends_a_retraction_line(lb: Logbook):
    target = list(lb.lines())[1]
    line = lb.retract(2, "wrong cafe", at="2026-03-02T09:00:00Z")
    assert line["seq"] == 4
    assert (line["source"], line["kind"], line["tier"]) == ("manual", "retraction", 2)
    assert line["payload"] == {
        "schema": "retraction/v1",
        "supersedes": target["id"],
        "seq": 2,
        "reason": "wrong cafe",
    }
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 4
    assert [row["seq"] for row in lb.lines()] == [1, 2, 3, 4]  # nothing removed


def test_retract_refuses_a_seq_that_does_not_exist(lb: Logbook):
    with pytest.raises(ValueError, match="99"):
        lb.retract(99, "nothing there")
    assert lb.meta["seq"] == 3


def test_retract_refuses_to_retract_a_retraction(lb: Logbook):
    lb.retract(2, "wrong cafe")
    with pytest.raises(ValueError, match="4"):
        lb.retract(4, "changed my mind")
    assert lb.meta["seq"] == 4


# -- CLI --------------------------------------------------------------------


def test_cli_retract_writes_the_line(lb: Logbook):
    r = _run(lb, "retract", "2", "wrong cafe")
    assert r.returncode == 0, r.stderr
    assert "#4" in r.stdout and "#2" in r.stdout and "wrong cafe" in r.stdout
    last = list(lb.lines())[-1]
    assert last["kind"] == "retraction" and last["payload"]["seq"] == 2


@pytest.mark.parametrize("seq", ["99", "0"])
def test_cli_retract_refuses_missing_seq_with_exit_2(lb: Logbook, seq: str):
    r = _run(lb, "retract", seq, "nothing there")
    assert r.returncode == 2
    assert r.stdout == "" and len(r.stderr.splitlines()) == 1
    assert lb.meta["seq"] == 3


def test_cli_retract_refuses_a_retraction_with_exit_2(lb: Logbook):
    lb.retract(2, "wrong cafe")
    r = _run(lb, "retract", "4", "changed my mind")
    assert r.returncode == 2
    assert lb.meta["seq"] == 4


def test_cli_show_hides_the_retracted_line_and_prints_a_marker(lb: Logbook):
    lb.retract(2, "wrong cafe", at="2026-03-02T09:00:00Z")
    r = _run(lb, "show", "2026-03-01")
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "wrong cafe" in out and "retracted #2: wrong cafe" in out
    assert "lunch at the wrong cafe" not in out
    assert "walk home" in out and "location" in out
    assert out.count("retracted #2") == 1


def test_cli_show_does_not_list_a_retraction_as_a_line_of_its_own_day(lb: Logbook):
    lb.retract(2, "wrong cafe", at="2026-03-02T09:00:00Z")
    r = _run(lb, "show", "2026-03-02")
    assert r.returncode == 0, r.stderr
    assert "retraction" not in r.stdout


# -- export --day -----------------------------------------------------------


def test_day_package_keeps_both_lines_and_marks_the_retracted_entry(lb: Logbook, tmp_path: Path):
    retraction = lb.retract(2, "wrong cafe", at="2026-03-01T20:00:00Z")
    write_day_package(lb, "2026-03-01", tmp_path / "pkg")
    m = json.loads((tmp_path / "pkg" / "package.json").read_text(encoding="utf-8"))
    by_seq = {e["seq"]: e for e in m["entries"]}
    assert sorted(by_seq) == [1, 2, 3, 4]
    assert by_seq[2]["retracted_by"] == retraction["id"]
    assert by_seq[4]["kind"] == "retraction"
    assert "retracted_by" not in by_seq[1] and "retracted_by" not in by_seq[3]
    assert "retracted_by" not in by_seq[4]
