"""What a stranger reads names commands that exist: every `logbook ...` in the README, the root pages,
docs/ and the changelog fragments is held to the parser of today's code (`build_parser`), the same one
`logbook <command> --help` prints.

Three places are read: a fenced line that starts with `logbook` (after `$ `, `uv run ` or a
`NAME=value` prefix, and after each `;`, `&&` or `|`); a code span that starts with `logbook `; and a
code span without the prefix whose first word is a command (an old name there is a word, not read)
and that passes a `--flag` (`serve --tier`). A line of program output inside a fence starts with
something else, so it is not read: the docs show what the code prints, and that is the code's to
change. In a fence not labelled as a shell, a line that starts `logbook` is read when it has a `$ `
prompt or its next word is a command, since such a fence also holds output (`logbook week to ...`,
a message's subject).

What is held: the command exists, each word after it that names a subcommand names one that exists,
and every `--flag` belongs to the command it is given to (or to `logbook` itself). An old name
(`logbook/commands/aliases.py`) is drift unless the page says it on purpose, once (`OLD_NAME_SAID`),
or the page is SPEC.md, whose wording changes in a pull request of its own (`OLD_NAMES_WAIT`).
A repository path in a code span (`docs/...`, `logbook/...`, ...) exists.

Not read: history, which was true when it was written (docs/rfcs, docs/adr, docs/letters, the
changelog, the release notes, the October audit, the 0.6 migration), the old-to-new table of
docs/commands.md, which `tests/test_aliases.py` holds to the code, and CLAUDE.md, which is for agents."""

from __future__ import annotations

import argparse
import re
import shlex
from collections.abc import Iterator
from pathlib import Path

import pytest

from logbook.commands.aliases import ALIASES
from logbook.commands.parser import build_parser

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIRS = frozenset({"rfcs", "adr", "letters", "conformance"})
HISTORY_FILES = frozenset(
    {"CHANGELOG.md", "CLAUDE.md", "release-notes.md", "audit-2026-10.md", "migration-0.6.md", "README.md"}
)
#: a page that names an old command on purpose (it was X before 0.6; X still works), once each
OLD_NAME_SAID: frozenset[tuple[str, str]] = frozenset(
    {
        ("docs/mcp.md", "mcp"),
        ("docs/print.md", "year"),
        ("docs/print.md", "trip"),
        ("docs/places.md", "places"),
        ("docs/adapters/voice-memos.md", "transcribe"),
    }
)
#: pages whose old names wait for their own change: SPEC.md moves only with its own pull request
OLD_NAMES_WAIT = frozenset({"SPEC.md"})
REPO_DIRS = ("docs", "scripts", "tests", "logbook", "homebrew", "adapters", "conformance", "schema", "rfcs")
REPO_PATH = re.compile(r"`((?:" + "|".join(REPO_DIRS) + r"|changelog\.d)/[\w./-]*[\w/])`")
ALIASES_START, ALIASES_END = "<!-- aliases:start -->", "<!-- aliases:end -->"
SHELLS = frozenset({"bash", "sh", "shell", "console", "zsh", "powershell"})
ENV = re.compile(r"^[A-Z_][A-Z0-9_]*=\S*$")


def _pages() -> list[Path]:
    """The pages a stranger reads, each once (docs/ holds links to some root pages)."""
    found = [*sorted(ROOT.glob("*.md")), ROOT / "README.md", ROOT / "adapters" / "README.md"]
    found += sorted((ROOT / "docs").rglob("*.md")) + sorted((ROOT / "changelog.d").glob("*.md"))
    pages: dict[Path, Path] = {}
    for page in found:
        rel = page.relative_to(ROOT)
        if HISTORY_DIRS & set(rel.parts[:-1]) or page.is_symlink():
            continue
        if page.name in HISTORY_FILES and rel not in (Path("README.md"), Path("adapters", "README.md")):
            continue
        pages.setdefault(page.resolve(), page)
    return sorted(pages.values())


def _subparsers(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction[argparse.ArgumentParser] | None:
    found = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    return found[0] if found else None


def _options(parser: argparse.ArgumentParser) -> set[str]:
    return {o for a in parser._actions for o in a.option_strings}


PARSER = build_parser()
_TOP = _subparsers(PARSER)
assert _TOP is not None
COMMANDS: dict[str, argparse.ArgumentParser] = dict(_TOP.choices)


def problems(words: list[str]) -> Iterator[str]:
    """What is wrong with `logbook <words>`: an unknown command, subcommand or flag, or an old name."""
    while words and words[0].startswith("-"):  # the root options before the command
        words = words[2:] if words[0] == "--identity-file" else words[1:]
    if not words or not re.fullmatch(r"[a-z][a-z-]*", words[0]):
        return
    command, rest = words[0], words[1:]
    if command in ALIASES:
        yield f"old name `{command}`: `{' '.join(ALIASES[command])}`"
        command, rest = ALIASES[command][0], [*ALIASES[command][1:], *rest]
    if command not in COMMANDS:
        yield f"no command `{command}`"
        return
    parser, path = COMMANDS[command], [command]
    actions = {**PARSER._option_string_actions, **parser._option_string_actions}
    rest = [w.strip("[]()") for w in rest if w.strip("[]()|")]
    i = 0
    while i < len(rest):
        word = rest[i]
        i += 1
        if word.startswith("--"):
            flag, _, value = word.partition("=")
            if flag == "--":
                continue
            if flag not in actions:
                yield f"`{' '.join(path)}` has no `{flag}`"
                continue
            nargs = actions[flag].nargs
            if value or nargs == 0:
                continue
            values = len(list(_values(rest[i:])))
            if nargs in ("+", "*"):
                i += values
            else:  # one value (None, "?") or a fixed number of them
                i += min(1 if nargs in (None, "?") else int(nargs), values)
            continue
        sub = _subparsers(parser)
        if sub is None or word.startswith("-"):
            continue
        if word in sub.choices:
            parser = sub.choices[word]
            path.append(word)
            actions.update(parser._option_string_actions)
        elif re.fullmatch(r"[a-z][a-z-]+", word):
            yield f"`{' '.join(path)}` has no `{word}`"
            return
        else:
            return  # a value (a path, a date): the subcommand was left out, which a mention may do


def _values(words: list[str]) -> Iterator[str]:
    """The words up to the next option: the values a flag may take."""
    for word in words:
        if word.startswith("-"):
            return
        yield word


def _words(text: str) -> list[str]:
    text = text.split(" #")[0].rstrip("\\ ")
    try:
        return shlex.split(text)
    except ValueError:  # an unclosed quote in a mention
        return text.split()


def invocations(text: str) -> Iterator[tuple[int, list[str]]]:
    """(line number, the words after `logbook`) for each place a page runs or names a command."""
    fenced, shell = False, False
    lines = text.splitlines()
    skip = set()
    if ALIASES_START in text:
        start = next(i for i, line in enumerate(lines) if ALIASES_START in line)
        end = next(i for i, line in enumerate(lines) if ALIASES_END in line)
        skip = set(range(start, end + 1))
    for n, line in enumerate(lines, 1):
        if n - 1 in skip:
            continue
        if line.lstrip().startswith("```"):
            fenced = not fenced
            shell = line.strip().removeprefix("```") in SHELLS
            continue
        if fenced:
            prompt = line.strip().startswith("$ ")
            for part in re.split(r"\s*(?:;|&&|\|)\s*", line.strip().removeprefix("$ ")):
                words = _words(part.lstrip("("))
                while words and (ENV.match(words[0]) or words[0] in {"uv", "run", "sudo"}):
                    words = words[1:]
                if words[:1] != ["logbook"]:
                    continue
                named = len(words) > 1 and (
                    words[1] in COMMANDS or words[1] in ALIASES or words[1].startswith("-")
                )
                if shell or prompt or named:
                    yield n, words[1:]
            continue
        for span in re.findall(r"`([^`]+)`", line):
            words = _words(span.removeprefix("uv run "))
            if words[:1] == ["logbook"]:
                yield n, words[1:]
            elif words and words[0] in COMMANDS and any(w.startswith("--") for w in words):
                yield n, words


def test_the_pages_are_found() -> None:
    names = {p.relative_to(ROOT).as_posix() for p in _pages()}
    assert {"README.md", "docs/install.md", "docs/mcp.md", "adapters/README.md"} <= names
    assert not any(name.startswith("docs/rfcs/") for name in names)


def test_the_checker_finds_what_it_is_for() -> None:
    assert list(problems(["serve", "--tier", "1"])) == ["`serve` has no `--tier`"]
    assert list(problems(["year", "2026"])) == ["old name `year`: `show year`"]
    assert list(problems(["import", "nothing-here"])) == ["`import` has no `nothing-here`"]
    assert list(problems(["key", "circle", "add", "ola", "--frob"])) == ["`key circle add` has no `--frob`"]
    assert not list(problems(["serve", "mcp", "--inspect"]))
    assert not list(problems(["--identity-file", "~/id.txt", "show", "year", "2026", "--html", "x.html"]))
    sample = "\n".join(
        [
            "x",
            "```bash",
            "LOGBOOK_HOME=~/L logbook serve --port 1  # here",
            "  the command: logbook old",
            "```",
        ]
    )
    sample += "\n`demo --out D`"
    assert list(invocations(sample)) == [(3, ["serve", "--port", "1"]), (6, ["demo", "--out", "D"])]


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_command_a_page_names_exists(page: Path) -> None:
    rel = page.relative_to(ROOT).as_posix()
    found = []
    said = set()
    for n, words in invocations(page.read_text(encoding="utf-8")):
        for problem in problems(words):
            old = re.match(r"old name `([a-z-]+)`", problem)
            if old and rel in OLD_NAMES_WAIT:
                continue
            if old and (rel, old.group(1)) in OLD_NAME_SAID and old.group(1) not in said:
                said.add(old.group(1))
                continue
            found.append(f"{rel}:{n}: {problem}  [logbook {' '.join(words)[:80]}]")
    assert not found, "\n".join(found)


@pytest.mark.parametrize("page", _pages(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_repository_path_a_page_names_exists(page: Path) -> None:
    rel = page.relative_to(ROOT).as_posix()
    missing = []
    for n, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
        for match in REPO_PATH.finditer(line):
            parts = match.group(1).split("/")
            if parts[0] == "logbook" and re.fullmatch(r"\d.*", parts[1]):  # `logbook/0.3`, a format name
                continue
            if not (ROOT.joinpath(*parts).exists() or page.parent.joinpath(*parts).exists()):
                missing.append(f"{rel}:{n}: no `{match.group(1)}`")
    assert not missing, "\n".join(missing)


def test_every_old_name_said_on_purpose_is_still_said() -> None:
    """An entry of `OLD_NAME_SAID` whose page no longer names the old command goes too."""
    stale = []
    for rel, old in sorted(OLD_NAME_SAID):
        text = ROOT.joinpath(*rel.split("/")).read_text(encoding="utf-8")
        if not any(words[:1] == [old] for _, words in invocations(text)):
            stale.append(f"{rel}: `logbook {old}`")
    assert not stale, stale
