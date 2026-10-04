"""Every old top-level command name still works (`logbook/commands/aliases.py`): it is absent from
`logbook --help`, prints exactly one line on stderr naming the new command, and then runs the new
command with the same arguments, printing the same bytes on stdout and exiting with the same status.
The record is the demo of `tests/test_cli_layout.py` (thirty days, seed 7), so every old form here
is also held, through its new form, to the fixtures written before the split."""

from __future__ import annotations

import contextlib
import io
import re
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from logbook import cli
from logbook.commands import aliases
from logbook.commands.parser import build_parser

DAYS, SEED = 30, 7

#: old name -> the arguments both forms run with on the demo record; every alias has one, so an
#: alias added without its proof fails `test_every_alias_has_a_sample`
SAMPLE: dict[str, tuple[str, ...]] = {
    "assets": ("list",),
    "attach": ("status",),
    "circle": (),
    "days": (),
    "describe": ("keepers", "--dry-run"),
    "import-backup": ("no-such-backup", "--dry-run"),
    "inbox": ("list",),
    "index": (),
    "infer": ("flights", "--dry-run"),
    "keepers": (),
    "ledger": (),
    "mcp": ("--inspect",),
    "migrate": (),
    "person": ("Ola Nordmann",),
    "places": ("list",),
    "questions": ("list",),
    "receive": ("no-such-page.zip",),
    "retract": ("999999", "a line that is not there"),
    "seal": (),
    "share": ("day", "2026-06-08", "--to", "nobody"),
    "sources": (),
    "stats": (),
    "tasks": (),
    "transcribe": ("voice-memos", "--dry-run"),
    "trip": ("trip:2026-06-08:2026-06-10",),
    "trips": (),
    "year": ("2026",),
}


@dataclass(frozen=True)
class Run:
    stdout: bytes
    stderr: str
    status: int


def _run(*argv: str) -> Run:
    out, err = io.StringIO(), io.StringIO()
    status = 0
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as e:
            status = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return Run(out.getvalue().encode("utf-8"), err.getvalue(), status)


@pytest.fixture(scope="module")
def demo_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("demo") / "Demo"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(root))
        _run("demo", "--days", str(DAYS), "--seed", str(SEED), "--out", str(root))
    return root


def _top_level() -> dict[str, object]:
    """The commands `logbook --help` offers, by name."""
    (subparsers,) = (action for action in build_parser()._actions if action.dest == "cmd")
    return dict(subparsers.choices)


def test_no_old_name_is_a_command_of_the_parser() -> None:
    assert not set(aliases.ALIASES) & set(_top_level())


def test_no_old_name_is_listed_by_help() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.suppress(SystemExit):
        cli.main(["--help"])
    # the command column: a name at the left, after two to four spaces; a wrapped line sits deeper
    listed = {m.group(1) for m in re.finditer(r"^ {2,4}([a-z][a-z-]*)(?:\s{2,}|$)", out.getvalue(), re.M)}
    assert not listed & set(aliases.ALIASES), sorted(listed & set(aliases.ALIASES))


def test_every_alias_names_a_command_that_exists() -> None:
    commands = _top_level()
    for old, new in aliases.ALIASES.items():
        assert new and new[0] in commands, (old, new)
        assert old != new[0] or len(new) > 1, (old, new)


def test_every_alias_has_a_sample() -> None:
    assert set(SAMPLE) == set(aliases.ALIASES)


def test_the_notice_is_one_line_naming_both_forms() -> None:
    for old, new in aliases.ALIASES.items():
        text = aliases.notice(old)
        assert "\n" not in text
        assert text == f"`logbook {old}` is now `logbook {' '.join(new)}`"


def test_rewrite_leaves_a_new_name_alone() -> None:
    assert aliases.rewrite(["show", "today"]) == (["show", "today"], None)
    assert aliases.rewrite(["--help"]) == (["--help"], None)
    assert aliases.rewrite([]) == ([], None)


def test_rewrite_keeps_the_root_options_in_front() -> None:
    if not aliases.ALIASES:
        pytest.skip("no alias yet")
    old, new = next(iter(aliases.ALIASES.items()))
    argv = ["--identity-file", "key.txt", old, "--json"]
    assert aliases.rewrite(argv) == (["--identity-file", "key.txt", *new, "--json"], aliases.notice(old))
    argv = ["--identity-file=key.txt", old]
    assert aliases.rewrite(argv) == (["--identity-file=key.txt", *new], aliases.notice(old))


@pytest.mark.parametrize("old", sorted(aliases.ALIASES))
def test_old_form_says_the_new_one_once_and_prints_the_same(
    old: str, demo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(demo_root))
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)  # `repair index` prints its elapsed time
    args = SAMPLE[old]
    _run(*aliases.ALIASES[old], *args)  # the index is built on the first read; neither form pays for it
    through_alias = _run(old, *args)
    new = _run(*aliases.ALIASES[old], *args)
    assert through_alias.stdout == new.stdout
    assert through_alias.status == new.status
    assert through_alias.stderr == aliases.notice(old) + "\n" + new.stderr
