"""The record's home (ADR 0022): the one machine that holds the only writable copy, runs the sync
schedule, the MCP server and the local models. `sync --install-schedule` on that machine writes
`<root>/state/home.json`, `{"host": "<hostname>", "since": "YYYY-MM-DD"}`, and `doctor` reads it:
the same host, or no home set, passes; another host is told that writers belong on the home. The
file is bookkeeping (`state/`, never in the chain, never in a backup) and a hostname is a name the
owner chose for a machine, not personal data. Home moves by copying the record once and installing
the schedule there, never by syncing; a second install on the same host keeps its date."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Any

HOME_FILE = PurePosixPath("state/home.json")  # record-relative


class HomeError(ValueError):
    """`state/home.json` is not the documented shape; the message names the file."""


@dataclass(frozen=True)
class Home:
    host: str
    since: date


def hostname() -> str:
    """This machine's name as the OS gives it. Tests replace it."""
    return socket.gethostname()


def today() -> date:
    return datetime.now().date()


def home_path(root: Path) -> Path:
    return Path(root).joinpath(*HOME_FILE.parts)


def same_machine(a: str, b: str) -> bool:
    """Two hostnames name one machine when their first labels match, case aside: `Nordlys-Home.local`
    is `nordlys-home`, as the OS reports the same machine both ways."""
    return _label(a) == _label(b)


def _label(host: str) -> str:
    return host.strip().casefold().split(".", 1)[0]


def read(root: Path) -> Home | None:
    """The home as written, or None when no home is set. A file that is not the shape raises
    HomeError naming it; nothing is written."""
    path = home_path(root)
    if not path.exists():
        return None
    shape = f'{path} must be {{"host": "<hostname>", "since": "YYYY-MM-DD"}}'
    try:
        data: Any = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as e:
        raise HomeError(f"{path} is not JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("host"), str) or not data["host"].strip():
        raise HomeError(shape)
    try:
        since = date.fromisoformat(data.get("since", ""))
    except (TypeError, ValueError):
        raise HomeError(shape) from None
    return Home(data["host"].strip(), since)


def write(root: Path, host: str | None = None, on: date | None = None) -> tuple[Home, Home | None]:
    """Make `host` (this machine) the record's home: the file written whole, the date kept when the
    same machine was the home already. Returns the home now and the home before, None for a record
    that had none."""
    host = hostname() if host is None else host
    on = today() if on is None else on
    try:
        before = read(root)
    except HomeError:
        before = None  # a file that is not the shape is bookkeeping, and is written over
    since = before.since if before is not None and same_machine(before.host, host) else on
    now = Home(host, since)
    path = home_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps({"host": now.host, "since": now.since.isoformat()}, indent=2) + "\n", encoding="utf-8"
    )
    tmp.replace(path)
    return now, before
