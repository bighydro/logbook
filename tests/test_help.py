"""`logbook --help` is one screen (the October 2026 audit, Decision 1): 50 lines at most,
the 32 commands in their groups (RFC 0036 added `goal` and `chapter`, then `transcript`, RFC 0037
`review` and `status`, RFC 0041 `star` and `unstar`, and `with`, then `videos`), one line per command,
no prose paragraph; and the groups in `parser.py` name exactly the commands the parser has."""

from __future__ import annotations

import contextlib
import io
import re

from logbook import cli
from logbook.commands import parser

TOP_LEVEL = 32
# it prints 50: 40 until RFC 0036, 42 until `transcript`, 43 until `review` and `status`, 45 until
# `star`, `unstar` and `with`, 48 until `videos`, 49 until the line for a newcomer (#334)
MAX_LINES = 51
MAX_WIDTH = 80


def _help() -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["--help"])
    return out.getvalue()


def _commands() -> list[str]:
    (sub,) = (action for action in parser.build_parser()._actions if action.dest == "cmd")
    return list(sub.choices)


def test_there_are_thirty_two_commands() -> None:
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
    assert headers == [parser.DESCRIPTION, parser.NEW, *(header for header, _ in parser.GROUPS)]
    body = text.split("\noptions:")[0]
    assert "\n\n\n" not in body and all(len(line) < MAX_WIDTH * 2 for line in body.split("\n"))


def test_a_command_help_carries_its_description() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["setup", "--help"])
    assert "one question at a time, resumable" in out.getvalue()


def test_lab_hold_census_help_says_what_it_never_does() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["lab", "hold", "--help"])
    assert "nothing is moved, renamed, deleted or appended" in " ".join(out.getvalue().split())


def test_the_relationship_reader_says_its_entry_and_its_model() -> None:
    """`people` and `dream` name the relationship reader's entry and the model it asks (slice 1)."""
    for argv, said in ((["people", "--help"], "relationship"), (["dream", "--help"], "dream person NAME")):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
            cli.main(argv)
        text = " ".join(out.getvalue().split())
        assert said in text and "no model wired yet" not in text, argv


def test_a_newcomer_is_told_where_to_start_near_the_top() -> None:
    """#334: `--help` assumed the product's vocabulary and said nothing of where to begin."""
    lines = _help().split("\n")
    assert parser.NEW in lines[:6]
    assert "`logbook demo`" in parser.NEW and "`logbook setup`" in parser.NEW


def test_dream_names_every_kind_it_drafts() -> None:
    (line,) = [line for line in _help().split("\n") if line.startswith("  dream ")]
    assert all(kind in line for kind in ("day", "journey", "week", "person")), line


def test_init_help_describes_its_path_and_timezone() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["init", "--help"])
    text = " ".join(out.getvalue().split())
    assert "LOGBOOK_HOME" in text and "~/Logbook" in text, "where the record goes with no path"
    assert "--timezone ZONE" in text and "Europe/Oslo" in text
