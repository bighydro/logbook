"""pre-commit hook: fail the commit when a diff adds a line that matches one of the owner's personal
identifiers. Stdlib only.

The identifiers are never in the repository. They live in the file `LOGBOOK_PII_PATTERNS` names, default
`~/.config/logbook/pii-patterns`: one case-insensitive regular expression per line, blank lines and `#`
comments ignored. A pattern's name is its first named group, `(?P<phone>...)`, or else `line N`, its line
in the file. Without the file (CI, a stranger's checkout) the hook warns and passes.

What it reads:
- by default, the added lines of the staged diff: what a commit is about to record;
- with `--from-ref A --to-ref B`, or the `PRE_COMMIT_FROM_REF` and `PRE_COMMIT_TO_REF` that
  `pre-commit run --from-ref A --to-ref B` sets, the added lines of `git diff A..B`: nothing is staged
  then, and the staged diff would be empty;
- with `--tree REF`, every line of every file tracked at REF, for a sweep of a whole branch.
The files pre-commit hands over narrow any of the three.

On a match it prints `<file>:<line>: matches pattern <name>` for every line that matched, never the text
and never the pattern, and exits 1. Every run ends with one line, `check-pii: 18 patterns, 9879 lines,
0 matches in <what>`; zero patterns or zero lines is that line as a warning on stderr, so a run that checked
nothing never reads as a clean one. A bad ref or a pattern that does not compile is one line and exit 2.

Usage: `check_pii.py [--from-ref A --to-ref B | --tree REF] [FILE ...]`"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

DEFAULT = Path("~") / ".config" / "logbook" / "pii-patterns"
DIFF = ("diff", "--no-color", "--no-ext-diff", "-U0")


@dataclass(frozen=True)
class Pattern:
    name: str
    regex: re.Pattern[str]


class Refused(Exception):
    """A ref git does not know, a pattern that does not compile: one line on stderr and exit 2."""


def patterns_file() -> Path:
    named = os.environ.get("LOGBOOK_PII_PATTERNS")
    return Path(named).expanduser() if named else DEFAULT.expanduser()


def load_patterns(path: Path) -> list[Pattern]:
    out: list[Pattern] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            regex = re.compile(line, re.IGNORECASE)
        except re.error:
            raise Refused(f"line {number} of {path} is not a regular expression") from None
        groups = sorted(regex.groupindex, key=regex.groupindex.__getitem__)
        out.append(Pattern(groups[0] if groups else f"line {number}", regex))
    return out


def git(*args: str, stdin: bytes | None = None) -> bytes:
    r = subprocess.run(["git", *args], input=stdin, capture_output=True)
    if r.returncode != 0:
        why = r.stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise Refused(f"git {args[0]} failed: {why[0] if why else f'exit {r.returncode}'}")
    return r.stdout


def resolve(ref: str, kind: str) -> str:
    """The object name of `ref` as a commit or a tree, so that what reaches `git diff` is never an option."""
    r = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", "--end-of-options", f"{ref}^{{{kind}}}"],
        capture_output=True,
        encoding="utf-8",
    )
    if r.returncode != 0:
        raise Refused(f"{ref!r} is not a {kind} in this repository")
    return r.stdout.strip()


def staged_diff(files: list[str]) -> str:
    return git(*DIFF, "--cached", "--", *files).decode("utf-8", errors="replace")


def range_diff(start: str, end: str, files: list[str]) -> str:
    span = f"{resolve(start, 'commit')}..{resolve(end, 'commit')}"
    return git(*DIFF, span, "--", *files).decode("utf-8", errors="replace")


def added_lines(diff: str) -> list[tuple[str, int, str]]:
    """(file, line number in the new file, text) for every `+` line of a unified diff."""
    out: list[tuple[str, int, str]] = []
    file = ""
    line = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            name = raw[4:]
            file = "" if name == "/dev/null" else name.removeprefix("b/")
        elif raw.startswith("@@ "):
            m = re.match(r"@@ -\S+ \+(\d+)", raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and file:
            out.append((file, line, raw[1:]))
            line += 1
        elif raw.startswith(" "):
            line += 1
    return out


def tree_lines(ref: str, files: list[str]) -> list[tuple[str, int, str]]:
    """(file, line number, text) for every line of every file tracked at `ref`, whatever it is."""
    listing = git("ls-tree", "-r", "-z", "--full-tree", resolve(ref, "tree"), "--", *files)
    blobs: list[tuple[str, str]] = []
    for entry in listing.decode("utf-8", errors="replace").split("\0"):
        if entry:
            meta, path = entry.split("\t", 1)
            _mode, kind, name = meta.split()
            if kind == "blob":  # a submodule is a commit and holds no lines here
                blobs.append((path, name))
    out: list[tuple[str, int, str]] = []
    for (path, _), body in zip(blobs, read_blobs([name for _, name in blobs]), strict=True):
        for number, text in enumerate(split_lines(body.decode("utf-8", errors="replace")), start=1):
            out.append((path, number, text))
    return out


def read_blobs(names: list[str]) -> Iterator[bytes]:
    """The contents of each blob, in order, from one `git cat-file --batch`."""
    raw = git("cat-file", "--batch", stdin="".join(f"{name}\n" for name in names).encode()) if names else b""
    at = 0
    for _ in names:
        header_end = raw.index(b"\n", at)
        size = int(raw[at:header_end].split()[2])
        yield raw[header_end + 1 : header_end + 1 + size]
        at = header_end + 1 + size + 1  # the body, then the newline cat-file puts after it


def split_lines(text: str) -> list[str]:
    """Lines as an editor numbers them: split on `\\n` only, a trailing `\\r` dropped, no empty last line."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    return lines[:-1] if lines and lines[-1] == "" else lines


def counted(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="check_pii.py", description="Check added lines for personal identifiers."
    )
    parser.add_argument("files", nargs="*", metavar="FILE", help="narrow the check to these paths")
    parser.add_argument("--from-ref", help="with --to-ref: the added lines of FROM..TO (PRE_COMMIT_FROM_REF)")
    parser.add_argument("--to-ref", help="with --from-ref (PRE_COMMIT_TO_REF)")
    parser.add_argument("--tree", metavar="REF", help="every line of every file tracked at REF")
    args = parser.parse_args(argv)
    start = args.from_ref or os.environ.get("PRE_COMMIT_FROM_REF")
    end = args.to_ref or os.environ.get("PRE_COMMIT_TO_REF")
    if args.tree and (args.from_ref or args.to_ref):
        parser.error("--tree reads a whole tree; it takes no --from-ref or --to-ref")
    if not args.tree and bool(start) != bool(end):
        parser.error("a range needs both ends: --from-ref and --to-ref (or both PRE_COMMIT_ variables)")

    path = patterns_file()
    try:
        patterns = load_patterns(path) if path.is_file() else []
        if args.tree:
            where, lines = f"the tree at {args.tree}", tree_lines(args.tree, args.files)
        elif start and end:
            where, lines = f"{start}..{end}", added_lines(range_diff(start, end, args.files))
        else:
            where, lines = "the staged diff", added_lines(staged_diff(args.files))
    except Refused as e:
        print(f"check-pii: {e}", file=sys.stderr)
        return 2

    hits = 0
    for file, number, text in lines:
        names = [p.name for p in patterns if p.regex.search(text)]
        if names:
            hits += 1
            print(f"{file}:{number}: matches pattern {', '.join(names)}")
    summary = (
        f"{counted(len(patterns), 'pattern', 'patterns')}, {counted(len(lines), 'line', 'lines')}, "
        f"{counted(hits, 'match', 'matches')} in {where}"
    )
    if not patterns or not lines:
        if not path.is_file():
            why = f"no patterns file at {path}"
        elif not patterns:
            why = f"{path} holds no patterns"
        else:
            why = "no line to read"
        sys.stdout.flush()
        print(f"check-pii: warning: {summary}; {why}, so nothing was checked", file=sys.stderr)
        return 0
    print(f"check-pii: {summary}")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
