"""`logbook serve --install-service [--system]`, `--uninstall-service` and `serve --status`: the pages
kept at http://127.0.0.1:8765/ by the machine's own service manager, started at load and again when
they fail, the output beside the sync log. Without `--system` a launchd agent (macOS) or a systemd
user service (Linux) installed as the user, as `sync --install-schedule` installs the schedule; with
`--system` the plist or unit is written to the home directory and the two `sudo` commands that
install it are printed, never run. The plist is the schedule's renderer, the server still binds
127.0.0.1 only, and nothing here talks to launchd or systemd: the calls are recorded. The account is
the Oslo persona's, who does not exist."""

from __future__ import annotations

import plistlib
import shlex
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.contrib import schedule, serve, service
from logbook.core.store import Logbook

PYTHON = "/opt/logbook/venv/bin/python3"
USER = "ines"
FIXTURES = Path(__file__).parent / "fixtures" / "service"


def _fixture(name: str, **paths: Path) -> str:
    """A rendered file as committed, each `@NAME@` filled with the path the test rendered it for."""
    text = (FIXTURES / name).read_text(encoding="utf-8")
    for key, path in paths.items():
        text = text.replace(f"@{key}@", str(path))
    return text


def _tree(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*")} if root.exists() else set()


# -- the files -----------------------------------------------------------------------------------------------


def test_the_agent_is_the_plist_committed(tmp_path: Path) -> None:
    home, record = tmp_path / "home", tmp_path / "Logbook"
    svc = service.plan("darwin", home, PYTHON, record)
    [(path, text)] = svc.plan.files.items()
    assert path == home / "Library" / "LaunchAgents" / "org.logbook.serve.plist"
    assert svc.path == path and not svc.system_wide
    log = home / "Library" / "Logs" / "logbook-serve.log"
    assert text == _fixture("org.logbook.serve.plist", LOG=log, LOGBOOK_HOME=record)
    data = plistlib.loads(text.encode("utf-8"))
    assert Path(data["StandardOutPath"]) == log == home.joinpath(*schedule.LOG).with_name("logbook-serve.log")
    assert data["RunAtLoad"] is True and data["KeepAlive"] == {"SuccessfulExit": False}, (
        "restarted on failure"
    )
    assert Path(data["EnvironmentVariables"]["LOGBOOK_HOME"]) == record
    assert [c.args[:2] for c in svc.plan.activate] == [("launchctl", "bootout"), ("launchctl", "bootstrap")]
    assert svc.plan.activate[-1].args[2].startswith("gui/")


def test_the_daemon_is_the_plist_committed_and_runs_as_the_user(tmp_path: Path) -> None:
    home, record = tmp_path / "home", tmp_path / "Logbook"
    svc = service.plan("darwin", home, PYTHON, record, system_wide=True, user=USER)
    [(path, text)] = svc.plan.files.items()
    assert path == home / "org.logbook.serve.plist", "written to the home directory, not the system's"
    assert svc.path == service.SYSTEM_ROOT / "Library" / "LaunchDaemons" / "org.logbook.serve.plist"
    log = home / "Library" / "Logs" / "logbook-serve.log"
    assert text == _fixture("org.logbook.serve.daemon.plist", LOG=log, HOME=home, LOGBOOK_HOME=record)
    data = plistlib.loads(text.encode("utf-8"))
    assert data["UserName"] == USER and Path(data["EnvironmentVariables"]["HOME"]) == home
    assert svc.plan.activate == () and svc.plan.deactivate == (), "nothing is run for the system domain"
    assert [c.args for c in svc.install_by_hand] == [
        ("sudo", "cp", str(path), str(svc.path)),
        ("sudo", "launchctl", "bootstrap", "system", str(svc.path)),
    ]
    assert [c.args for c in svc.replace_by_hand] == [
        ("sudo", "launchctl", "bootout", "system/org.logbook.serve"),
        *[c.args for c in svc.install_by_hand],
    ]
    assert [c.args for c in svc.remove_by_hand] == [
        ("sudo", "launchctl", "bootout", "system/org.logbook.serve"),
        ("sudo", "rm", str(svc.path)),
    ]


def test_the_user_unit_is_the_unit_committed(tmp_path: Path) -> None:
    home, record = tmp_path / "home", tmp_path / "Logbook"
    svc = service.plan("linux", home, PYTHON, record)
    [(path, text)] = svc.plan.files.items()
    assert path == home / ".config" / "systemd" / "user" / "logbook-serve.service"
    assert text == _fixture("logbook-serve.service", LOGBOOK_HOME=record)
    assert [c.args for c in svc.plan.activate] == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "logbook-serve.service"),
        ("systemctl", "--user", "restart", "logbook-serve.service"),
    ]
    assert [c.args for c in svc.plan.deactivate] == [
        ("systemctl", "--user", "disable", "--now", "logbook-serve.service")
    ]
    xdg = service.plan("linux", home, PYTHON, record, config_home=tmp_path / "xdg")
    assert list(xdg.plan.files) == [tmp_path / "xdg" / "systemd" / "user" / "logbook-serve.service"]


def test_the_system_unit_is_the_unit_committed(tmp_path: Path) -> None:
    home, record = tmp_path / "home", tmp_path / "Logbook"
    svc = service.plan("linux", home, PYTHON, record, system_wide=True, user=USER)
    [(path, text)] = svc.plan.files.items()
    assert path == home / "logbook-serve.service"
    assert svc.path == service.SYSTEM_ROOT / "etc" / "systemd" / "system" / "logbook-serve.service"
    assert text == _fixture("logbook-serve.system.service", LOGBOOK_HOME=record)
    assert svc.plan.activate == () and svc.plan.deactivate == ()
    assert [c.args for c in svc.install_by_hand] == [
        ("sudo", "cp", str(path), str(svc.path)),
        ("sudo", "systemctl", "enable", "--now", "logbook-serve.service"),
    ]
    assert [c.args for c in svc.replace_by_hand] == [
        ("sudo", "cp", str(path), str(svc.path)),
        ("sudo", "systemctl", "daemon-reload"),
        ("sudo", "systemctl", "restart", "logbook-serve.service"),
    ]
    assert [c.args for c in svc.remove_by_hand] == [
        ("sudo", "systemctl", "disable", "--now", "logbook-serve.service"),
        ("sudo", "rm", str(svc.path)),
    ]


def test_the_port_the_airports_and_the_identity_file_are_carried(tmp_path: Path) -> None:
    home = tmp_path / "home"
    identity, airports = tmp_path / "keys" / "identity.txt", tmp_path / "My Airports.csv"
    mac = service.plan("darwin", home, PYTHON, port=8080, identity_file=identity, airports=airports)
    data = plistlib.loads(next(iter(mac.plan.files.values())).encode("utf-8"))
    assert data["ProgramArguments"][3:] == ["serve", "--port", "8080", "--airports", str(airports)]
    assert Path(data["EnvironmentVariables"]["LOGBOOK_IDENTITY_FILE"]) == identity
    assert "LOGBOOK_HOME" not in data["EnvironmentVariables"], "no record given: found as the shell would"
    linux = service.plan("linux", home, PYTHON, port=8080, identity_file=identity, airports=airports)
    unit = next(iter(linux.plan.files.values()))
    assert f'serve --port 8080 --airports "{airports}"\n' in unit, "an argument with a space is quoted"
    assert f"Environment=LOGBOOK_IDENTITY_FILE={identity}\n" in unit
    assert mac.port == linux.port == 8080


def test_the_plist_and_the_unit_are_the_schedules_renderers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One renderer each, shared with `sync --install-schedule`: the service calls them."""
    seen: list[str] = []
    plist, unit = schedule.launchd_plist, schedule.unit_file

    def spy_plist(*args: Any, **kwargs: Any) -> str:
        seen.append("plist")
        return plist(*args, **kwargs)

    def spy_unit(*args: Any, **kwargs: Any) -> str:
        seen.append("unit")
        return unit(*args, **kwargs)

    monkeypatch.setattr(schedule, "launchd_plist", spy_plist)
    monkeypatch.setattr(schedule, "unit_file", spy_unit)
    service.plan("darwin", tmp_path, PYTHON)
    service.plan("darwin", tmp_path, PYTHON, system_wide=True, user=USER)
    service.plan("linux", tmp_path, PYTHON)
    service.plan("linux", tmp_path, PYTHON, system_wide=True, user=USER)
    assert seen == ["plist", "plist", "unit", "unit"]


def test_the_service_runs_the_server_on_loopback_and_nowhere_else(tmp_path: Path) -> None:
    """No `--host` in what the service runs: the server's own default, 127.0.0.1, is the bind."""
    for system in ("darwin", "linux"):
        for system_wide in (False, True):
            svc = service.plan(system, tmp_path, PYTHON, system_wide=system_wide, user=USER)
            text = next(iter(svc.plan.files.values()))
            assert "--host" not in text and "0.0.0.0" not in text, (system, system_wide)
            assert "http://127.0.0.1:8765/" in "\n".join(service.summary(svc)), (system, system_wide)


def test_a_port_no_service_can_keep_and_another_platform_are_refused(tmp_path: Path) -> None:
    for port in (0, -1, 70000):
        with pytest.raises(service.ServiceError, match="port"):
            service.plan("linux", tmp_path, PYTHON, port=port)
    with pytest.raises(service.ServiceError, match="win32"):
        service.plan("win32", tmp_path, PYTHON)
    with pytest.raises(service.ServiceError, match="user"):
        service.plan("darwin", tmp_path, PYTHON, system_wide=True)


# -- through the CLI -----------------------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A record under the temporary home (conftest points HOME there and the system folders at a
    temporary root), Linux, the persona's account, not root."""
    home = Path.home()
    lb = Logbook.init(home / "Logbook", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    monkeypatch.setattr(service, "system", lambda: "linux")
    monkeypatch.setattr(service, "user_name", lambda: USER)
    monkeypatch.setattr(service, "running_as_root", lambda: False)
    monkeypatch.setattr(service, "answering", lambda port: False)
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


def _exit(args: list[str]) -> int:
    try:
        cli.main(args)
    except SystemExit as e:
        return int(e.code or 0)
    return 0


def test_install_prints_the_unit_writes_it_in_the_user_dir_only_and_starts_it(
    home: Path, calls: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    before, system = _tree(home), _tree(service.SYSTEM_ROOT)
    assert _exit(["serve", "--install-service"]) == 0
    out = capsys.readouterr().out
    unit = home / ".config" / "systemd" / "user" / "logbook-serve.service"
    text = unit.read_text(encoding="utf-8")
    assert text in out and out.index(str(unit)) < out.index(text), "printed before it is written"
    assert _tree(home) - before == {
        Path(".config"),
        Path(".config/systemd"),
        Path(".config/systemd/user"),
        unit.relative_to(home),
    }, "nothing else under the home directory; the record's home is the schedule's business"
    assert _tree(service.SYSTEM_ROOT) == system
    assert f"Environment=LOGBOOK_HOME={home / 'Logbook'}\n" in text
    assert calls == [
        ("systemctl", "--user", "daemon-reload"),
        ("systemctl", "--user", "enable", "logbook-serve.service"),
        ("systemctl", "--user", "restart", "logbook-serve.service"),
    ]
    assert "http://127.0.0.1:8765/" in out and "journalctl --user -u logbook-serve.service" in out
    assert "loginctl enable-linger" in out, "a user service starts at boot only when the user lingers"


def test_install_on_macos_loads_an_agent_logging_beside_the_sync_log(
    home: Path,
    calls: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(service, "system", lambda: "darwin")
    assert _exit(["serve", "--install-service", "--port", "8080"]) == 0
    plist = home / "Library" / "LaunchAgents" / "org.logbook.serve.plist"
    data = plistlib.loads(plist.read_bytes())
    assert data["ProgramArguments"][-2:] == ["--port", "8080"]
    assert Path(data["StandardOutPath"]).parent == home.joinpath(*schedule.LOG).parent
    assert [c[:2] for c in calls] == [("launchctl", "bootout"), ("launchctl", "bootstrap")]
    out = capsys.readouterr().out
    assert "logbook-serve.log" in out and "--system" in out, "no login session: the daemon"


def test_install_system_writes_to_the_home_directory_and_prints_two_sudo_commands_it_never_runs(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(service, "system", lambda: "darwin")
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: pytest.fail("nothing is run"))
    before = _tree(home)
    assert _exit(["serve", "--install-service", "--system"]) == 0
    out = capsys.readouterr().out
    copy = home / "org.logbook.serve.plist"
    target = service.SYSTEM_ROOT / "Library" / "LaunchDaemons" / "org.logbook.serve.plist"
    assert _tree(home) - before == {copy.relative_to(home)}
    assert not service.SYSTEM_ROOT.exists(), "nothing is written outside the home directory"
    assert plistlib.loads(copy.read_bytes())["UserName"] == USER
    commands = [line.strip() for line in out.splitlines() if line.strip().startswith("sudo ")]
    assert commands == [
        shlex.join(("sudo", "cp", str(copy), str(target))),
        shlex.join(("sudo", "launchctl", "bootstrap", "system", str(target))),
    ]
    target.parent.mkdir(parents=True)
    target.write_bytes(copy.read_bytes())  # the owner ran them; installing again replaces it
    assert _exit(["serve", "--install-service", "--system"]) == 0
    out = capsys.readouterr().out
    commands = [line.strip() for line in out.splitlines() if line.strip().startswith("sudo ")]
    assert commands[0] == "sudo launchctl bootout system/org.logbook.serve" and len(commands) == 3


def test_install_system_on_linux_prints_the_copy_and_the_enable(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: pytest.fail("nothing is run"))
    assert _exit(["serve", "--install-service", "--system"]) == 0
    out = capsys.readouterr().out
    copy = home / "logbook-serve.service"
    target = service.SYSTEM_ROOT / "etc" / "systemd" / "system" / "logbook-serve.service"
    assert "User=ines\n" in copy.read_text(encoding="utf-8")
    commands = [line.strip() for line in out.splitlines() if line.strip().startswith("sudo ")]
    assert commands == [
        shlex.join(("sudo", "cp", str(copy), str(target))),
        "sudo systemctl enable --now logbook-serve.service",
    ]


def test_install_system_as_root_is_refused(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`sudo logbook serve --install-service --system` would make a daemon that runs as root, with
    root's home: refused, nothing written."""
    monkeypatch.setattr(service, "running_as_root", lambda: True)
    before = _tree(home)
    assert _exit(["serve", "--install-service", "--system"]) == 2
    assert "root" in capsys.readouterr().err and _tree(home) == before


def test_uninstall_stops_the_service_and_removes_only_its_file(
    home: Path, calls: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(["serve", "--install-service"])
    calls.clear()
    unit_dir = home / ".config" / "systemd" / "user"
    (unit_dir / "other.service").write_text("[Unit]\n", encoding="utf-8")
    capsys.readouterr()
    assert _exit(["serve", "--uninstall-service"]) == 0
    assert calls == [("systemctl", "--user", "disable", "--now", "logbook-serve.service")]
    assert sorted(p.name for p in unit_dir.iterdir()) == ["other.service"]
    assert "removed" in capsys.readouterr().out
    assert _exit(["serve", "--uninstall-service"]) == 0
    assert "no serve service installed" in capsys.readouterr().out


def test_uninstall_system_removes_the_copy_and_prints_the_commands_it_never_runs(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(service, "system", lambda: "darwin")
    monkeypatch.setattr(schedule.subprocess, "run", lambda *a, **k: pytest.fail("nothing is run"))
    cli.main(["serve", "--install-service", "--system"])
    target = service.SYSTEM_ROOT / "Library" / "LaunchDaemons" / "org.logbook.serve.plist"
    target.parent.mkdir(parents=True)
    target.write_bytes((home / "org.logbook.serve.plist").read_bytes())
    capsys.readouterr()
    assert _exit(["serve", "--uninstall-service", "--system"]) == 0
    out = capsys.readouterr().out
    assert not (home / "org.logbook.serve.plist").exists()
    assert target.exists(), "the system's copy is the owner's to remove, with sudo"
    commands = [line.strip() for line in out.splitlines() if line.strip().startswith("sudo ")]
    assert commands == [
        "sudo launchctl bootout system/org.logbook.serve",
        shlex.join(("sudo", "rm", str(target))),
    ]


def test_the_flags_go_together_only_as_they_should(
    home: Path, calls: list[tuple[str, ...]], capsys: pytest.CaptureFixture[str]
) -> None:
    for args in (
        ["serve", "--install-service", "--uninstall-service"],
        ["serve", "--install-service", "--status"],
        ["serve", "--system"],
        ["serve", "--status", "--system"],
        ["serve", "--install-service", "--port", "0"],
        ["serve", "--install-service", "--host", "0.0.0.0"],
    ):
        assert _exit(args) == 2, args
        assert capsys.readouterr().err, args
    assert calls == [] and not (home / ".config").exists()


# -- status --------------------------------------------------------------------------------------------------


def test_status_says_absent_installed_and_answering(
    home: Path,
    calls: list[tuple[str, ...]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert _exit(["serve", "--status"]) == 3
    assert "no serve service installed" in capsys.readouterr().out
    cli.main(["serve", "--install-service", "--port", "8080"])
    capsys.readouterr()
    assert _exit(["serve", "--status"]) == 1, "installed, nothing answering"
    out = capsys.readouterr().out
    assert "systemd user service" in out and "8080" in out and "journalctl --user" in out
    asked: list[int] = []
    monkeypatch.setattr(service, "answering", lambda port: asked.append(port) or True)
    assert _exit(["serve", "--status"]) == 0
    assert asked == [8080], "the port the installed unit names"
    assert "answering at http://127.0.0.1:8080/" in capsys.readouterr().out


def test_status_finds_the_system_service_too(
    home: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(service, "system", lambda: "darwin")
    cli.main(["serve", "--install-service", "--system", "--port", "8081"])
    target = service.SYSTEM_ROOT / "Library" / "LaunchDaemons" / "org.logbook.serve.plist"
    target.parent.mkdir(parents=True)
    target.write_bytes((home / "org.logbook.serve.plist").read_bytes())
    [found] = service.find("darwin", home)
    assert found.kind == "launchd daemon" and found.path == target and found.port == 8081
    monkeypatch.setattr(service, "answering", lambda port: port == 8081)
    capsys.readouterr()
    assert _exit(["serve", "--status"]) == 0
    assert "launchd daemon" in capsys.readouterr().out


def test_answering_asks_the_port_and_knows_a_logbook_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real probe against a real server on 127.0.0.1, and against a port nothing listens on."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    server = serve.make_server(lb, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        assert service.answering(port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert not service.answering(port), "closed now"
