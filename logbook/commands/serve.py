"""The record served to a browser or an agent: `serve` and `mcp`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import serve
from ..store import Logbook
from .common import Subparsers, _airports


def serve_arguments(sub: Subparsers) -> None:
    """`logbook serve`."""
    s = sub.add_parser(
        "serve", help="read the record in a browser, from this machine only (http://127.0.0.1:8765/)"
    )
    s.add_argument(
        "--port", type=int, default=serve.PORT, metavar="N", help=f"the port (default {serve.PORT})"
    )
    s.add_argument(
        "--host", default=serve.HOST, help=f"must be {serve.HOST}; the server refuses any other host"
    )
    s.add_argument("--airports", metavar="FILE", help="an airports table that overrides the built-in one")
    s.set_defaults(fn=cmd_serve)


def cmd_serve(a: argparse.Namespace) -> None:
    """`serve [--port N]`: the record read in a browser, from this machine only (`logbook/serve.py`).
    Server-rendered pages from the index and the readers — the Day as a timeline, a window one row
    per day, the trips of a year, the places, the assets and their last fix, where each source went
    quiet — at http://127.0.0.1:8765/. Any other host is refused before a socket is opened; no page
    references a URL outside itself; nothing is written."""
    if a.host != serve.HOST:
        print(
            f"serve: binds {serve.HOST} only, never {a.host!r}: the record is read from this machine",
            file=sys.stderr,
        )
        sys.exit(2)
    lb = Logbook.find()
    try:
        serve.serve(lb, host=a.host, port=a.port, airports=_airports(a.airports))
    except serve.HostError as e:
        print(f"serve: {e}", file=sys.stderr)
        sys.exit(2)
    except OSError as e:
        print(f"serve: cannot listen on {a.host}:{a.port}: {e}", file=sys.stderr)
        sys.exit(2)


def mcp_arguments(sub: Subparsers) -> None:
    """`logbook mcp`."""
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
    stdin and stdout, nothing else open, until the host closes them (`logbook.mcp_server`; the
    tools and the ceiling are documented in `docs/mcp.md`). `--inspect` prints the tool table and
    one sample request and needs neither a record nor the `mcp` extra."""
    from .. import mcp_server

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
