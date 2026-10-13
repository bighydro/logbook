"""The record served to a browser or an agent: `serve` and `mcp`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ..contrib import schedule, serve, service
from ..core import sealing
from ..core.store import Logbook
from .common import Subparsers, _airports


def serve_arguments(sub: Subparsers) -> None:
    """`logbook serve [mcp]`: the record read in a browser, or served to an agent (`mcp`, a command of
    its own until 0.6)."""
    s = sub.add_parser(
        "serve",
        help="the record in a browser, from this machine only; mcp: to an agent",
        description="read the record in a browser, from this machine only (http://127.0.0.1:8765/); `mcp`:"
        " serve it"
        " to an MCP host over stdin and stdout",
    )
    s.add_argument(
        "--port", type=int, default=serve.PORT, metavar="N", help=f"the port (default {serve.PORT})"
    )
    s.add_argument(
        "--host", default=serve.HOST, help=f"must be {serve.HOST}; the server refuses any other host"
    )
    s.add_argument("--airports", metavar="FILE", help="an airports table that overrides the built-in one")
    s.add_argument(
        "--install-service",
        action="store_true",
        help="keep `serve --port N` running from load, started again when it fails: a launchd agent (macOS)"
        " or a systemd user service (Linux), printed before it is written; the output beside the sync log",
    )
    s.add_argument("--uninstall-service", action="store_true", help="stop that service and remove it")
    s.add_argument(
        "--system",
        action="store_true",
        help="with --install-service or --uninstall-service: a daemon of the system domain that runs as you"
        " from boot, for a machine nobody logs in to; written to your home directory, and the sudo commands"
        " that install or remove it printed, never run",
    )
    s.add_argument(
        "--status",
        action="store_true",
        help="whether a serve service is installed and answers; exit 0 answering, 1 installed and not"
        " answering, 3 none installed",
    )
    s.set_defaults(fn=cmd_serve)
    hosts = s.add_subparsers(dest="host_kind", required=False, metavar="<to>")
    mcp_arguments(hosts)


def cmd_serve(a: argparse.Namespace) -> None:
    """`serve [--port N]`: the record read in a browser, from this machine only (`logbook/contrib/serve.py`).
    Server-rendered pages from the index and the readers — the Day as a timeline, a window one row
    per day, the trips of a year, the places, the assets and their last fix, where each source went
    quiet — at http://127.0.0.1:8765/. Any other host is refused before a socket is opened; no page
    references a URL outside itself; nothing is written. `--install-service`, `--uninstall-service`
    and `--status`: the same server kept running by the machine's service manager (`_service`)."""
    if a.host != serve.HOST:
        print(
            f"serve: binds {serve.HOST} only, never {a.host!r}: the record is read from this machine",
            file=sys.stderr,
        )
        sys.exit(2)
    if a.install_service or a.uninstall_service or a.status or a.system:
        _service(a)
        return
    lb = Logbook.find()
    try:
        serve.serve(lb, host=a.host, port=a.port, airports=_airports(a.airports))
    except serve.HostError as e:
        print(f"serve: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"serve: cannot listen on {a.host}:{a.port}: {e}", file=sys.stderr)
        sys.exit(2)


def _service(a: argparse.Namespace) -> None:
    """`serve --install-service [--system]`: the server kept running by launchd or systemd
    (`logbook.contrib.service`), the file printed before it is written. Without `--system` it is
    the user's, written under LaunchAgents or the systemd user directory and handed to the service
    manager, as `sync --install-schedule` does; with `--system` it is written to the home directory
    and the sudo commands that install it are printed, never run. `--uninstall-service` the
    reverse; `--status` whether one is installed and answers (exit 0, 1 installed and silent, 3
    none)."""
    chosen = [
        flag
        for flag, on in (
            ("--install-service", a.install_service),
            ("--uninstall-service", a.uninstall_service),
            ("--status", a.status),
        )
        if on
    ]
    if len(chosen) != 1:
        print("serve: one of --install-service, --uninstall-service or --status", file=sys.stderr)
        sys.exit(2)
    flag = chosen[0]
    if a.system and a.status:
        print(
            "serve: --status looks for both; --system goes with --install-service or --uninstall-service",
            file=sys.stderr,
        )
        sys.exit(2)
    xdg = os.environ.get("XDG_CONFIG_HOME", "").strip()
    config_home = Path(xdg).expanduser() if xdg else None
    platform, home = service.system(), Path.home()
    if a.status:
        _service_status(platform, home, config_home, a.port)
        return
    if a.system and service.running_as_root():
        print(
            f"serve: {flag} --system: run it as the user the server is to run as, not as root; it prints the"
            " sudo commands itself",
            file=sys.stderr,
        )
        sys.exit(2)
    lb = Logbook.find() if a.install_service else None
    identity = os.environ.get(sealing.IDENTITY_ENV, "").strip()
    try:
        svc = service.plan(
            platform,
            home,
            sys.executable,
            lb.root if lb is not None else None,
            a.port,
            system_wide=a.system,
            user=service.user_name() if a.system else None,
            config_home=config_home,
            identity_file=Path(identity).expanduser() if identity else None,
            airports=Path(a.airports).expanduser().resolve() if a.airports else None,
        )
    except service.ServiceError as e:
        print(f"serve: {flag}: {e}", file=sys.stderr)
        sys.exit(2)
    if a.uninstall_service:
        _service_uninstall(svc, home, config_home)
        return
    replacing = svc.path.is_file()
    schedule.install(svc.plan, print)
    for line in service.summary(svc, replacing=replacing):
        print(line)
    for other in service.find(platform, home, config_home):
        if other.path != svc.path:
            shown = service.shown(other.path, home)
            print(
                f"note: a {other.kind} is installed too ({shown}, port {other.port}); two servers on one"
                " port: remove the one you do not want"
            )
    if svc.system_wide:
        return
    problem = schedule.run(svc.plan.activate, svc.plan.tool, print)
    if problem is not None:
        print(f"serve: {flag}: {problem}", file=sys.stderr)
        sys.exit(1)


def _service_uninstall(svc: service.Service, home: Path, config_home: Path | None) -> None:
    """The user's service: stopped by its manager, its file unlinked. A system service: the copy in
    the home directory unlinked, and the sudo commands that stop it and remove the system's copy
    printed, never run."""
    if svc.system_wide:
        removed = schedule.uninstall(svc.plan)
        for path in removed:
            print(f"removed {path}")
        if not svc.path.is_file():
            if not removed:
                print(f"no serve service installed ({svc.path})")
            return
        print(f"the {svc.kind} is installed at {svc.path}; to stop and remove it, as an administrator:")
        for command in svc.remove_by_hand:
            print(f"  {command.text}")
        return
    if not svc.path.is_file():
        print(f"no serve service installed ({service.shown(svc.path, home)})")
        for other in service.find(svc.plan.system, home, config_home):
            if other.path != svc.path:
                print(
                    f"a {other.kind} is: `logbook serve --uninstall-service --system` says how to remove it"
                )
        return
    problem = schedule.run(svc.plan.deactivate, svc.plan.tool, print)
    for path in schedule.uninstall(svc.plan):
        print(f"removed {path}")
    if problem is not None:
        print(f"serve: --uninstall-service: {problem}", file=sys.stderr)
        sys.exit(1)


def _service_status(platform: str, home: Path, config_home: Path | None, port: int) -> None:
    """One line per serve service installed, and whether a logbook server answers on its port.
    Exit 0 when every one installed answers, 1 when one does not, 3 when none is installed (and
    then whether one run by hand answers on `port`)."""
    found = service.find(platform, home, config_home)
    if not found:
        print("no serve service installed; `logbook serve --install-service` (docs/serve.md)")
        if service.answering(port):
            print(f"a logbook server answers at http://{serve.HOST}:{port}/ (run by hand)")
        sys.exit(3)
    silent = False
    for item in found:
        print(f"installed: a {item.kind} ({service.shown(item.path, home)}), port {item.port}")
        address = f"http://{serve.HOST}:{item.port}/"
        if service.answering(item.port):
            print(f"answering at {address}")
        else:
            silent = True
            print(f"nothing answers at {address}; its output: {item.log}")
    if silent:
        sys.exit(1)


def mcp_arguments(sub: Subparsers) -> None:
    """`logbook serve mcp` (`logbook mcp` until 0.6)."""
    s = sub.add_parser(
        "mcp",
        help="serve the record to an MCP host over stdin and stdout; every tool behind the mcp ceiling of"
        " policy/crossing.json (docs/mcp.md)",
    )
    s.add_argument("--root", metavar="DIR", help="logbook folder (default: find)")
    s.add_argument(
        "--allow-tier-3",
        action="store_true",
        help="let tier 3 cross when policy/crossing.json allows it for mcp; without this flag 2 is the most",
    )
    s.add_argument(
        "--inspect", action="store_true", help="print the tool list and a sample call; serve nothing"
    )
    s.set_defaults(fn=cmd_mcp)


def cmd_mcp(a: argparse.Namespace) -> None:
    """`mcp [--root DIR] [--allow-tier-3]`: serve the record to an MCP host over this process's
    stdin and stdout, nothing else open, until the host closes them (`logbook.contrib.mcp_server`; the
    tools and the ceiling are documented in `docs/mcp.md`). `--inspect` prints the tool table and
    one sample request and needs neither a record nor the `mcp` extra."""
    from ..contrib import mcp_server

    if a.inspect:
        print(mcp_server.inspect_text())
        return
    lb = Logbook(Path(a.root).expanduser()) if a.root else Logbook.find()
    if not lb.meta_path.exists():
        print(f"mcp: {lb.root} is not a logbook (no logbook.json)", file=sys.stderr)
        sys.exit(2)
    try:
        mcp_server.serve(lb.root, allow_tier_3=a.allow_tier_3)
    except ImportError as e:
        print(f"mcp: {e}", file=sys.stderr)
        sys.exit(2)
