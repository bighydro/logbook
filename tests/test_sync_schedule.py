"""`logbook sync --install-schedule` and `--uninstall-schedule`: four runs a day, 00:00, 06:00, 12:00 and
18:00 local — `logbook sync --scheduled` (`sync --all`, then `doctor`) at three of them and `sync
--scheduled --close` at 06:00, the run that closes the day (RFC 0036) — as two launchd agents on macOS
or two systemd user timers on Linux, or with `--system` as daemons or system units written to the home
directory with the two sudo commands that install them printed. The plist or unit is printed before it
is written; nothing is written outside the user's LaunchAgents or systemd user directory (or the home
directory, for `--system`); the secrets stay in `~/.config/logbook/sync.env`, which the agent sources
and this command never writes. An install of the two-run schedule moves to the four runs when it is
installed again. Nothing here talks to launchd or systemd: the calls are recorded. The account is the
Oslo persona's, who does not exist."""

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


def test_the_macos_plan_is_two_launchd_agents_at_the_four_times(tmp_path: Path) -> None:
    home = tmp_path / "home"
    plan = schedule.plan("darwin", home, PYTHON, logbook_home=tmp_path / "Logbook")
    agents = home / "Library" / "LaunchAgents"
    runs, close = agents / "org.logbook.sync.plist", agents / "org.logbook.sync.close.plist"
    assert list(plan.files) == [runs, close]
    assert plan.directory == agents
    times = {}
    for path, label, command in (
        (runs, "org.logbook.sync", "sync --scheduled"),
        (close, "org.logbook.sync.close", "sync --scheduled --close"),
    ):
        data = plistlib.loads(plan.files[path].encode("utf-8"))
        assert data["Label"] == label
        shell, flag, script = data["ProgramArguments"]
        assert (shell, flag) == ("/bin/sh", "-c")
        assert script.endswith(f"exec {PYTHON} -m logbook.cli {command}")
        assert '"$HOME/.config/logbook/sync.env"' in script and "set -a" in script, "the secrets are sourced"
        assert data["EnvironmentVariables"] == {"LOGBOOK_HOME": str(tmp_path / "Logbook")}
        assert data["StandardOutPath"] == str(home / "Library" / "Logs" / "logbook-sync.log")
        assert data["StandardErrorPath"] == data["StandardOutPath"]
        assert data["RunAtLoad"] is False and "UserName" not in data
        times[label] = [(c["Hour"], c["Minute"]) for c in data["StartCalendarInterval"]]
    assert times == {"org.logbook.sync": [(0, 0), (12, 0), (18, 0)], "org.logbook.sync.close": [(6, 0)]}
    assert [c.args[:2] for c in plan.activate] == [("launchctl", "bootout"), ("launchctl", "bootstrap")] * 2
    assert [c.required for c in plan.activate] == [False, True] * 2, (
        "unloading what is not loaded is no error"
    )
    assert [c.args[:2] for c in plan.deactivate] == [("launchctl", "bootout")] * 2
    assert [c.args[-1] for c in plan.activate] == [str(runs), str(runs), str(close), str(close)]


def test_the_linux_plan_is_two_systemd_user_timers_at_the_four_times(tmp_path: Path) -> None:
    home = tmp_path / "home"
    plan = schedule.plan("linux", home, PYTHON, logbook_home=tmp_path / "Logbook")
    unit_dir = home / ".config" / "systemd" / "user"
    assert plan.directory == unit_dir
    assert set(plan.files) == {
        unit_dir / f"{name}.{kind}"
        for name in ("logbook-sync", "logbook-sync-close")
        for kind in ("service", "timer")
    }
    for name, command, calendar in (
        ("logbook-sync", "sync --scheduled", "00,12,18"),
        ("logbook-sync-close", "sync --scheduled --close", "06"),
    ):
        service = plan.files[unit_dir / f"{name}.service"]
        assert f"ExecStart={PYTHON} -m logbook.cli {command}\n" in service
        assert "EnvironmentFile=-%h/.config/logbook/sync.env\n" in service, "optional: no file, no secrets"
        assert f"Environment=LOGBOOK_HOME={tmp_path / 'Logbook'}\n" in service
        assert "Type=oneshot\n" in service and "User=" not in service
        timer = plan.files[unit_dir / f"{name}.timer"]
        assert f"OnCalendar=*-*-* {calendar}:00:00\n" in timer and "Persistent=true\n" in timer
        assert f"Unit={name}.service\n" in timer and "WantedBy=timers.target\n" in timer
    timers = ("logbook-sync.timer", "logbook-sync-close.timer")
    assert [c.args for c in plan.activate] == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", *timers),
        ("systemctl", "--user", "restart", *timers),
    ]
    assert [c.args for c in plan.deactivate] == [("systemctl", "--user", "disable", "--now", *timers)]


def test_the_linux_plan_honours_xdg_config_home(tmp_path: Path) -> None:
    plan = schedule.plan("linux", tmp_path / "home", PYTHON, config_home=tmp_path / "xdg")
    assert plan.directory == tmp_path / "xdg" / "systemd" / "user"
    assert all(path.parent == plan.directory for path in plan.files)
    assert "Environment=LOGBOOK_HOME" not in plan.files[plan.directory / "logbook-sync.service"]


def test_a_path_with_a_space_is_quoted_for_both_schedulers(tmp_path: Path) -> None:
    python = "/Users/kari/My Tools/venv/bin/python3"
    mac = schedule.plan("darwin", tmp_path / "home", python)
    scripts = [plistlib.loads(text.encode("utf-8"))["ProgramArguments"][2] for text in mac.files.values()]
    assert all(
        "exec '/Users/kari/My Tools/venv/bin/python3' -m logbook.cli sync --scheduled" in s for s in scripts
    )
    linux = schedule.plan("linux", tmp_path / "home", python)
    for name in ("logbook-sync", "logbook-sync-close"):
        service = linux.files[linux.directory / f"{name}.service"]
        assert 'ExecStart="/Users/kari/My Tools/venv/bin/python3" -m logbook.cli sync --scheduled' in service


FIXTURES = Path(__file__).parent / "fixtures" / "service"


def _fixture(name: str, **paths: Path) -> str:
    """A rendered file as committed, each `@NAME@` filled with the path the test rendered it for."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    for key, path in paths.items():
        text = text.replace(f"@{key}@", str(path))
    return text


def test_the_agent_and_the_units_are_the_files_committed(tmp_path: Path) -> None:
    """The plist and the units byte for byte, so the renderer `serve --install-service` shares with
    this command cannot change what the schedule writes."""
    home, record = tmp_path / "home", tmp_path / "Logbook"
    mac = schedule.plan("darwin", home, PYTHON, logbook_home=record)
    log = home / "Library" / "Logs" / "logbook-sync.log"
    for path, text in mac.files.items():
        assert text == _fixture(path.name, LOG=log, LOGBOOK_HOME=record), path.name
    assert sorted(p.name for p in mac.files) == ["org.logbook.sync.close.plist", "org.logbook.sync.plist"]
    linux = schedule.plan("linux", home, PYTHON, logbook_home=record)
    for name in (
        "logbook-sync.service",
        "logbook-sync.timer",
        "logbook-sync-close.service",
        "logbook-sync-close.timer",
    ):
        assert linux.files[linux.directory / name] == _fixture(name, LOGBOOK_HOME=record), name


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
    units = [
        unit_dir / f"{n}.{k}" for n in ("logbook-sync", "logbook-sync-close") for k in ("service", "timer")
    ]
    for path in units:
        text = path.read_text(encoding="utf-8")
        assert text in out, "printed before it is written"
        assert out.index(str(path)) < out.index(text)
    added = _tree(home) - before
    assert added == {
        Path(".config"),
        Path(".config/systemd"),
        Path(".config/systemd/user"),
        *(path.relative_to(home) for path in units),
        Path("Logbook/state"),
        Path("Logbook/state/home.json"),  # this machine is now the record's home (ADR 0022)
    }, "nothing else under the home directory"
    assert f"Environment=LOGBOOK_HOME={home / 'Logbook'}" in units[0].read_text(encoding="utf-8")
    timers = ("logbook-sync.timer", "logbook-sync-close.timer")
    assert calls == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "--now", *timers),
        ("systemctl", "--user", "restart", *timers),
    ]
    assert (
        "00:00, 12:00 and 18:00" in out and "06:00 as `sync --scheduled --close`" in out and "sync.env" in out
    )


def test_install_without_the_scheduler_on_path_writes_the_files_and_says_what_to_run(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(schedule.shutil, "which", lambda name: None)
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: pytest.fail("never run"))
    cli.main(["sync", "--install-schedule"])
    out = capsys.readouterr().out
    assert (home / ".config" / "systemd" / "user" / "logbook-sync.timer").exists()
    assert "systemctl not found" in out
    assert "systemctl --user enable --now logbook-sync.timer logbook-sync-close.timer" in out


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


def test_uninstall_disables_both_timers_and_removes_only_their_files(
    home: Path, calls: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["sync", "--install-schedule"])
    calls.clear()
    unit_dir = home / ".config" / "systemd" / "user"
    (unit_dir / "other.service").write_text("[Unit]\n", encoding="utf-8")
    capsys.readouterr()
    cli.main(["sync", "--uninstall-schedule"])
    out = capsys.readouterr().out
    assert calls == [
        ("systemctl", "--user", "disable", "--now", "logbook-sync.timer", "logbook-sync-close.timer")
    ]
    assert sorted(p.name for p in unit_dir.iterdir()) == ["other.service"], "all four runs, nothing else"
    for name in (
        "logbook-sync.timer",
        "logbook-sync.service",
        "logbook-sync-close.timer",
        "logbook-sync-close.service",
    ):
        assert f"removed {unit_dir / name}" in out, name
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
    agents = home / "Library" / "LaunchAgents"
    plists = [agents / "org.logbook.sync.plist", agents / "org.logbook.sync.close.plist"]
    assert _tree(home) - before == {
        Path("Library"),
        Path("Library/LaunchAgents"),
        *(plist.relative_to(home) for plist in plists),
        Path("Logbook/state"),
        Path("Logbook/state/home.json"),  # this machine is now the record's home (ADR 0022)
    }
    out = capsys.readouterr().out
    for plist in plists:
        data = plistlib.loads(plist.read_bytes())
        assert data["EnvironmentVariables"] == {"LOGBOOK_HOME": str(home / "Logbook")}
        assert plist.read_text(encoding="utf-8") in out
    assert [c[:2] for c in calls] == [("launchctl", "bootout"), ("launchctl", "bootstrap")] * 2
    assert [c[-1] for c in calls] == [str(plists[0])] * 2 + [str(plists[1])] * 2


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


# -- the two-run schedule moves to the four runs ---------------------------------------------------------

OLD_TIMER = """[Unit]
Description=logbook sync --scheduled at 07:00 and 19:00 local

[Timer]
OnCalendar=*-*-* 07,19:00:00
Persistent=true
Unit=logbook-sync.service

[Install]
WantedBy=timers.target
"""


def test_installing_again_moves_a_two_run_schedule_to_the_four_runs(
    home: Path, calls: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "logbook-sync.timer").write_text(OLD_TIMER, encoding="utf-8")
    (unit_dir / "logbook-sync.service").write_text(
        "[Service]\nExecStart=/old -m logbook.cli sync --scheduled\n"
    )
    cli.main(["sync", "--install-schedule"])
    assert "07,19" not in (unit_dir / "logbook-sync.timer").read_text(encoding="utf-8")
    assert "OnCalendar=*-*-* 00,12,18:00:00" in (unit_dir / "logbook-sync.timer").read_text(encoding="utf-8")
    assert (unit_dir / "logbook-sync-close.timer").exists()
    assert ("systemctl", "--user", "restart", "logbook-sync.timer", "logbook-sync-close.timer") in calls, (
        "a timer enabled before is restarted, so it runs at the new times"
    )


def test_uninstall_removes_a_two_run_schedule_too(
    home: Path,
    calls: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(schedule, "system", lambda: "darwin")
    agents = home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    old = agents / "org.logbook.sync.plist"
    old.write_text(_fixture("org.logbook.sync.plist", LOG=home, LOGBOOK_HOME=home), encoding="utf-8")
    cli.main(["sync", "--uninstall-schedule"])
    assert not old.exists() and list(agents.iterdir()) == []
    assert f"removed {old}" in capsys.readouterr().out


# -- --system: daemons or system units, installed by hand ------------------------------------------------


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> str:
    from logbook.contrib import service

    monkeypatch.setattr(service, "user_name", lambda: "ines")
    monkeypatch.setattr(service, "running_as_root", lambda: False)
    return "ines"


def test_the_system_daemons_run_as_the_user_at_the_four_times(tmp_path: Path) -> None:
    home, root = tmp_path / "home", tmp_path / "system-root"
    plan = schedule.plan("darwin", home, PYTHON, tmp_path / "Logbook", user="ines", system_root=root)
    assert list(plan.files) == [home / "org.logbook.sync.plist", home / "org.logbook.sync.close.plist"], (
        "written to the home directory, not the system's"
    )
    daemons = root / "Library" / "LaunchDaemons"
    assert plan.copies == (daemons / "org.logbook.sync.plist", daemons / "org.logbook.sync.close.plist")
    hours = []
    for text in plan.files.values():
        data = plistlib.loads(text.encode("utf-8"))
        assert data["UserName"] == "ines"
        assert data["EnvironmentVariables"] == {"HOME": str(home), "LOGBOOK_HOME": str(tmp_path / "Logbook")}
        hours.append([c["Hour"] for c in data["StartCalendarInterval"]])
    assert hours == [[0, 12, 18], [6]]
    assert plan.activate == () and plan.deactivate == (), "nothing is run for the system domain"
    copies = [str(path) for path in plan.copies]
    assert [c.args for c in plan.install_by_hand] == [
        ("sudo", "cp", *map(str, plan.files), str(daemons)),
        ("sudo", "launchctl", "bootstrap", "system", *copies),
    ], "two sudo commands"
    assert [c.args for c in plan.replace_by_hand] == [
        ("sudo", "launchctl", "bootout", "system", *copies),
        *[c.args for c in plan.install_by_hand],
    ]
    assert [c.args for c in plan.remove_by_hand] == [
        ("sudo", "launchctl", "bootout", "system", *copies),
        ("sudo", "rm", *copies),
    ]


def test_the_system_units_run_as_the_user_at_the_four_times(tmp_path: Path) -> None:
    home, root = tmp_path / "home", tmp_path / "system-root"
    plan = schedule.plan("linux", home, PYTHON, tmp_path / "Logbook", user="ines", system_root=root)
    names = [f"{n}.{k}" for n in ("logbook-sync", "logbook-sync-close") for k in ("service", "timer")]
    assert list(plan.files) == [home / name for name in names]
    units = root / "etc" / "systemd" / "system"
    assert plan.copies == tuple(units / name for name in names)
    for name, calendar in (("logbook-sync", "00,12,18"), ("logbook-sync-close", "06")):
        service = plan.files[home / f"{name}.service"]
        assert "User=ines\n" in service
        assert f"EnvironmentFile=-{home.as_posix()}/.config/logbook/sync.env\n" in service, (
            "a system unit's %h is root's home: the file is named by its path"
        )
        assert f"OnCalendar=*-*-* {calendar}:00:00\n" in plan.files[home / f"{name}.timer"]
    timers = ("logbook-sync.timer", "logbook-sync-close.timer")
    assert [c.args for c in plan.install_by_hand] == [
        ("sudo", "cp", *map(str, plan.files), str(units)),
        ("sudo", "systemctl", "enable", "--now", *timers),
    ], "two sudo commands"
    assert [c.args for c in plan.remove_by_hand] == [
        ("sudo", "systemctl", "disable", "--now", *timers),
        ("sudo", "rm", *map(str, plan.copies)),
    ]


def test_install_system_writes_to_the_home_directory_prints_the_sudo_commands_and_runs_nothing(
    home: Path,
    account: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from logbook.contrib import service

    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: pytest.fail("nothing is run"))
    root = service.SYSTEM_ROOT
    before = _tree(home)
    cli.main(["sync", "--install-schedule", "--system"])
    out = capsys.readouterr().out
    names = [f"{n}.{k}" for n in ("logbook-sync", "logbook-sync-close") for k in ("service", "timer")]
    assert _tree(home) - before == {
        *(Path(name) for name in names),
        Path("Logbook/state"),
        Path("Logbook/state/home.json"),
    }
    assert not root.exists() or _tree(root) == set(), "the system's folders are the administrator's to write"
    units = root / "etc" / "systemd" / "system"
    assert f"  sudo cp {' '.join(str(home / name) for name in names)} {units}" in out
    assert "  sudo systemctl enable --now logbook-sync.timer logbook-sync-close.timer" in out
    assert "running as ines from boot" in out
    units.mkdir(parents=True)
    for name in names:
        (units / name).write_text("[Unit]\n", encoding="utf-8")
    cli.main(["sync", "--install-schedule", "--system"])
    assert "  sudo systemctl daemon-reload" in capsys.readouterr().out, "over the copies installed before"


def test_uninstall_system_removes_the_home_copies_and_prints_how_to_remove_the_systems(
    home: Path, account: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.contrib import service

    monkeypatch.setattr(schedule, "system", lambda: "darwin")
    cli.main(["sync", "--install-schedule", "--system"])
    daemons = service.SYSTEM_ROOT / "Library" / "LaunchDaemons"
    daemons.mkdir(parents=True)
    for name in ("org.logbook.sync.plist", "org.logbook.sync.close.plist"):
        (daemons / name).write_text("<plist/>", encoding="utf-8")
    capsys.readouterr()
    cli.main(["sync", "--uninstall-schedule", "--system"])
    out = capsys.readouterr().out
    assert (
        not (home / "org.logbook.sync.plist").exists()
        and not (home / "org.logbook.sync.close.plist").exists()
    )
    assert f"  sudo rm {daemons / 'org.logbook.sync.plist'} {daemons / 'org.logbook.sync.close.plist'}" in out
    assert (daemons / "org.logbook.sync.plist").exists(), "never removed by this command"


def test_system_is_refused_as_root_and_without_install(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from logbook.contrib import service

    monkeypatch.setattr(service, "running_as_root", lambda: True)
    with pytest.raises(SystemExit) as e:
        cli.main(["sync", "--install-schedule", "--system"])
    assert e.value.code == 2 and "not as root" in capsys.readouterr().err
    for args in (["sync", "--system"], ["sync", "--all", "--system"]):
        with pytest.raises(SystemExit) as e:
            cli.main(args)
        assert e.value.code == 2, args
        assert "--install-schedule" in capsys.readouterr().err
