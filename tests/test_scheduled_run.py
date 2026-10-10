"""`logbook sync --scheduled`: what the schedule runs — `sync --all`, then `doctor`, the outcome
written to `state/last-run.json` (when, the lines per source, the doctor counts, the first failing
line), the restore test on the first Sunday of the month, and one message when something is wrong
or on Sunday evening. Fake live sources, nothing real; synthetic notes only; the scheduler is never
touched and no connection is opened."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from test_sync_all import Fake, _fakes

from logbook import cli
from logbook.contrib import backup, doctor, last_run, notify, schedule
from logbook.core.store import Logbook

NOW = datetime(2026, 10, 8, 17, 0, 12, tzinfo=UTC)  # a Thursday, 19:00 in Oslo
SUNDAY_EVENING = datetime(2026, 10, 11, 17, 0, 12, tzinfo=UTC)  # 19:00 in Oslo
SUNDAY_MORNING = datetime(2026, 10, 11, 5, 0, 12, tzinfo=UTC)  # 07:00 in Oslo
FIRST_SUNDAY = datetime(2026, 10, 4, 5, 0, 12, tzinfo=UTC)
OWNER = {"names": ["Ines Nordmann"], "emails": ["ines.nordmann@example.org"], "phones": []}


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "owner.json").write_text(json.dumps(OWNER), encoding="utf-8")
    (lb.root / "places.json").write_text(
        json.dumps({"Home": {"lat": 59.9139, "lon": 10.7522, "radius_m": 120, "kind": "home"}}),
        encoding="utf-8",
    )
    for name in ("LOGBOOK_ALPHA_KEY", "LOGBOOK_GAMMA_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name in notify.ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(doctor, "EXTRAS", ())  # what this machine has installed is not the test's
    monkeypatch.setattr(doctor, "DISK_WARN_BYTES", 0)
    return lb


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """`last_run.now()` reads the first stamp of this list; a test sets it."""
    stamps = [NOW]
    monkeypatch.setattr(last_run, "now", lambda: stamps[0])
    return stamps


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> tuple[Fake, Fake, Fake]:
    """alpha pulls two lines, gamma fails, beta is not configured."""
    alpha = Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=2)
    beta = Fake("beta", ("LOGBOOK_BETA_KEY",), drafts=1)
    gamma = Fake("gamma", ("LOGBOOK_GAMMA_KEY",), fail=OSError("the service is down"))
    _fakes(monkeypatch, alpha, beta, gamma)
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")
    monkeypatch.setenv("LOGBOOK_GAMMA_KEY", "k")
    monkeypatch.delenv("LOGBOOK_BETA_KEY", raising=False)
    return alpha, beta, gamma


def _scheduled(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(["sync", "--scheduled", *args])
    except SystemExit as e:
        status = int(e.code or 0)
    else:
        status = 0
    out = capsys.readouterr()
    return status, out.out, out.err


def _last_run(lb: Logbook) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((lb.root / "state" / "last-run.json").read_text(encoding="utf-8"))
    return data


def _backed_up(lb: Logbook, dest: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb.append("2026-10-01T10:00:00Z", "manual", "note", 2, {"schema": "note/v1", "text": "a synthetic note"})
    monkeypatch.setattr(backup, "now", lambda: datetime(2026, 10, 3, 3, 0, tzinfo=UTC))
    cli.main(["backup", str(dest)])


# -- the run ---------------------------------------------------------------------------------------------


def test_the_scheduled_run_syncs_every_source_then_runs_doctor_and_writes_the_outcome(
    lb: Logbook,
    sources: tuple[Fake, Fake, Fake],
    clock: list[datetime],
    capsys: pytest.CaptureFixture[str],
) -> None:
    status, out, err = _scheduled(capsys)
    assert status == 1, "a source failed"
    assert "alpha: 2 new lines of 2 seen" in out
    assert "sync: gamma: the service is down" in err
    assert out.index("sync --all: 3 sources: 1 ok, 1 failed, 1 skipped") < out.index("pass  record")
    assert "checks:" in out, "doctor ran after the sync"
    data = _last_run(lb)
    assert data["at"] == "2026-10-08T17:00:12Z"
    assert data["sources"] == {
        "alpha": {"result": "ok", "lines": 2},
        "beta": {"result": "skipped (LOGBOOK_BETA_KEY not set)", "lines": 0},
        "gamma": {"result": "failed (status 1)", "lines": 0},
    }
    assert data["doctor"]["fail"] == 0 and data["doctor"]["pass"] >= 5
    assert "restore-test" in data["doctor"]["warned"], "no restore test has passed yet"
    assert set(data["doctor"]) == {"pass", "warn", "fail", "warned", "failed"}
    assert data["first_failing"] == "gamma  failed (status 1)"
    assert data["clean"] is False
    assert data["week"] == [{"at": "2026-10-08T17:00:12Z", "clean": False, "lines": {"alpha": 2}}]
    assert "state/last-run.json" in out


def test_a_clean_run_is_clean_and_exits_0(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    capsys: pytest.CaptureFixture[str],
) -> None:
    alpha = Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=1)
    _fakes(monkeypatch, alpha)
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")
    _backed_up(lb, tmp_path / "Backups", monkeypatch)
    cli.main(["backup", "--restore-test"])  # a restore test that passed: nothing left to warn about
    capsys.readouterr()
    status, _out, _err = _scheduled(capsys)
    assert status == 0
    data = _last_run(lb)
    assert data["clean"] is True and data["first_failing"] is None
    assert data["doctor"]["warn"] == 0 and data["doctor"]["fail"] == 0


def test_a_doctor_warning_is_the_first_failing_line_when_every_source_was_fine(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    _fakes(monkeypatch, Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=1))
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")
    (lb.root / "places.json").unlink()
    status, _out, _err = _scheduled(capsys)
    assert status == 0, "a warn is not a failure of the run"
    data = _last_run(lb)
    assert data["clean"] is False
    assert data["first_failing"].startswith("warn  places  no places.json")
    assert data["doctor"]["warned"] == ["places", "restore-test"]


def test_the_week_keeps_seven_days_of_runs(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    alpha = Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=1)
    _fakes(monkeypatch, alpha)
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")
    clock[0] = datetime(2026, 9, 30, 17, 0, tzinfo=UTC)
    _scheduled(capsys)
    clock[0] = datetime(2026, 10, 2, 17, 0, tzinfo=UTC)
    _scheduled(capsys)
    clock[0] = NOW
    _scheduled(capsys)
    week = _last_run(lb)["week"]
    assert [entry["at"] for entry in week] == ["2026-10-02T17:00:00Z", "2026-10-08T17:00:12Z"]
    assert [entry["lines"] for entry in week] == [{}, {}], (
        "the first run took the line; the record refuses it after"
    )


def test_scheduled_takes_no_source_and_no_other_flag(
    lb: Logbook, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    for args in (
        ["sync", "alpha", "--scheduled"],
        ["sync", "--all", "--scheduled"],
        ["sync", "--scheduled", "--dry-run"],
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2, args
        assert "--scheduled" in capsys.readouterr().err
    assert not (lb.root / "state" / "last-run.json").exists()


def test_the_schedule_runs_the_scheduled_run(tmp_path: Path) -> None:
    plan = schedule.plan("linux", tmp_path / "home", "/opt/py", logbook_home=tmp_path / "lb")
    [service] = [text for path, text in plan.files.items() if path.suffix == ".service"]
    assert "ExecStart=/opt/py -m logbook.cli sync --scheduled\n" in service
    plan = schedule.plan("darwin", tmp_path / "home", "/opt/py")
    [text] = plan.files.values()
    assert "-m logbook.cli sync --scheduled" in text and "sync --all" not in text


# -- the restore test on the first Sunday ----------------------------------------------------------------


def test_the_first_sunday_of_the_month_runs_the_restore_test_once(
    lb: Logbook,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    clock: list[datetime],
    capsys: pytest.CaptureFixture[str],
) -> None:
    _fakes(monkeypatch, Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=1))
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")
    _backed_up(lb, tmp_path / "Backups", monkeypatch)
    capsys.readouterr()
    clock[0] = FIRST_SUNDAY
    status, out, _err = _scheduled(capsys)
    assert status == 0
    assert "restore test: 2026-10-03T030000Z" in out and "passed" in out
    test = json.loads((lb.root / "state" / "last-restore-test.json").read_text(encoding="utf-8"))
    assert test["status"] == "passed" and test["at"] == "2026-10-04T05:00:12Z"
    assert "pass  restore-test" in out, "doctor saw the fresh result"
    clock[0] = datetime(2026, 10, 4, 17, 0, tzinfo=UTC)  # the evening run of the same Sunday
    _status, out, _err = _scheduled(capsys)
    assert "restore test:" not in out, "once a day"
    assert (
        json.loads((lb.root / "state" / "last-restore-test.json").read_text(encoding="utf-8"))["at"]
        == test["at"]
    )
    clock[0] = SUNDAY_EVENING  # the second Sunday
    _status, out, _err = _scheduled(capsys)
    assert "restore test:" not in out


def test_without_a_backup_the_first_sunday_records_a_skip_that_says_what_to_do(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, clock: list[datetime], capsys: pytest.CaptureFixture[str]
) -> None:
    _fakes(monkeypatch, Fake("alpha", ("LOGBOOK_ALPHA_KEY",), drafts=1))
    monkeypatch.setenv("LOGBOOK_ALPHA_KEY", "k")
    clock[0] = FIRST_SUNDAY
    status, out, _err = _scheduled(capsys)
    assert status == 0, "no backup to test is a warn, not a failed run"
    test = json.loads((lb.root / "state" / "last-restore-test.json").read_text(encoding="utf-8"))
    assert test["status"] == "skipped" and "logbook backup DEST" in test["reason"]
    assert "warn  restore-test" in out and "logbook backup DEST" in out
