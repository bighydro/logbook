"""`logbook <command>`: the entry point. The commands live in `logbook/commands/`, one family per
module; this module turns the arguments into a command, runs it, and gives the errors every
command shares one exit status. Nothing but the standard library is imported until `main` runs,
so `import logbook.cli` is cheap and `logbook --help` loads no adapter and no model code
(`tests/test_cli_lazy.py` holds it to that).

A name that lived here before the split (`cmd_show`, `record_stats`, `SKIP_PHRASES`, ...) is still
reachable as `logbook.cli.<name>`, found in its family's module with a DeprecationWarning; it is a
copy of the binding, so patching it here changes nothing. Import it from `logbook.commands.<family>`
instead; `docs/migration-0.6.md` lists the moves."""

from __future__ import annotations

import contextlib
import os
import sys
import warnings
import zoneinfo
from importlib import import_module
from typing import Any

from . import __version__

__all__ = ["__version__", "main"]

FAMILIES = (
    "add",
    "common",
    "day",
    "derive",
    "export",
    "keepers",
    "parser",
    "people",
    "places",
    "promises",
    "record",
    "rollup",
    "rows",
    "serve",
    "skips",
    "sync",
    "trips",
)


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; the CLI speaks UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    from .commands.parser import build_parser  # every family's arguments, and nothing that runs one

    a = build_parser().parse_args(argv)
    from .store import FormatError  # the command just chosen has imported the store by now

    try:
        a.fn(a)
        sys.stdout.flush()  # a short listing sits in the buffer until exit: meet the closed pipe here
    except FormatError as e:  # verify and every writer refuse a record hashed by another rule
        print(f"{a.cmd}: {e}", file=sys.stderr)
        sys.exit(2)
    except zoneinfo.ZoneInfoNotFoundError as e:  # SPEC §2: a zone this host lacks is said, never swapped
        reason = e.args[0] if e.args else str(e)
        print(f"{a.cmd}: {reason}; this machine's zone database does not know it", file=sys.stderr)
        sys.exit(2)
    except BrokenPipeError:  # the reader went away (`| head`): stop quietly, status 0
        _stdout_to_devnull()
    except SystemExit:  # a command's own status (`sources --gaps` exits 1) stands; the pipe is still quiet
        _flush_quietly()
        raise


def _flush_quietly() -> None:
    """Flush stdout now, so a pipe whose reader is gone is seen here and not reported by the
    interpreter's final flush."""
    try:
        sys.stdout.flush()
    except BrokenPipeError:
        _stdout_to_devnull()


def _stdout_to_devnull() -> None:
    """Point stdout at the null device so the interpreter's final flush does not report the
    broken pipe on stderr and turn the exit status into 120. Python ignores SIGPIPE at start-up,
    so a write to a closed pipe is a BrokenPipeError, never a signal; this is where every reader
    meets it."""
    with contextlib.suppress(OSError, ValueError):  # no real file behind stdout (a test capture)
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def __getattr__(name: str) -> Any:
    """`logbook.cli.<name>` for a name the split moved into `logbook/commands/`: the first family
    that has it, with a DeprecationWarning naming where it lives now. Dunder names are never
    looked up, so the import system's probes stay quiet."""
    if name.startswith("__"):
        raise AttributeError(name)
    for family in FAMILIES:
        module = import_module(f"{__name__.rsplit('.', 1)[0]}.commands.{family}")
        if hasattr(module, name):
            warnings.warn(
                f"logbook.cli.{name} moved to logbook.commands.{family}.{name} in 0.6 and goes in 0.7",
                DeprecationWarning,
                stacklevel=2,
            )
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    main()
