"""The old names of the commands, and where each lives now (the October 2026 audit, Decision 1:
46 top-level commands became 22; every old name stays as a hidden alias).

`ALIASES` is the one list: `old top-level name -> the words of the new command`. It is read by
`rewrite`, which `logbook.cli.main` runs on the arguments before they are parsed; by the test that
holds every old form to its new one (`tests/test_aliases.py`); and by `scripts/command_aliases.py`,
which writes the table in `docs/commands.md`. An old name is not in the parser at all, so
`logbook --help` never shows it; `logbook <old> ...` prints one line on stderr naming the new
command, then runs it with the same arguments and the same exit status.

A name is removed from this table only with a major version."""

from __future__ import annotations

ALIASES: dict[str, tuple[str, ...]] = {
    "attach": ("import", "attachments"),
    "days": ("show", "days"),
    "import-backup": ("import", "backup"),
    "inbox": ("import", "inbox"),
    "keepers": ("show", "keepers"),
    "receive": ("import", "page"),
    "stats": ("show", "stats"),
    "trip": ("show", "trip"),
    "trips": ("show", "trips"),
    "year": ("show", "year"),
}

# The root options that may stand before the command: the ones that take a value, and the flags.
_ROOT_OPTIONS_WITH_VALUE = frozenset({"--identity-file"})
_ROOT_FLAGS = frozenset({"-h", "--help", "--version"})


def notice(old: str) -> str:
    """The one line `logbook <old>` prints on stderr before it runs the new command."""
    return f"`logbook {old}` is now `logbook {' '.join(ALIASES[old])}`"


def command_index(argv: list[str]) -> int | None:
    """Where the command word stands in `argv`: after the root options, if any; None when there is
    none (argparse then says so itself)."""
    i = 0
    while i < len(argv):
        word = argv[i]
        if word in _ROOT_OPTIONS_WITH_VALUE:
            i += 2
            continue
        if word in _ROOT_FLAGS or (word.startswith("--") and "=" in word):  # --identity-file=PATH
            i += 1
            continue
        return i
    return None


def rewrite(argv: list[str]) -> tuple[list[str], str | None]:
    """`argv` with an old command name replaced by the words of the new command, and the notice to
    print; `argv` as given and None when the command is not an old name."""
    i = command_index(argv)
    if i is None or argv[i] not in ALIASES:
        return argv, None
    old = argv[i]
    return [*argv[:i], *ALIASES[old], *argv[i + 1 :]], notice(old)
