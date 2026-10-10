"""`logbook sync --install-schedule` / `--uninstall-schedule`: `logbook sync --scheduled` (`sync --all`,
then `doctor`, the outcome to `state/last-run.json`, one message when something is wrong: docs/schedule.md)
twice a day, 07:00 and 19:00 local, by the scheduler the machine already has — a launchd agent on macOS
(`~/Library/LaunchAgents/org.logbook.sync.plist`), a systemd user timer on Linux
(`~/.config/systemd/user/logbook-sync.{service,timer}`, or under `$XDG_CONFIG_HOME`).

The rules: the plist or unit is printed before it is written; nothing is written outside that one
directory; the agent runs the Python that installed it (`sys.executable -m logbook.cli`), so no PATH
is assumed, and carries `LOGBOOK_HOME` so it finds the record this command found. The secrets a live
source needs (`LOGBOOK_IMMICH_KEY`, …) are never written here: both schedulers read them at run time
from `~/.config/logbook/sync.env`, `KEY=value` lines the owner writes and keeps at mode 600 — the
agent sources it (`set -a; . file`), the unit names it as an optional `EnvironmentFile`. A source
whose variables are not set is one `sync --all` skips, so the schedule is harmless until the file
exists.

`plan` is pure: the files and the scheduler's commands for a platform, a home directory and an
interpreter. `install` prints and writes; `uninstall` unlinks what `plan` names and nothing else;
`run` hands the commands to the scheduler and reports, or says what to run when it is not on PATH.
"""

from __future__ import annotations

import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

LABEL = "org.logbook.sync"  # launchd
UNIT = "logbook-sync"  # systemd
HOURS = (7, 19)  # local
ENV_FILE = ".config/logbook/sync.env"  # relative to the home directory; the owner's, never written here
LOG = ("Library", "Logs", "logbook-sync.log")  # launchd's stdout and stderr; launchd creates it, not we
ARGS = ("-m", "logbook.cli", "sync", "--scheduled")


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

    @property
    def tool(self) -> str:
        return self.activate[-1].args[0]


def system() -> str:
    return sys.platform


def plan(
    system: str,
    home: Path,
    python: str,
    logbook_home: Path | None = None,
    config_home: Path | None = None,
) -> Plan:
    """The files and commands for `system`: `darwin` a launchd agent, `linux` a systemd user timer.
    `python` is the interpreter the agent runs; `logbook_home` the record it is pointed at (none:
    the agent finds the record as the shell would); `config_home` overrides `~/.config` (Linux,
    `$XDG_CONFIG_HOME`). ScheduleError for any other platform."""
    if system == "darwin":
        return _launchd(home, python, logbook_home)
    if system == "linux":
        return _systemd(home, python, logbook_home, config_home)
    raise ScheduleError(f"no scheduler here for {system}: launchd (macOS) and systemd user timers (Linux)")


def _launchd(home: Path, python: str, logbook_home: Path | None) -> Plan:
    directory = home / "Library" / "LaunchAgents"
    path = directory / f"{LABEL}.plist"
    env_file = f'"$HOME/{ENV_FILE}"'
    script = (
        f"if [ -r {env_file} ]; then set -a; . {env_file}; set +a; fi; "
        f"exec {shlex.quote(python)} {' '.join(ARGS)}"
    )
    data: dict[str, object] = {
        "Label": LABEL,
        "ProgramArguments": ["/bin/sh", "-c", script],
        "StartCalendarInterval": [{"Hour": hour, "Minute": 0} for hour in HOURS],
        "RunAtLoad": False,
        "StandardOutPath": str(home.joinpath(*LOG)),
        "StandardErrorPath": str(home.joinpath(*LOG)),
    }
    if logbook_home is not None:
        data["EnvironmentVariables"] = {"LOGBOOK_HOME": str(logbook_home)}
    text = plistlib.dumps(data, sort_keys=False).decode("utf-8")
    domain = f"gui/{os.getuid() if hasattr(os, 'getuid') else 501}"
    return Plan(
        "darwin",
        directory,
        {path: text},
        (
            Command(("launchctl", "bootout", domain, str(path)), required=False),
            Command(("launchctl", "bootstrap", domain, str(path))),
        ),
        (Command(("launchctl", "bootout", domain, str(path)), required=False),),
    )


def _systemd(home: Path, python: str, logbook_home: Path | None, config_home: Path | None) -> Plan:
    directory = (config_home or home / ".config") / "systemd" / "user"
    exec_start = f"{_unit_quote(python)} {' '.join(ARGS)}"
    environment = f"Environment=LOGBOOK_HOME={logbook_home}\n" if logbook_home is not None else ""
    service = (
        "[Unit]\n"
        "Description=logbook sync --scheduled: every configured live source, then doctor, twice a day\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"EnvironmentFile=-%h/{ENV_FILE}\n"
        f"{environment}"
        f"ExecStart={exec_start}\n"
    )
    timer = (
        "[Unit]\n"
        f"Description=logbook sync --scheduled at {' and '.join(f'{h:02d}:00' for h in HOURS)} local\n"
        "\n"
        "[Timer]\n"
        f"OnCalendar=*-*-* {','.join(f'{h:02d}' for h in HOURS)}:00:00\n"
        "Persistent=true\n"
        f"Unit={UNIT}.service\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return Plan(
        "linux",
        directory,
        {directory / f"{UNIT}.service": service, directory / f"{UNIT}.timer": timer},
        (
            Command(("systemctl", "--user", "daemon-reload")),
            Command(("systemctl", "--user", "enable", "--now", f"{UNIT}.timer")),
        ),
        (Command(("systemctl", "--user", "disable", "--now", f"{UNIT}.timer")),),
    )


def _unit_quote(path: str) -> str:
    """A path in `ExecStart=`: double-quoted when it holds whitespace (systemd's own quoting)."""
    return f'"{path}"' if any(c.isspace() for c in path) else path


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
    """Whether every file `plan` names is there: the schedule is installed on this machine."""
    return all(path.exists() for path in plan.files)


def summary(plan: Plan) -> list[str]:
    """What was installed and where the secrets go, after the files."""
    when = " and ".join(f"{h:02d}:00" for h in HOURS)
    log = " (launchd; its output goes to ~/Library/Logs/logbook-sync.log)" if plan.system == "darwin" else ""
    return [
        f"installed: `logbook sync --scheduled` (`sync --all`, then `doctor`) runs at {when} local{log};"
        " the outcome goes to state/last-run.json and `logbook doctor` reads it",
        "to be told when something is wrong, put LOGBOOK_NOTIFY_TELEGRAM_TOKEN and"
        " LOGBOOK_NOTIFY_TELEGRAM_CHAT in the same file: one Telegram message when a source fails or doctor"
        " warns, and the week's counts on Sunday evening (docs/schedule.md)",
        f"the variables your live sources need go in ~/{ENV_FILE}, one KEY=value per line, mode 600;"
        " a source whose variables are not set is skipped",
    ]
