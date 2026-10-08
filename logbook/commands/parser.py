"""The parser: every command's arguments, registered in the order `logbook --help` lists them, and
that help itself: one screen, the 22 commands in seven groups by what a person is doing, one line
each (the October 2026 audit, Decision 1).

A command's arguments live next to the command, in its family's module (`<command>_arguments`
beside `cmd_<command>`); this module only says which commands there are, in which group, and in
what order. A new command is one function pair in its family's module, one line in `ARGUMENTS`
and its name in `GROUPS`; a test holds the two lists to each other. An old name lives on in
`aliases.py`, never here."""

from __future__ import annotations

import argparse
import textwrap
from collections.abc import Callable
from typing import cast

from .. import __version__
from . import (
    add,
    day,
    derive,
    export,
    lab,
    people,
    promises,
    record,
    rollup,
    serve,
    sync,
)
from .common import Subparsers

#: the groups of `logbook --help`, in order: a header, then the commands under it
GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("start", ("init", "setup", "doctor")),
    ("write", ("add", "import", "sync")),
    ("read", ("show", "day", "digest", "search", "people", "rollup", "serve")),
    ("derive", ("derive", "promises")),
    ("keep", ("verify", "backup", "key", "repair")),
    ("share", ("export",)),
    ("try", ("demo", "lab")),
)

ARGUMENTS: tuple[Callable[[Subparsers], None], ...] = (
    record.init_arguments,
    record.setup_arguments,
    record.doctor_arguments,
    add.add_arguments,
    export.import_arguments,
    sync.sync_arguments,
    day.show_arguments,
    day.day_arguments,
    day.digest_arguments,
    day.search_arguments,
    people.people_arguments,
    rollup.rollup_arguments,
    serve.serve_arguments,
    derive.derive_arguments,
    promises.promises_arguments,
    record.verify_arguments,
    record.backup_arguments,
    record.key_arguments,
    record.repair_arguments,
    export.export_arguments,
    record.demo_arguments,
    lab.lab_arguments,
)

DESCRIPTION = "A diary that writes itself. `logbook <command> --help` explains one command."
USAGE = "logbook [--version] [--identity-file PATH] [--no-wait] <command> ..."  # one line, never wrapped
WIDTH = 80  # one screen: no line of the root help is wider


class _RootParser(argparse.ArgumentParser):
    """The root parser's help is one screen: the usage line, one sentence, the commands in their
    groups one line each with no wrapping, the root options. A command's own `--help` is argparse's
    (`parser_class` below keeps the subparsers plain)."""

    def format_help(self) -> str:
        (commands,) = (action for action in self._actions if action.dest == "cmd")
        choices = cast("argparse._SubParsersAction[argparse.ArgumentParser]", commands)._choices_actions
        helps = {choice.dest: choice.help or "" for choice in choices}
        width = max(len(name) for name in helps)
        lines = [self.format_usage().rstrip(), "", self.description or "", ""]
        for header, names in GROUPS:
            lines.append(header)
            lines.extend(f"  {name:<{width}}  {helps[name]}" for name in names)
        lines += ["", "options:"]
        options = [
            (
                ", ".join(action.option_strings) + (f" {action.metavar}" if action.metavar else ""),
                action.help or "",
            )
            for action in self._actions
            if action.option_strings
        ]
        flags_width = max(len(flags) for flags, _ in options)
        for flags, text in options:
            lines.extend(
                textwrap.wrap(
                    text,
                    WIDTH,
                    initial_indent=f"  {flags:<{flags_width}}  ",
                    subsequent_indent=" " * (flags_width + 4),
                )
            )
        return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    ap = _RootParser(prog="logbook", usage=USAGE, description=DESCRIPTION)
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument(
        "--identity-file",
        metavar="PATH",
        help="the age identity that opens the record, from `key init`",
    )
    ap.add_argument(
        "--no-wait",
        action="store_true",
        help="refuse, exit 2, while another command is writing",
    )
    sub = ap.add_subparsers(
        dest="cmd", required=True, metavar="<command>", parser_class=argparse.ArgumentParser
    )
    for arguments in ARGUMENTS:
        arguments(sub)
    return ap
