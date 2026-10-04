"""Rewrite the test suite's imports from the 0.5 paths to where the modules live since 0.6.

The one-package split (#212) kept every 0.5 import path alive through `logbook._shim`, with a
DeprecationWarning once per old path, and `layout.MOVED` is the table of moves. This script walks
`tests/` and rewrites each import statement that names an old path to the new one, so the suite
runs on the 0.6 paths and the shims warn for nobody. Re-runnable: a file on the new paths is left
as it is. Stdlib only.

    uv run python scripts/rewrite_test_imports.py            # rewrite, print what changed
    uv run python scripts/rewrite_test_imports.py --check    # exit 1 when a file would change

What is rewritten (the mapping is `layout.MOVED`, through `_shim.new_name`):

    from logbook.store import Logbook                ->  from logbook.core.store import Logbook
    from logbook.adapters.takeout import fit         ->  from logbook.contrib.adapters.takeout import fit
    from logbook import adapters, cli, health        ->  from logbook import cli
                                                         from logbook.contrib import adapters
                                                         from logbook.core import health
    import logbook.adapters.takeout.maps as maps     ->  import logbook.contrib.adapters.takeout.maps as maps

A bare `import logbook.store` (no `as`) binds the name `logbook` and the test then reads
`logbook.store.X`, which a rewrite of the import line alone would break; the script names the line
and stops. `tests/test_layout.py` is skipped: its job is to prove the old paths still resolve.
Imports that span several lines are rewritten only when every name moves to one place."""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
SKIP = {TESTS / "test_layout.py"}  # tests the 0.5 paths on purpose

sys.path.insert(0, str(ROOT))
from logbook._shim import new_name  # noqa: E402  (the repository's own table, not an installed copy)


def _trailing_comment(line: str) -> str:
    """The `# noqa` or other comment at the end of an import statement, with two spaces before it."""
    try:
        for token in tokenize.generate_tokens(io.StringIO(line).readline):
            if token.type == tokenize.COMMENT:
                return "  " + token.string
    except tokenize.TokenError:
        pass
    return ""


def _rewrite_import(node: ast.Import, line: str) -> list[str] | None:
    """`import a.b [as x], c.d`: each dotted name that moved is replaced."""
    names: list[str] = []
    changed = False
    for alias in node.names:
        new = new_name(alias.name)
        if new is None:
            names.append(alias.name if alias.asname is None else f"{alias.name} as {alias.asname}")
            continue
        if alias.asname is None:
            raise SystemExit(
                f"{line.strip()!r}: a bare `import {alias.name}` binds `logbook` and the test reads the "
                "attribute path; rewrite it by hand (an `as` name, or a `from` import)"
            )
        names.append(f"{new} as {alias.asname}")
        changed = True
    if not changed:
        return None
    indent = line[: len(line) - len(line.lstrip())]
    return [f"{indent}import {', '.join(names)}{_trailing_comment(line)}"]


def _rewrite_from(node: ast.ImportFrom, line: str) -> list[str] | None:
    """`from a.b import x, y`: the module is replaced when it moved; when the module is the package
    `logbook` itself, each imported name that is a moved module goes to its own statement."""
    if node.level or node.module is None:
        return None
    indent = line[: len(line) - len(line.lstrip())]
    comment = _trailing_comment(line)
    new_module = new_name(node.module)
    if new_module is not None:
        names = ", ".join(a.name if a.asname is None else f"{a.name} as {a.asname}" for a in node.names)
        return [f"{indent}from {new_module} import {names}{comment}"]
    if node.module != "logbook":
        return None
    # `from logbook import a, b`: group the names by where each lives now, one statement per module
    groups: dict[str, list[str]] = {}
    changed = False
    for alias in node.names:
        new = new_name(f"logbook.{alias.name}")
        if new is None:
            target = "logbook"
        else:
            target, _, leaf = new.rpartition(".")
            assert leaf == alias.name, new
            changed = True
        groups.setdefault(target, []).append(
            alias.name if alias.asname is None else f"{alias.name} as {alias.asname}"
        )
    if not changed:
        return None
    return [
        f"{indent}from {module} import {', '.join(names)}{comment}"
        for module, names in sorted(groups.items())
    ]


def rewrite(source: str, path: Path) -> str:
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines(keepends=True)
    edits: list[tuple[int, int, list[str]]] = []  # (first line index, last line index, replacement)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            text = "".join(lines[node.lineno - 1 : node.end_lineno])
            replacement = _rewrite_import(node, text)
        elif isinstance(node, ast.ImportFrom):
            text = "".join(lines[node.lineno - 1 : node.end_lineno])
            replacement = _rewrite_from(node, text)
        else:
            continue
        if replacement is None:
            continue
        if node.end_lineno != node.lineno and len(replacement) > 1:
            raise SystemExit(
                f"{path}:{node.lineno}: an import over several lines whose names move to different "
                "places; rewrite it by hand"
            )
        edits.append((node.lineno - 1, node.end_lineno or node.lineno, replacement))
    if not edits:
        return source
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"
    for first, last, replacement in sorted(edits, reverse=True):
        lines[first:last] = [text + newline for text in replacement]
    return "".join(lines)


def main(argv: list[str]) -> int:
    check = "--check" in argv
    changed: list[Path] = []
    for path in sorted(TESTS.rglob("*.py")):
        if path in SKIP:
            continue
        before = path.read_text(encoding="utf-8")
        after = rewrite(before, path)
        if after == before:
            continue
        changed.append(path)
        if not check:
            path.write_bytes(after.encode("utf-8"))  # bytes: no CRLF translation on Windows
    for path in changed:
        print(("would rewrite " if check else "rewrote ") + str(path.relative_to(ROOT)))
    print(f"{len(changed)} file(s) {'to rewrite' if check else 'rewritten'}")
    return 1 if check and changed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
