"""`logbook sync --install-schedule` / `--uninstall-schedule`: `logbook sync --scheduled` (`sync --all`,
then `doctor`, the outcome to `state/last-run.json`, one message when something is wrong: docs/schedule.md)
four times a day, at 00:00, 06:00, 12:00 and 18:00 local, by the scheduler the machine already has. The
06:00 run is the close (`sync --scheduled --close`): the same run, then the dream's catch-up when this
version has the dream and the policy allows it, so the day that ended at the owner's `day_start` is
read once it is over (RFC 0036). Two jobs, then: the runs at 00:00, 12:00 and 18:00, and the close.

- Without `--system`, the user's: two launchd agents on macOS (`~/Library/LaunchAgents/org.logbook.sync.plist`
  and `org.logbook.sync.close.plist`), two systemd user timers on Linux
  (`~/.config/systemd/user/logbook-sync.{service,timer}` and `logbook-sync-close.{service,timer}`, or
  under `$XDG_CONFIG_HOME`).
- With `--system`, daemons or units of the system domain that run as this user from boot, as `serve
  --install-service --system` writes the server's: the files are written to the home directory and the
  two `sudo` commands that copy them into `/Library/LaunchDaemons` (or `/etc/systemd/system`) and start
  them are printed, never run.

An install made before the four runs (one agent or timer at 07:00 and 19:00, under the same names) is
moved to them by installing again: the files are written over and the jobs loaded again;
`--uninstall-schedule` removes every file of the schedule, the close's included.

The rules: the plist or unit is printed before it is written; nothing is written outside that one
directory; the agent runs the Python that installed it (`sys.executable -m logbook.cli`), so no PATH
is assumed, and carries `LOGBOOK_HOME` so it finds the record this command found. The secrets a live
source needs (`LOGBOOK_IMMICH_KEY`, …) are never written here: both schedulers read them at run time
from `~/.config/logbook/sync.env`, `KEY=value` lines the owner writes and keeps at mode 600 — the
agent sources it (`set -a; . file`), the unit names it as an optional `EnvironmentFile`. A source
whose variables are not set is one `sync --all` skips, so the schedule is harmless until the file
exists.

`plan` is pure: the files and the scheduler's commands for a platform, a home directory and an
interpreter. The plists are `launchd_plist`'s and the units `unit_file`'s, the one renderer of each,
which `serve --install-service` (`logbook.contrib.service`) uses too. `install` prints and writes;
`uninstall` unlinks what `plan` names and nothing else; `run` hands the commands to the scheduler and
reports, or says what to run when it is not on PATH.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

LABEL = "org.logbook.sync"  # launchd: the runs at HOURS
CLOSE_LABEL = "org.logbook.sync.close"  # launchd: the run at CLOSE_HOUR
UNIT = "logbook-sync"  # systemd
CLOSE_UNIT = "logbook-sync-close"
HOURS = (0, 12, 18)  # local: `sync --scheduled`
CLOSE_HOUR = 6  # local: `sync --scheduled --close`, the run that closes the day (RFC 0036)
RUNS = tuple(sorted((*HOURS, CLOSE_HOUR)))  # the four, as the owner reads them
ENV_FILE = ".config/logbook/sync.env"  # relative to the home directory; the owner's, never written here
LOG = ("Library", "Logs", "logbook-sync.log")  # launchd's stdout and stderr; launchd creates it, not we
ARGS = ("-m", "logbook.cli", "sync", "--scheduled")
CLOSE_ARGS = (*ARGS, "--close")
DAEMONS = ("Library", "LaunchDaemons")  # under the system root: where the system domain reads a daemon
SYSTEM_UNITS = ("etc", "systemd", "system")


class ScheduleError(ValueError):
    """No scheduler here for this platform."""


@dataclass(frozen=True)
class Command:
    args: tuple[str, ...]
    required: bool = True  # False: a failure is expected and silent (unloading what is not loaded)

    @property
    def text(self) -> str:
        return shlex.join(self.args)


@dataclass(frozen=True)
class Plan:
    system: str  # `darwin` or `linux`
    directory: Path  # the one directory written to
    files: dict[Path, str]  # path → text, every path inside `directory`
    activate: tuple[Command, ...]
    deactivate: tuple[Command, ...]
    user: str | None = None  # `--system`: the account the jobs run as; None for the user's own
    copies: tuple[Path, ...] = ()  # `--system`: where the system's scheduler reads the files
    install_by_hand: tuple[Command, ...] = ()  # `--system`, printed and never run: a first install
    replace_by_hand: tuple[Command, ...] = ()  # `--system`, over the copies installed before
    remove_by_hand: tuple[Command, ...] = ()  # `--system`: stop the jobs and remove the system's copies

    @property
    def tool(self) -> str:
        return self.activate[-1].args[0]

    @property
    def system_wide(self) -> bool:
        return self.user is not None


def system() -> str:
    return sys.platform


def plan(
    system: str,
    home: Path,
    python: str,
    logbook_home: Path | None = None,
    config_home: Path | None = None,
    *,
    user: str | None = None,
    system_root: Path = Path("/"),
) -> Plan:
    """The files and commands for `system`: `darwin` two launchd agents, `linux` two systemd user
    timers; with `user`, daemons or system units that run as that account, written to `home` with the
    sudo commands that install them under `system_root`. `python` is the interpreter the jobs run;
    `logbook_home` the record they are pointed at (none: they find the record as the shell would);
    `config_home` overrides `~/.config` (Linux, `$XDG_CONFIG_HOME`, the user's timers). ScheduleError
    for any other platform."""
    if system == "darwin":
        return _launchd(home, python, logbook_home, user, system_root)
    if system == "linux":
        return _systemd(home, python, logbook_home, config_home, user, system_root)
    raise ScheduleError(f"no scheduler here for {system}: launchd (macOS) and systemd user timers (Linux)")


def _jobs() -> tuple[tuple[str, str, tuple[str, ...], tuple[int, ...]], ...]:
    """(launchd label, systemd unit, arguments, local hours) of each job: the runs, then the close."""
    return ((LABEL, UNIT, ARGS, HOURS), (CLOSE_LABEL, CLOSE_UNIT, CLOSE_ARGS, (CLOSE_HOUR,)))


def _launchd(home: Path, python: str, logbook_home: Path | None, user: str | None, system_root: Path) -> Plan:
    environment = {"HOME": str(home)} if user is not None else {}  # a daemon has no HOME of its own
    if logbook_home is not None:
        environment["LOGBOOK_HOME"] = str(logbook_home)
    env_file = f'"$HOME/{ENV_FILE}"'
    files: dict[Path, str] = {}
    for label, _unit, args, hours in _jobs():
        script = (
            f"if [ -r {env_file} ]; then set -a; . {env_file}; set +a; fi; "
            f"exec {shlex.quote(python)} {' '.join(args)}"
        )
        text = launchd_plist(
            label,
            ("/bin/sh", "-c", script),
            home.joinpath(*LOG),
            environment,
            calendar=[{"Hour": hour, "Minute": 0} for hour in hours],
            user=user,
        )
        directory = home if user is not None else home / "Library" / "LaunchAgents"
        files[directory / f"{label}.plist"] = text
    if user is None:
        commands = [agent_commands(path) for path in files]
        activate = tuple(c for pair in commands for c in pair[0])
        deactivate = tuple(c for pair in commands for c in pair[1])
        return Plan("darwin", home / "Library" / "LaunchAgents", files, activate, deactivate)
    daemons = system_root.joinpath(*DAEMONS)
    copies = tuple(daemons / path.name for path in files)
    bootout = _sudo("launchctl", "bootout", "system", *map(str, copies))
    install = (
        _sudo("cp", *map(str, files), str(daemons)),
        _sudo("launchctl", "bootstrap", "system", *map(str, copies)),
    )
    remove = (bootout, _sudo("rm", *map(str, copies)))
    return Plan("darwin", home, files, (), (), user, copies, install, (bootout, *install), remove)


def launchd_plist(
    label: str,
    arguments: Sequence[str],
    log: Path,
    environment: Mapping[str, str],
    *,
    calendar: Sequence[Mapping[str, int]] = (),
    keep_alive: bool = False,
    user: str | None = None,
) -> str:
    """A launchd job, the one renderer for every plist the package writes (this schedule, `serve
    --install-service`): `arguments` run as given, stdout and stderr to `log` (launchd creates it).
    With `calendar` the job runs at those local times and not at load; with `keep_alive` it starts
    at load and launchd starts it again whenever it exits unsuccessfully. `user` is the account a
    daemon of the system domain runs as (`UserName`); an agent runs as the user who loaded it."""
    data: dict[str, object] = {"Label": label}
    if user is not None:
        data["UserName"] = user
    data["ProgramArguments"] = list(arguments)
    if calendar:
        data["StartCalendarInterval"] = [dict(c) for c in calendar]
    data["RunAtLoad"] = keep_alive
    if keep_alive:
        data["KeepAlive"] = {"SuccessfulExit": False}
    data["StandardOutPath"] = str(log)
    data["StandardErrorPath"] = str(log)
    if environment:
        data["EnvironmentVariables"] = dict(environment)
    return plistlib.dumps(data, sort_keys=False).decode("utf-8")


def agent_commands(path: Path) -> tuple[tuple[Command, ...], tuple[Command, ...]]:
    """(activate, deactivate) for a launchd agent of this user's login session: unloaded first, so
    an agent installed again is loaded as now written."""
    domain = f"gui/{os.getuid() if hasattr(os, 'getuid') else 501}"
    return (
        (
            Command(("launchctl", "bootout", domain, str(path)), required=False),
            Command(("launchctl", "bootstrap", domain, str(path))),
        ),
        (Command(("launchctl", "bootout", domain, str(path)), required=False),),
    )


def _systemd(
    home: Path,
    python: str,
    logbook_home: Path | None,
    config_home: Path | None,
    user: str | None,
    system_root: Path,
) -> Plan:
    if user is None:
        directory = (config_home or home / ".config") / "systemd" / "user"
        env_file = f"%h/{ENV_FILE}"
    else:  # a system unit's %h is root's home, whatever User= says: the file is named by its path
        directory, env_file = home, f"{home.as_posix()}/{ENV_FILE}"
    environment = [environment_line("LOGBOOK_HOME", str(logbook_home))] if logbook_home is not None else []
    files: dict[Path, str] = {}
    timers: list[str] = []
    for _label, unit, args, hours in _jobs():
        what = (
            "the run that closes the day, then the dream's catch-up"
            if unit == CLOSE_UNIT
            else "every configured live source, then doctor"
        )
        files[directory / f"{unit}.service"] = unit_file(
            ("Unit", [f"Description=logbook {' '.join(args[2:])}: {what}"]),
            (
                "Service",
                [
                    "Type=oneshot",
                    *([f"User={user}"] if user is not None else []),
                    f"EnvironmentFile=-{env_file}",
                    *environment,
                    f"ExecStart={exec_line((python, *args))}",
                ],
            ),
        )
        files[directory / f"{unit}.timer"] = unit_file(
            ("Unit", [f"Description=logbook {' '.join(args[2:])} at {_hours_text(hours)} local"]),
            (
                "Timer",
                [
                    f"OnCalendar=*-*-* {','.join(f'{h:02d}' for h in hours)}:00:00",
                    "Persistent=true",
                    f"Unit={unit}.service",
                ],
            ),
            ("Install", ["WantedBy=timers.target"]),
        )
        timers.append(f"{unit}.timer")
    if user is None:
        return Plan(
            "linux",
            directory,
            files,
            (
                Command(("systemctl", "--user", "daemon-reload")),
                Command(("systemctl", "--user", "enable", "--now", *timers)),
                Command(
                    ("systemctl", "--user", "restart", *timers)
                ),  # a timer enabled before takes the new times
            ),
            (Command(("systemctl", "--user", "disable", "--now", *timers)),),
        )
    units = system_root.joinpath(*SYSTEM_UNITS)
    copies = tuple(units / path.name for path in files)
    cp = _sudo("cp", *map(str, files), str(units))
    return Plan(
        "linux",
        home,
        files,
        (),
        (),
        user,
        copies,
        (cp, _sudo("systemctl", "enable", "--now", *timers)),
        (cp, _sudo("systemctl", "daemon-reload"), _sudo("systemctl", "restart", *timers)),
        (_sudo("systemctl", "disable", "--now", *timers), _sudo("rm", *map(str, copies))),
    )


def _sudo(*args: str) -> Command:
    return Command(("sudo", *args))


def _hours_text(hours: tuple[int, ...]) -> str:
    """`00:00, 12:00 and 18:00`."""
    clocks = [f"{h:02d}:00" for h in hours]
    return clocks[0] if len(clocks) == 1 else f"{', '.join(clocks[:-1])} and {clocks[-1]}"


def unit_file(*sections: tuple[str, Sequence[str]]) -> str:
    """A systemd unit, the one renderer for every unit the package writes: each `[Section]` with its
    `Key=value` lines, a blank line between sections."""
    return "\n".join(f"[{name}]\n" + "".join(f"{line}\n" for line in lines) for name, lines in sections)


def exec_line(arguments: Sequence[str]) -> str:
    """`ExecStart=`'s value: each argument double-quoted when it holds whitespace (systemd's own
    quoting)."""
    return " ".join(f'"{a}"' if any(c.isspace() for c in a) else a for a in arguments)


def environment_line(key: str, value: str) -> str:
    """`Environment=KEY=value`, the assignment double-quoted when the value holds whitespace."""
    assignment = f"{key}={value}"
    return (
        f'Environment="{assignment}"' if any(c.isspace() for c in assignment) else f"Environment={assignment}"
    )


def install(plan: Plan, say: Callable[[str], None]) -> None:
    """Print each file — its path, then its text — and then write it, the directory made if need
    be. Nothing outside `plan.directory` is touched."""
    plan.directory.mkdir(parents=True, exist_ok=True)
    for path, text in plan.files.items():
        say(f"writing {path}:")
        say(text.rstrip("\n"))
        say("")
        path.write_text(text, encoding="utf-8")


def uninstall(plan: Plan) -> list[Path]:
    """Unlink the files `plan` names that exist, and no other; the paths removed."""
    removed: list[Path] = []
    for path in plan.files:
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed


def run(commands: tuple[Command, ...], tool: str, say: Callable[[str], None]) -> str | None:
    """Hand `commands` to the scheduler. The error text of the first required command that fails,
    else None; when `tool` is not on PATH, say so and what to run by hand, and return None."""
    if shutil.which(tool) is None:
        say(f"{tool} not found on PATH; when it is, run:")
        for command in commands:
            if command.required:
                say(f"  {command.text}")
        return None
    for command in commands:
        result = subprocess.run(list(command.args), capture_output=True, encoding="utf-8", check=False)
        if result.returncode != 0 and command.required:
            detail = (result.stderr or result.stdout).strip() or f"exit status {result.returncode}"
            return f"{command.text}: {detail}"
    return None


def installed(plan: Plan) -> bool:
    """Whether every file `plan` names is there (for `--system`, the system's copies): the schedule
    is installed on this machine."""
    return all(path.exists() for path in (plan.copies or tuple(plan.files)))


def summary(plan: Plan, replacing: bool = False) -> list[str]:
    """What was installed and where the secrets go, after the files. For `--system`, the commands to
    run by hand come first (`replace_by_hand` over copies installed before), each on a line of its own,
    indented."""
    log = " (launchd; its output goes to ~/Library/Logs/logbook-sync.log)" if plan.system == "darwin" else ""
    runs = (
        f"`logbook sync --scheduled` (`sync --all`, then `doctor`) runs at {_hours_text(HOURS)} local, and at"
        f" {CLOSE_HOUR:02d}:00 as `sync --scheduled --close`, which then runs the dream's catch-up when this"
        " version has it and policy/crossing.json has a dream entry"
    )
    head = [f"installed: {runs}{log}; the outcome goes to state/last-run.json and `logbook doctor` reads it"]
    if plan.system_wide:
        commands = plan.replace_by_hand if replacing else plan.install_by_hand
        head = [
            f"written: {len(plan.files)} files for the system domain, running as {plan.user} from boot:"
            f" {runs}; nothing runs until you install them, as an administrator:",
            *(f"  {command.text}" for command in commands),
        ]
    return [
        *head,
        "to be told when something is wrong, put LOGBOOK_NOTIFY_TELEGRAM_TOKEN and"
        " LOGBOOK_NOTIFY_TELEGRAM_CHAT in the same file: one Telegram message when a source fails or doctor"
        " warns, and the week's counts on Sunday evening (docs/schedule.md)",
        f"the variables your live sources need go in ~/{ENV_FILE}, one KEY=value per line, mode 600;"
        " a source whose variables are not set is skipped",
    ]
