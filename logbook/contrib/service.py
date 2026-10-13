"""`logbook serve --install-service [--system]`, `--uninstall-service` and `serve --status`: the pages
kept at http://127.0.0.1:8765/ by the service manager the machine already has, so they are there in
the morning without a terminal open (docs/serve.md, "As a service").

- Without `--system`, the service is the user's, installed as `sync --install-schedule` installs the
  schedule: a launchd agent on macOS (`~/Library/LaunchAgents/org.logbook.serve.plist`, loaded in
  the user's login session), a systemd user service on Linux
  (`~/.config/systemd/user/logbook-serve.service`, or under `$XDG_CONFIG_HOME`; at boot when the user
  lingers, else at login).
- With `--system`, it is a service of the system domain that runs as this user from boot, for a
  machine on which the user never logs in (the record's home, ADR 0022, kept by a user with no GUI
  session, where an agent cannot load): the plist or unit is written to the home directory and the
  `sudo` commands that copy it into `/Library/LaunchDaemons` (or `/etc/systemd/system`) and start it
  are printed. Nothing here runs sudo or writes outside the home directory, and installing as root
  is refused (the daemon would run as root, with root's home).

Either way the service runs `logbook serve --port N` with the interpreter that installed it
(`sys.executable -m logbook.cli`, no PATH assumed), pointed at the record this command found
(`LOGBOOK_HOME`, and `LOGBOOK_IDENTITY_FILE` when it is set: paths, never a key); it is started at
load and started again whenever it fails, and its output goes beside the sync log
(`~/Library/Logs/logbook-serve.log` on macOS, the journal on Linux). It never carries `--host`: the
server binds 127.0.0.1 and refuses anything else, as by hand.

`plan` is pure: the file and the commands for a platform, a home directory and an interpreter, the
plist rendered by `schedule.launchd_plist` and the unit by `schedule.unit_file`, the renderers the
schedule uses. `find` reads what is installed; `answering` asks a port whether a logbook server is
there (one HEAD of `/favicon.ico` on 127.0.0.1, which reads nothing of the record)."""

from __future__ import annotations

import getpass
import http.client
import os
import plistlib
import shlex
import sys
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

from ..core import sealing
from . import schedule, serve
from .schedule import Command

LABEL = "org.logbook.serve"  # launchd
UNIT = "logbook-serve"  # systemd
LOG = ("Library", "Logs", "logbook-serve.log")  # beside the schedule's `logbook-sync.log`
SYSTEM_ROOT = Path("/")  # under it the system domain's folders; the tests point it at a temporary one
DAEMONS = ("Library", "LaunchDaemons")
SYSTEM_UNITS = ("etc", "systemd", "system")
ARGS = ("-m", "logbook.cli", "serve")
PROBE_TIMEOUT_S = 2.0


class ServiceError(ValueError):
    """No service manager here, a port a service cannot keep, or a system service with no user."""


@dataclass(frozen=True)
class Service:
    """What `--install-service` writes and how it is made to run."""

    plan: schedule.Plan  # the one file written; for the user's service, the commands that run it
    path: Path  # where the service manager reads it: the plan's file, or the system domain's copy
    port: int
    user: str | None = None  # the account a system service runs as; None for the user's own
    install_by_hand: tuple[Command, ...] = ()  # --system, printed and never run: a first install
    replace_by_hand: tuple[Command, ...] = ()  # --system, over the copy installed before
    remove_by_hand: tuple[Command, ...] = ()  # --system: stop it and remove the system's copy

    @property
    def system_wide(self) -> bool:
        return self.user is not None

    @property
    def kind(self) -> str:
        return _kind(self.plan.system, self.system_wide)

    @property
    def log(self) -> str:
        return _log(self.plan.system, self.system_wide)


@dataclass(frozen=True)
class Installed:
    """A serve service this machine has: what kind, its file, the port it serves."""

    kind: str
    path: Path
    port: int
    log: str  # where its output goes, as the owner would look


def system() -> str:
    return sys.platform


def user_name() -> str:
    """The account the command runs as, which a system service runs as. Tests replace it."""
    return getpass.getuser()


def running_as_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def plan(
    system: str,
    home: Path,
    python: str,
    logbook_home: Path | None = None,
    port: int = serve.PORT,
    *,
    system_wide: bool = False,
    user: str | None = None,
    config_home: Path | None = None,
    identity_file: Path | None = None,
    airports: Path | None = None,
) -> Service:
    """The file and commands for `system` (`darwin` launchd, `linux` systemd). `python` is the
    interpreter the service runs; `logbook_home` the record (none: found as the shell would);
    `system_wide` the system domain, run as `user`; `config_home` overrides `~/.config` (Linux, the
    user's service). ServiceError for another platform, a port outside 1 to 65535, or a system service
    without a user."""
    if system not in ("darwin", "linux"):
        raise ServiceError(f"no service manager here for {system}: launchd (macOS) and systemd (Linux)")
    if not 0 < port < 65536:
        raise ServiceError(f"a service needs a fixed port, 1 to 65535, not {port}")
    if system_wide and not user:
        raise ServiceError("a system service runs as a user, and none was given")
    arguments: tuple[str, ...] = (python, *ARGS, "--port", str(port))
    if airports is not None:
        arguments += ("--airports", str(airports))
    environment: dict[str, str] = {"HOME": str(home)} if system == "darwin" and system_wide else {}
    if logbook_home is not None:
        environment["LOGBOOK_HOME"] = str(logbook_home)
    if identity_file is not None:
        environment[sealing.IDENTITY_ENV] = str(identity_file)
    environment["PYTHONUNBUFFERED"] = "1"  # the log has each line as it is printed
    if system == "darwin":
        return _launchd(home, arguments, environment, port, user if system_wide else None)
    return _systemd(home, arguments, environment, port, user if system_wide else None, config_home)


def _launchd(
    home: Path, arguments: tuple[str, ...], environment: dict[str, str], port: int, user: str | None
) -> Service:
    text = schedule.launchd_plist(
        LABEL, arguments, home.joinpath(*LOG), environment, keep_alive=True, user=user
    )
    path = path_of("darwin", home, user is not None)
    if user is None:
        activate, deactivate = schedule.agent_commands(path)
        return Service(schedule.Plan("darwin", path.parent, {path: text}, activate, deactivate), path, port)
    copy = home / path.name
    bootout = _sudo("launchctl", "bootout", f"system/{LABEL}")
    install = (_sudo("cp", str(copy), str(path)), _sudo("launchctl", "bootstrap", "system", str(path)))
    return Service(
        schedule.Plan("darwin", home, {copy: text}, (), ()),
        path,
        port,
        user,
        install,
        (bootout, *install),
        (bootout, _sudo("rm", str(path))),
    )


def _systemd(
    home: Path,
    arguments: tuple[str, ...],
    environment: dict[str, str],
    port: int,
    user: str | None,
    config_home: Path | None,
) -> Service:
    text = schedule.unit_file(
        (
            "Unit",
            [f"Description=logbook serve: the record's pages at {_address(port)}, from this machine only"],
        ),
        (
            "Service",
            [
                *([f"User={user}"] if user is not None else []),
                *(schedule.environment_line(key, value) for key, value in environment.items()),
                f"ExecStart={schedule.exec_line(arguments)}",
                "Restart=on-failure",
                "RestartSec=5",
            ],
        ),
        ("Install", ["WantedBy=default.target" if user is None else "WantedBy=multi-user.target"]),
    )
    name = f"{UNIT}.service"
    path = path_of("linux", home, user is not None, config_home)
    if user is None:
        activate = (
            Command(("systemctl", "--user", "daemon-reload")),
            Command(("systemctl", "--user", "enable", name)),
            Command(("systemctl", "--user", "restart", name)),  # started, or started again as now written
        )
        deactivate = (Command(("systemctl", "--user", "disable", "--now", name)),)
        return Service(schedule.Plan("linux", path.parent, {path: text}, activate, deactivate), path, port)
    copy = home / name
    cp = _sudo("cp", str(copy), str(path))
    return Service(
        schedule.Plan("linux", home, {copy: text}, (), ()),
        path,
        port,
        user,
        (cp, _sudo("systemctl", "enable", "--now", name)),
        (cp, _sudo("systemctl", "daemon-reload"), _sudo("systemctl", "restart", name)),
        (_sudo("systemctl", "disable", "--now", name), _sudo("rm", str(path))),
    )


def path_of(system: str, home: Path, system_wide: bool, config_home: Path | None = None) -> Path:
    """Where the service manager reads the service: the user's agent or unit under the home
    directory, or the system domain's under `SYSTEM_ROOT`."""
    if system == "darwin":
        return (
            SYSTEM_ROOT.joinpath(*DAEMONS, f"{LABEL}.plist")
            if system_wide
            else (home / "Library" / "LaunchAgents" / f"{LABEL}.plist")
        )
    if system_wide:
        return SYSTEM_ROOT.joinpath(*SYSTEM_UNITS, f"{UNIT}.service")
    return (config_home or home / ".config") / "systemd" / "user" / f"{UNIT}.service"


def _sudo(*args: str) -> Command:
    return Command(("sudo", *args))


def _address(port: int) -> str:
    return f"http://{serve.HOST}:{port}/"


def _kind(system: str, system_wide: bool) -> str:
    if system == "darwin":
        return "launchd daemon" if system_wide else "launchd agent"
    return "systemd system service" if system_wide else "systemd user service"


def _log(system: str, system_wide: bool) -> str:
    if system == "darwin":
        return "~/" + "/".join(LOG)
    return f"journalctl {'' if system_wide else '--user '}-u {UNIT}.service"


def summary(svc: Service, replacing: bool = False) -> list[str]:
    """What was written, where the pages are and where the output goes, after the file. For a
    system service, the commands to run by hand come in the middle (`replace_by_hand` over a copy
    installed before), each on a line of its own, indented."""
    where = f"{_address(svc.port)} (/today is today's page)"
    bound = "the server binds 127.0.0.1 and nothing else; reaching it from another device: docs/serve.md"
    if svc.system_wide:
        commands = svc.replace_by_hand if replacing else svc.install_by_hand
        return [
            f"written: a {svc.kind} running `logbook serve --port {svc.port}` as {svc.user} from boot,"
            " started again when it fails; nothing runs until you install it, as an administrator:",
            *(f"  {command.text}" for command in commands),
            f"then {where}; its output: {svc.log}; `logbook serve --status` says whether it answers",
            bound,
        ]
    lines = [
        f"installed: a {svc.kind} running `logbook serve --port {svc.port}`, started again when it fails;"
        f" {where}; its output: {svc.log}",
    ]
    if svc.plan.system == "darwin":
        lines.append(
            "an agent runs while you are logged in; on a machine nobody logs in to (the record's home),"
            " `logbook serve --install-service --system` writes a daemon that runs from boot"
        )
    else:
        lines.append(
            "a user service starts with your session; to have it from boot without one:"
            f" `loginctl enable-linger {user_name()}`, or `logbook serve --install-service --system`"
        )
    lines.append(bound)
    return lines


# -- what is installed, and whether it answers -----------------------------------------------------------


def find(system: str, home: Path, config_home: Path | None = None) -> list[Installed]:
    """Every serve service this machine has, the user's first, then the system's: the file the
    service manager reads and the port it names. None installed is an empty list; another platform
    has none."""
    if system not in ("darwin", "linux"):
        return []
    found: list[Installed] = []
    for system_wide in (False, True):
        path = path_of(system, home, system_wide, config_home)
        if path.is_file():
            found.append(
                Installed(_kind(system, system_wide), path, port_of(path), _log(system, system_wide))
            )
    return found


def port_of(path: Path) -> int:
    """The `--port` an installed plist or unit runs the server on; the default when it does not say
    or cannot be read."""
    try:
        if path.suffix == ".plist":
            data = plistlib.loads(path.read_bytes())
            arguments = [str(a) for a in data.get("ProgramArguments", [])] if isinstance(data, dict) else []
        else:
            lines = path.read_text(encoding="utf-8").splitlines()
            start = next((line for line in lines if line.startswith("ExecStart=")), "ExecStart=")
            arguments = shlex.split(start.removeprefix("ExecStart="))
    except (OSError, ValueError, plistlib.InvalidFileException):
        return serve.PORT
    for flag, value in pairwise(arguments):
        if flag == "--port" and value.isdigit():
            return int(value)
    return serve.PORT


def answering(port: int) -> bool:
    """Whether a logbook server answers on 127.0.0.1:`port`: one HEAD of `/favicon.ico` (an empty
    204 that reads nothing of the record) and the `Server` header it carries. Loopback only, by
    address: nothing is resolved."""
    connection = http.client.HTTPConnection(serve.HOST, port, timeout=PROBE_TIMEOUT_S)
    try:
        connection.request("HEAD", "/favicon.ico")
        reply = connection.getresponse()
        return (reply.getheader("Server") or "").strip() == serve.Handler.server_version
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def shown(path: Path, home: Path) -> str:
    """A path as the owner reads it: `~/…` under the home directory, never the user name."""
    try:
        return "~/" + path.relative_to(home).as_posix()
    except ValueError:
        return str(path)
