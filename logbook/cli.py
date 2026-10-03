"""`logbook <command>`: the entry point. The commands live in `logbook/commands/`, one family per
module; this module turns the arguments into a command, runs it, and gives the errors every
command shares one exit status. The names it imports are re-exported, so `from logbook.cli
import …` and `logbook.cli.<name>` keep working for what other code and the tests reach."""

from __future__ import annotations

import contextlib
import os
import sys
import zoneinfo

from . import __version__
from .commands.add import (
    PASSWORD_ENV,
    PATH_SUFFIXES,
    _plan_row,
    cmd_add,
    cmd_import_backup,
    cmd_inbox,
    looks_like_path,
)
from .commands.common import EM_DASH, EN_DASH
from .commands.day import cmd_day, cmd_days, cmd_digest, cmd_show, cmd_year
from .commands.derive import cmd_derive, cmd_infer, cmd_transcribe
from .commands.export import cmd_export
from .commands.keepers import cmd_keepers
from .commands.parser import build_parser
from .commands.people import cmd_people, cmd_person
from .commands.places import cmd_places
from .commands.promises import cmd_promises
from .commands.record import (
    _tz_default,
    cmd_backup,
    cmd_demo,
    cmd_doctor,
    cmd_index,
    cmd_init,
    cmd_migrate,
    cmd_repair,
    cmd_retract,
    cmd_stats,
    cmd_verify,
    health_days,
    record_stats,
)
from .commands.rollup import cmd_rollup
from .commands.serve import cmd_mcp, cmd_serve
from .commands.skips import LOCATION_SKIPS, NOTE_PHRASES, SKIP_PHRASES
from .commands.sync import cmd_assets, cmd_sources, cmd_sync
from .commands.trips import cmd_trips
from .store import FormatError

__all__ = [
    "EM_DASH",
    "EN_DASH",
    "LOCATION_SKIPS",
    "NOTE_PHRASES",
    "PASSWORD_ENV",
    "PATH_SUFFIXES",
    "SKIP_PHRASES",
    "__version__",
    "_plan_row",
    "_tz_default",
    "build_parser",
    "cmd_add",
    "cmd_assets",
    "cmd_backup",
    "cmd_day",
    "cmd_days",
    "cmd_demo",
    "cmd_derive",
    "cmd_digest",
    "cmd_doctor",
    "cmd_export",
    "cmd_import_backup",
    "cmd_inbox",
    "cmd_index",
    "cmd_infer",
    "cmd_init",
    "cmd_keepers",
    "cmd_mcp",
    "cmd_migrate",
    "cmd_people",
    "cmd_person",
    "cmd_places",
    "cmd_promises",
    "cmd_repair",
    "cmd_retract",
    "cmd_rollup",
    "cmd_serve",
    "cmd_show",
    "cmd_sources",
    "cmd_stats",
    "cmd_sync",
    "cmd_transcribe",
    "cmd_trips",
    "cmd_verify",
    "cmd_year",
    "health_days",
    "looks_like_path",
    "main",
    "record_stats",
]


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252; the CLI speaks UTF-8
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    a = build_parser().parse_args(argv)
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


if __name__ == "__main__":
    main()
