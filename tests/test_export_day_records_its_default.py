"""`export --day` with no `folder` entry records what is true (the owner's desk's review of #429): no
entry exists, and the default tier 1 applied, never `max_tier 1` as if a policy had set it. An entry is
recorded by name with its ceiling. Doctor's `export-day` line says the same. Synthetic lines."""

from __future__ import annotations

from pathlib import Path

import pytest
import test_export_day_crossing as crossing_day
from test_export_day_crossing import DAY, _crossings, _export, _policy

from logbook.contrib import doctor
from logbook.core import policy
from logbook.core.store import Logbook

lb = crossing_day.lb


def test_no_folder_entry_is_recorded_as_none_and_the_default_tier(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _export(capsys, "--day", DAY, "--out", str(tmp_path / "For Kari"))
    [line] = _crossings(lb)
    said = line["payload"]["policy"]
    assert said == {"file": policy.POLICY_FILE.as_posix(), "entry": None, "default_tier": 1}, said
    assert "max_tier" not in said, "no ceiling a policy did not set"


def test_a_folder_entry_is_recorded_by_name_with_its_ceiling(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _policy(lb, {"mcp": {"max_tier": 1}, "folder": {"max_tier": 2}})
    _export(capsys, "--days", DAY, "2026-03-03", "--out", str(tmp_path / "Week"))
    [line] = _crossings(lb)
    said = line["payload"]["policy"]
    assert said == {"file": policy.POLICY_FILE.as_posix(), "entry": "folder", "max_tier": 2}, said


def test_the_refusal_without_an_entry_says_no_entry_and_the_default(
    lb: Logbook, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit):
        _export(capsys, "--day", DAY, "--out", str(tmp_path / "x"), "--tier", "1,2")
    err = capsys.readouterr().err
    assert "names no 'folder' entry" in err and "default" in err, err
    assert "allows max_tier 1" not in err, "the file allows nothing it does not name"


def test_doctor_says_no_entry_and_the_default_tier(lb: Logbook) -> None:
    check = doctor.export_day_check(lb.root)
    assert check.name == "export-day" and check.status == "pass"
    assert "names no folder entry" in check.detail and "default tier 1" in check.detail, check.detail
    assert '{"folder": {"max_tier": 2}}' in check.detail
    assert "export-day" in {c.name for c in doctor.run(Logbook(lb.root), {}, installed=lambda _m: True)}
    _policy(lb, {"mcp": {"max_tier": 1}, "folder": {"max_tier": 2}})
    named = doctor.export_day_check(lb.root)
    assert named.status == "pass" and "up to 2" in named.detail and "folder entry" in named.detail
    assert "default" not in named.detail


def test_doctor_warns_when_the_folder_entry_has_expired(lb: Logbook) -> None:
    """The blind review: an entry past its `until` counts as tier 0, so no folder is written; the line
    says so as a warn, never a pass that reads "tiers up to 0"."""
    _policy(lb, {"mcp": {"max_tier": 1}, "folder": {"max_tier": 2, "until": "2020-01-01"}})
    check = doctor.export_day_check(lb.root)
    assert check.status == "warn" and "expired on 2020-01-01" in check.detail, check.detail
    assert "up to 0" not in check.detail
