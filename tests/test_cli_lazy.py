"""`logbook/cli.py` is a thin entry point and `logbook --help` is cheap: neither imports an adapter or
a model module. The commands live in `logbook/commands/`, one family per module, and a family
imports an adapter (`logbook.contrib.adapters.*`) or a labs module (`judge`, `describe`, `transcribe`,
`demo_life`) inside the function that runs the command. Where the help text needs a constant from
one of them, the family keeps a copy, and this file holds the copy to the original."""

from __future__ import annotations

import subprocess
import sys
import warnings

import pytest

from logbook import cli, describe, judge, transcribe
from logbook.commands import add, day, derive, parser, promises, record
from logbook.contrib import setup
from logbook.contrib.adapters import screentime

ADAPTER_PREFIX = "logbook.contrib.adapters."
LABS = {"logbook.judge", "logbook.describe", "logbook.transcribe", "logbook.demo_life"}


def _modules_after(code: str) -> set[str]:
    """The `logbook` modules a fresh interpreter has imported once `code` has run."""
    script = (
        f"{code}\nimport sys\nprint('\\n'.join(sorted(m for m in sys.modules if m.startswith('logbook'))))"
    )
    out = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, encoding="utf-8")
    return set(out.stdout.split())


def test_importing_cli_imports_nothing_else() -> None:
    """The package itself (with the shim for the 0.5 import paths) and the entry point: no command."""
    assert _modules_after("import logbook.cli") == {
        "logbook",
        "logbook._shim",
        "logbook.layout",
        "logbook.cli",
    }


def test_help_imports_no_adapter_and_no_model_code() -> None:
    loaded = _modules_after(
        "import contextlib, io\n"
        "from logbook.commands.parser import build_parser\n"
        "with contextlib.redirect_stdout(io.StringIO()), contextlib.suppress(SystemExit):\n"
        "    build_parser().parse_args(['--help'])\n"
    )
    assert "logbook.commands.parser" in loaded
    assert not {m for m in loaded if m.startswith(ADAPTER_PREFIX)}, "an adapter module was imported"
    assert "logbook.contrib.adapters" not in loaded, "the adapter registry was imported"
    assert not (loaded & LABS), "a labs module was imported"


def test_every_command_runs_from_the_module_that_declares_it() -> None:
    """A command's `fn` lives in the family whose `<command>_arguments` registered it."""
    for arguments in parser.ARGUMENTS:
        family = sys.modules[arguments.__module__]
        command = arguments.__name__.removesuffix("_arguments")
        assert getattr(family, f"cmd_{command}").__module__ == arguments.__module__


def test_the_help_text_copies_match_their_originals() -> None:
    assert add.SCREENTIME_MAC_STORE == screentime.MAC_STORE
    assert add.SCREENTIME_PHONE_STORE == screentime.PHONE_STORE
    assert add.SCREENTIME_MAC_DEFAULT == screentime.MAC_DEFAULT
    assert derive.TRANSCRIBE_DEFAULT_MODEL == transcribe.DEFAULT_MODEL
    assert derive.DESCRIBE_DEFAULT_MODEL == describe.DEFAULT_MODEL
    assert promises.JUDGE_DEFAULT_MODEL == judge.DEFAULT_MODEL
    assert promises.JUDGE_EXTRA == judge.EXTRA
    assert record.SETUP_STEPS == setup.STEPS


def test_old_cli_names_still_resolve_with_a_warning() -> None:
    with pytest.warns(DeprecationWarning, match="logbook.cli.cmd_show moved to logbook.commands.day"):
        assert cli.cmd_show is day.cmd_show
    with pytest.warns(DeprecationWarning):
        assert cli.record_stats is record.record_stats
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert cli.main is not None  # a name that stayed warns about nothing
    with pytest.raises(AttributeError):
        cli.no_such_name  # noqa: B018
