"""`logbook --help` is one screen (the October 2026 audit, Decision 1): under 40 lines, the 22
commands in their groups, one line per command, no prose paragraph; and the groups in `parser.py`
name exactly the commands the parser has."""

from __future__ import annotations

import contextlib
import io
import re

from logbook import cli
from logbook.commands import parser

TOP_LEVEL = 22
MAX_LINES = 40
MAX_WIDTH = 80


def _help() -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["--help"])
    return out.getvalue()


def _commands() -> list[str]:
    (sub,) = (action for action in parser.build_parser()._actions if action.dest == "cmd")
    return list(sub.choices)


def test_there_are_twenty_two_commands() -> None:
    assert len(_commands()) == TOP_LEVEL, _commands()


def test_every_command_is_in_exactly_one_group_and_the_groups_name_nothing_else() -> None:
    grouped = [name for _, names in parser.GROUPS for name in names]
    assert sorted(grouped) == sorted(set(grouped)), "a command in two groups"
    assert sorted(grouped) == sorted(_commands())


def test_help_fits_one_screen() -> None:
    lines = _help().rstrip("\n").split("\n")
    assert len(lines) < MAX_LINES, len(lines)
    long = [line for line in lines if len(line) > MAX_WIDTH]
    assert not long, long


def test_help_lists_every_command_once_under_its_group_and_no_paragraph() -> None:
    text = _help()
    listed = re.findall(r"^  ([a-z][a-z-]*)\s{2,}\S", text, re.M)
    assert listed == [name for _, names in parser.GROUPS for name in names]
    headers = [line for line in text.split("\n") if line and not line.startswith((" ", "usage:", "options:"))]
    assert headers == [parser.DESCRIPTION, *(header for header, _ in parser.GROUPS)]
    body = text.split("\noptions:")[0]
    assert "\n\n\n" not in body and all(len(line) < MAX_WIDTH * 2 for line in body.split("\n"))


def test_a_command_help_carries_its_description() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["setup", "--help"])
    assert "one question at a time, resumable" in out.getvalue()
