"""`logbook sync --install-schedule` and `--uninstall-schedule`: a launchd agent on macOS, a
systemd user timer on Linux, running `logbook sync --scheduled` (`sync --all`, then `doctor`) at 07:00
and 19:00 local. The plist or unit is printed before it is written; nothing is written outside the
user's LaunchAgents or systemd user directory; the secrets stay in `~/.config/logbook/sync.env`,
which the agent sources and this command never writes. Nothing here talks to launchd or systemd:
the calls are recorded."""

from __future__ import annotations

import json
import plistlib
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import home as record_home
from logbook.contrib import schedule
from logbook.core.store import Logbook

PYTHON = "/opt/logbook/venv/bin/python3"


def _tree(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*")}


# -- the plan ------------------------------------------------------------------------------------------------


def test_the_macos_plan_is_a_launchd_agent_at_7_and_19(tmp_path: Path) -> None:
    home = tmp_path / "home"
    plan = schedule.plan("darwin", home, PYTHON, logbook_home=tmp_path / "Logbook")
    [path] = plan.files
    assert path == home / "Library" / "LaunchAgents" / "org.logbook.sync.plist"
    assert plan.directory == home / "Library" / "LaunchAgents"
    data = plistlib.loads(plan.files[path].encode("utf-8"))
    assert data["Label"] == "org.logbook.sync"
    shell, flag, script = data["ProgramArguments"]
    assert (shell, flag) == ("/bin/sh", "-c")
    assert script.endswith(f"exec {PYTHON} -m logbook.cli sync --scheduled")
    assert '"$HOME/.config/logbook/sync.env"' in script and "set -a" in script, "the secrets are sourced"
    assert data["StartCalendarInterval"] == [{"Hour": 7, "Minute": 0}, {"Hour": 19, "Minute": 0}]
    assert data["EnvironmentVariables"] == {"LOGBOOK_HOME": str(tmp_path / "Logbook")}
    assert data["StandardOutPath"] == str(home / "Library" / "Logs" / "logbook-sync.log")
    assert data["StandardErrorPath"] == data["StandardOutPath"]
    assert data["RunAtLoad"] is False
    assert [c.args[:2] for c in plan.activate] == [("launchctl", "bootout"), ("launchctl", "bootstrap")]
    assert [c.required for c in plan.activate] == [False, True], "unloading what is not loaded is no error"
    assert [c.args[:2] for c in plan.deactivate] == [("launchctl", "bootout")]
    assert all(str(path) in c.args for c in [*plan.activate, *plan.deactivate])


def test_the_linux_plan_is_a_systemd_user_timer_at_7_and_19(tmp_path: Path) -> None:
    home = tmp_path / "home"
    plan = schedule.plan("linux", home, PYTHON, logbook_home=tmp_path / "Logbook")
    unit_dir = home / ".config" / "systemd" / "user"
    assert plan.directory == unit_dir
    assert set(plan.files) == {unit_dir / "logbook-sync.service", unit_dir / "logbook-sync.timer"}
    service = plan.files[unit_dir / "logbook-sync.service"]
    assert f"ExecStart={PYTHON} -m logbook.cli sync --scheduled\n" in service
    assert "EnvironmentFile=-%h/.config/logbook/sync.env\n" in service, "optional: no file, no secrets"
    assert f"Environment=LOGBOOK_HOME={tmp_path / 'Logbook'}\n" in service
    assert "Type=oneshot\n" in service
    timer = plan.files[unit_dir / "logbook-sync.timer"]
    assert "OnCalendar=*-*-* 07,19:00:00\n" in timer and "Persistent=true\n" in timer
    assert "Unit=logbook-sync.service\n" in timer and "WantedBy=timers.target\n" in timer
    assert [c.args for c in plan.activate] == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", "logbook-sync.timer"),
    ]
    assert [c.args for c in plan.deactivate] == [
        ("systemctl", "--user", "disable", "--now", "logbook-sync.timer"),
    ]


def test_the_linux_plan_honours_xdg_config_home(tmp_path: Path) -> None:
    plan = schedule.plan("linux", tmp_path / "home", PYTHON, config_home=tmp_path / "xdg")
    assert plan.directory == tmp_path / "xdg" / "systemd" / "user"
    assert "Environment=LOGBOOK_HOME" not in plan.files[plan.directory / "logbook-sync.service"]


def test_a_path_with_a_space_is_quoted_for_both_schedulers(tmp_path: Path) -> None:
    python = "/Users/kari/My Tools/venv/bin/python3"
    mac = schedule.plan("darwin", tmp_path / "home", python)
    [plist] = mac.files.values()
    script = plistlib.loads(plist.encode("utf-8"))["ProgramArguments"][2]
    assert "exec '/Users/kari/My Tools/venv/bin/python3' -m logbook.cli sync --scheduled" in script
    linux = schedule.plan("linux", tmp_path / "home", python)
    service = linux.files[linux.directory / "logbook-sync.service"]
    assert 'ExecStart="/Users/kari/My Tools/venv/bin/python3" -m logbook.cli sync --scheduled\n' in service


def test_another_platform_has_no_scheduler_here(tmp_path: Path) -> None:
    with pytest.raises(schedule.ScheduleError, match="win32"):
        schedule.plan("win32", tmp_path / "home", PYTHON)


# -- install and uninstall through the CLI -------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A record under the temporary home (conftest points HOME there), the config dir default, and
    a scheduler whose commands are recorded, never run."""
    home = Path.home()
    lb = Logbook.init(home / "Logbook", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(schedule, "system", lambda: "linux")
    return home


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    seen: list[tuple[str, ...]] = []

    def run(args: Any, **_: Any) -> subprocess.CompletedProcess[str]:
        seen.append(tuple(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(schedule.subprocess, "run", run)
    monkeypatch.setattr(schedule.shutil, "which", lambda name: f"/usr/bin/{name}")
    return seen


def test_install_prints_each_unit_writes_it_in_the_systemd_user_dir_only_and_enables_the_timer(
    home: Path, calls: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    before = _tree(home)
    cli.main(["sync", "--install-schedule"])
    out = capsys.readouterr().out
    unit_dir = home / ".config" / "systemd" / "user"
    service, timer = unit_dir / "logbook-sync.service", unit_dir / "logbook-sync.timer"
    for path in (service, timer):
        text = path.read_text(encoding="utf-8")
        assert text in out, "printed before it is written"
        assert out.index(str(path)) < out.index(text)
    added = _tree(home) - before
    assert added == {
        Path(".config"),
        Path(".config/systemd"),
        Path(".config/systemd/user"),
        service.relative_to(home),
        timer.relative_to(home),
        Path("Logbook/state"),
        Path("Logbook/state/home.json"),  # this machine is now the record's home (ADR 0022)
    }, "nothing else under the home directory"
    assert f"Environment=LOGBOOK_HOME={home / 'Logbook'}" in service.read_text(encoding="utf-8")
    assert calls == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", "logbook-sync.timer"),
    ]
    assert "07:00 and 19:00" in out and "sync.env" in out


def test_install_without_the_scheduler_on_path_writes_the_files_and_says_what_to_run(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(schedule.shutil, "which", lambda name: None)
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: pytest.fail("never run"))
    cli.main(["sync", "--install-schedule"])
    out = capsys.readouterr().out
    assert (home / ".config" / "systemd" / "user" / "logbook-sync.timer").exists()
    assert "systemctl not found" in out and "systemctl --user enable --now logbook-sync.timer" in out


def test_install_reports_a_scheduler_that_refuses(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(args: Any, **_: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, 1, "", "Failed to connect to bus")

    monkeypatch.setattr(schedule.subprocess, "run", run)
    monkeypatch.setattr(schedule.shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(SystemExit) as e:
        cli.main(["sync", "--install-schedule"])
    assert e.value.code == 1
    assert "Failed to connect to bus" in capsys.readouterr().err
    timer = home / ".config" / "systemd" / "user" / "logbook-sync.timer"
    assert timer.exists(), "the unit stays for a retry"


def test_uninstall_disables_the_timer_and_removes_only_its_files(
    home: Path, calls: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["sync", "--install-schedule"])
    calls.clear()
    unit_dir = home / ".config" / "systemd" / "user"
    (unit_dir / "other.service").write_text("[Unit]\n", encoding="utf-8")
    capsys.readouterr()
    cli.main(["sync", "--uninstall-schedule"])
    out = capsys.readouterr().out
    assert calls == [("systemctl", "--user", "disable", "--now", "logbook-sync.timer")]
    assert sorted(p.name for p in unit_dir.iterdir()) == ["other.service"]
    assert "removed" in out and "logbook-sync.timer" in out and "logbook-sync.service" in out
    cli.main(["sync", "--uninstall-schedule"])
    assert "no schedule installed" in capsys.readouterr().out


def test_install_on_macos_writes_the_agent_under_launch_agents(
    home: Path,
    calls: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(schedule, "system", lambda: "darwin")
    before = _tree(home)
    cli.main(["sync", "--install-schedule"])
    plist = home / "Library" / "LaunchAgents" / "org.logbook.sync.plist"
    assert _tree(home) - before == {
        Path("Library"),
        Path("Library/LaunchAgents"),
        plist.relative_to(home),
        Path("Logbook/state"),
        Path("Logbook/state/home.json"),  # this machine is now the record's home (ADR 0022)
    }
    data = plistlib.loads(plist.read_bytes())
    assert data["EnvironmentVariables"] == {"LOGBOOK_HOME": str(home / "Logbook")}
    assert [c[:2] for c in calls] == [("launchctl", "bootout"), ("launchctl", "bootstrap")]
    assert all(str(plist) in c for c in calls)
    assert plist.read_text(encoding="utf-8") in capsys.readouterr().out


def test_install_and_uninstall_take_no_source_and_no_other_flag(
    home: Path, calls: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    for args in (
        ["sync", "immich", "--install-schedule"],
        ["sync", "--all", "--install-schedule"],
        ["sync", "--install-schedule", "--uninstall-schedule"],
        ["sync", "--uninstall-schedule", "--dry-run"],
    ):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2, args
        assert "schedule" in capsys.readouterr().err
    assert calls == []


def test_install_on_an_unsupported_platform_exits_2(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(schedule, "system", lambda: "win32")
    with pytest.raises(SystemExit) as e:
        cli.main(["sync", "--install-schedule"])
    assert e.value.code == 2 and "win32" in capsys.readouterr().err


# -- the record's home (ADR 0022) ------------------------------------------------------------------------


def test_install_records_this_machine_as_the_records_home(
    home: Path,
    calls: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(record_home, "hostname", lambda: "nordlys-home")
    monkeypatch.setattr(record_home, "today", lambda: date(2026, 10, 9))
    cli.main(["sync", "--install-schedule"])
    out = capsys.readouterr().out
    path = home / "Logbook" / "state" / "home.json"
    assert json.loads(path.read_text(encoding="utf-8")) == {"host": "nordlys-home", "since": "2026-10-09"}
    assert "nordlys-home" in out and "home" in out
    found = record_home.read(home / "Logbook")
    assert found is not None and found.host == "nordlys-home" and found.since == date(2026, 10, 9)


def test_install_again_on_the_same_machine_keeps_the_date(
    home: Path, calls: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record_home, "hostname", lambda: "nordlys-home")
    monkeypatch.setattr(record_home, "today", lambda: date(2026, 10, 9))
    cli.main(["sync", "--install-schedule"])
    monkeypatch.setattr(record_home, "today", lambda: date(2026, 11, 1))
    cli.main(["sync", "--install-schedule"])
    found = record_home.read(home / "Logbook")
    assert found is not None and found.since == date(2026, 10, 9)


def test_install_on_another_machine_moves_the_home_and_says_so(
    home: Path,
    calls: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(record_home, "hostname", lambda: "laptop-of-ines")
    monkeypatch.setattr(record_home, "today", lambda: date(2026, 10, 9))
    cli.main(["sync", "--install-schedule"])
    capsys.readouterr()
    monkeypatch.setattr(record_home, "hostname", lambda: "nordlys-home")
    monkeypatch.setattr(record_home, "today", lambda: date(2026, 11, 1))
    cli.main(["sync", "--install-schedule"])
    out = capsys.readouterr().out
    assert "laptop-of-ines" in out and "nordlys-home" in out
    found = record_home.read(home / "Logbook")
    assert found is not None and found.host == "nordlys-home" and found.since == date(2026, 11, 1)


def test_uninstall_leaves_the_home_as_it_is(
    home: Path, calls: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record_home, "hostname", lambda: "nordlys-home")
    cli.main(["sync", "--install-schedule"])
    cli.main(["sync", "--uninstall-schedule"])
    assert (home / "Logbook" / "state" / "home.json").exists()


def test_install_writes_over_a_home_file_that_is_not_the_shape(
    home: Path, calls: list[tuple[str, ...]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record_home, "hostname", lambda: "nordlys-home")
    path = home / "Logbook" / "state" / "home.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    cli.main(["sync", "--install-schedule"])
    found = record_home.read(home / "Logbook")
    assert found is not None and found.host == "nordlys-home"
