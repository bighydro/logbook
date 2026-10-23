"""The record served to a browser or an agent: `serve` and `mcp`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ..contrib import phone, schedule, serve, service
from ..core import sealing
from ..core.flights import Airports
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
        "--build",
        action="store_true",
        help="build the Library's pages now and exit: what the server answers from (the 06:00 close and"
        " every act on a page build them too)",
    )
    s.add_argument(
        "--limit",
        type=float,
        default=serve.LIMIT_S,
        metavar="SECONDS",
        help=f"stop reading a page after this long and say so (default {serve.LIMIT_S:g}); with the pages"
        " built ahead, it is built in the background instead",
    )
    s.add_argument(
        "--live",
        action="store_true",
        help="render every page as it is asked for, never from the pages built ahead",
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
    references a URL outside itself; nothing is written but what the owner names on the Places page
    and reflects and signs on a Day, each through the CLI's own function, from this machine only; a
    Day hears a recording when this machine can (`day.voice`). `--install-service`, `--uninstall-service`
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
    if a.build:
        _build(Logbook.find(), _airports(a.airports))
        return
    from .day import voice  # whether a Day can hear a recording: asked once, now (labs, so here)

    lb = Logbook.find()
    try:
        serve.serve(
            lb,
            host=a.host,
            port=a.port,
            airports=_airports(a.airports),
            voice=voice(),
            built=not a.live,
            limit_s=max(1.0, a.limit),
        )
    except serve.HostError as e:
        print(f"serve: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"serve: cannot listen on {a.host}:{a.port}: {e}", file=sys.stderr)
        sys.exit(2)


def _build(lb: Logbook, airports: Airports | None) -> None:
    """`serve --build`: the Library's pages built now (`library_build.build`), said in one line; exit 1
    when a page failed (named), 75 when another process is building."""
    from ..contrib import library_build

    try:
        result = library_build.build(
            lb, serve.Site(lb, airports), say=lambda text: print(text, file=sys.stderr)
        )
    except library_build.Busy as e:
        print(f"serve: {e}; try again when it is done", file=sys.stderr)
        sys.exit(75)
    print(
        f"library: {result.pages:,} pages, {result.written:,} written, {result.removed:,} removed,"
        f" in {result.seconds} s ({library_build.folder_of(lb)})"
    )
    for target, why in sorted(result.failed.items()):
        print(f"  failed: {target}: {why}", file=sys.stderr)
    if result.failed:
        sys.exit(1)


def phone_arguments(sub: Subparsers) -> None:
    """`logbook setup phone [--origin URL --login LOGIN | --off]`: whether the owner's own phone may
    write through the Library, through Tailscale Serve (`logbook/contrib/phone.py`, docs/serve.md)."""
    s = sub.add_parser(
        "phone",
        help="let your own phone write through the Library, through Tailscale Serve (off by default)",
        description="let your own phone write through the Library (Reflect, With, Star, Sign and the"
        " shelves' forms) when `tailscale serve --bg 8765` puts it on your tailnet: --origin names the"
        " address the phone opens (https://<machine>.<tailnet>.ts.net), --login your tailnet login as"
        " `tailscale status` names it; written to logbook.json `phone` after your yes, typed at a"
        " terminal. --off removes it. Without a flag, says what is set",
    )
    s.add_argument(
        "--origin", metavar="URL", help="https://<machine>.<tailnet>.ts.net, as the phone opens it"
    )
    s.add_argument("--login", metavar="LOGIN", help="your tailnet login, e.g. ines@example.org")
    s.add_argument("--off", action="store_true", help="remove the setting: this machine only, as by default")
    s.set_defaults(fn=cmd_phone)


def cmd_phone(a: argparse.Namespace) -> None:
    """`setup phone`: what is set. `--origin URL --login LOGIN`: the setting printed as it will be
    written, then written to `logbook.json` under the writer lock after a yes typed at a terminal
    (never piped: the owner's word, not a script's or an agent's); every other key kept. `--off`:
    the key removed, every other kept. A setting, not a line: nothing is appended and no hash changes."""
    if a.off and (a.origin is not None or a.login is not None):
        print("setup phone: --off takes no --origin or --login; nothing changed", file=sys.stderr)
        sys.exit(2)
    if (a.origin is None) != (a.login is None):
        print(
            "setup phone: --origin and --login go together, the address the phone opens and your tailnet"
            " login; nothing changed",
            file=sys.stderr,
        )
        sys.exit(2)
    lb = Logbook.find()
    current = lb.meta.get(phone.KEY)
    if a.off:
        if current is None:
            print("no phone in logbook.json: the Library is written from this machine only; nothing changed")
            return
        with lb.writer():
            meta = lb.meta
            meta.pop(phone.KEY, None)
            lb._save_meta(meta)
        print("phone: removed from logbook.json; the Library is written from this machine only again")
        return
    if a.origin is None:
        problem = phone.problem(lb.meta)
        if current is None:
            print(
                "the Library is written from this machine only (no phone in logbook.json); `logbook setup"
                " phone --origin URL --login LOGIN` lets your phone write through Tailscale Serve"
            )
        elif problem is not None:
            print(f"logbook.json phone lets nothing in: {problem}; `logbook setup phone` writes it again")
        else:
            print(f"your phone may write from {current['origin']} as {current['login']} (logbook.json phone)")
        return
    try:
        setting = {"origin": phone.origin_of(a.origin), "login": phone.login_of(a.login)}
    except phone.PhoneError as e:
        print(f"setup phone: {e}", file=sys.stderr)
        sys.exit(2)
    if current == setting:
        print(f"your phone may already write from {setting['origin']} as {setting['login']}; nothing changed")
        return
    if not sys.stdin.isatty():
        print("setup phone: asks for your yes, typed at a terminal; nothing changed", file=sys.stderr)
        sys.exit(2)
    print(f"setup phone will write to {lb.meta_path.name}:")
    print(f"  {json.dumps({phone.KEY: setting}).strip('{}')}")
    print(
        f"The Library then answers a form posted from {setting['origin']}, through Tailscale Serve on this"
        f" machine and by {setting['login']}, as it answers this machine's own pages."
    )
    try:
        answer = input("Write it? [y/N]: ").strip().casefold()
    except EOFError:
        answer = ""
    if answer not in ("y", "yes"):
        print("nothing changed")
        return
    with lb.writer():
        lb.set_meta(**{phone.KEY: setting})
    print(
        f"phone: {setting['origin']} as {setting['login']} in logbook.json;"
        " `logbook setup phone --off` removes it"
    )


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
            continue
        silent = True
        if service.probe(item.port) == service.NOT_ANSWERING:
            restart = service.restart_command(item) or service.restart_by_hand(item)
            print(
                f"not answering at {address}: it takes the connection and says nothing in"
                f" {service.PROBE_TIMEOUT_S:g} s; `{restart.text}` restarts it (the scheduled run does);"
                f" its output: {item.log}"
            )
        else:
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
