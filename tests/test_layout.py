"""One package, three tiers (`logbook/layout.py`): every module under `logbook/` belongs to exactly one
of core, contrib, labs, the commands or the package's own root; the import arrow points down; and
every 0.5 import path still resolves, to the same module object, with a DeprecationWarning once."""

from __future__ import annotations

import ast
import importlib
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

import logbook
from logbook import layout

PACKAGE = Path(logbook.__file__).parent
DOC = PACKAGE.parent / "docs" / "migration-0.6.md"
ORDER = {"core": 0, "contrib": 1, "labs": 2, "commands": 3}  # a tier imports its own level or lower


def modules() -> dict[str, Path]:
    """Every module of the package by its dotted name."""
    found: dict[str, Path] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.relative_to(PACKAGE.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        found[".".join(parts)] = path
    return found


def tier_of(name: str) -> str | None:
    """The tier (or `commands`, or `root`) a module belongs to by the table; None when none claims it."""
    parts = name.split(".")
    if len(parts) == 1:
        return "root"
    if len(parts) == 2 and parts[1] in layout.ROOT:
        return "root"
    if parts[1] == layout.COMMANDS:
        return "commands"
    if parts[1] in layout.TIERS:
        if len(parts) == 2:
            return parts[1]  # the tier package itself
        members = layout.TIERS[parts[1]]
        if parts[2] in members:
            return parts[1]
    return None


def test_every_module_belongs_to_exactly_one_tier() -> None:
    unclaimed = sorted(name for name in modules() if tier_of(name) is None)
    assert not unclaimed, f"not in layout.TIERS, ROOT or commands: {unclaimed}"


def test_the_table_names_only_modules_that_exist() -> None:
    existing = set(modules())
    for tier, names in layout.TIERS.items():
        for name in names:
            assert f"logbook.{tier}.{name}" in existing, (
                f"layout.TIERS[{tier!r}] names {name}, which is not there"
            )
    for name in layout.ROOT:
        assert name == "__init__" or f"logbook.{name}" in existing
    seen: dict[str, str] = {}
    for tier, names in layout.TIERS.items():
        for name in names:
            assert name not in seen, f"{name} is in {seen[name]} and {tier}"
            seen[name] = tier


def _imports_of(path: Path, name: str) -> set[str]:
    """The absolute names of every module `path` imports, at the top or inside a function."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                base = node.module or ""
            else:
                parts = package.split(".")
                parts = parts[: len(parts) - (node.level - 1)]
                base = ".".join(parts) + (f".{node.module}" if node.module else "")
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)  # `from . import day`: a submodule
    return {m for m in found if m.startswith("logbook")}


def test_the_import_arrow_points_down() -> None:
    """Core imports core; contrib imports core and contrib; labs and the commands import anything.
    Function-level imports count: a tier never reaches above itself, lazily or not."""
    known = modules()
    problems: list[str] = []
    for name, path in known.items():
        mine = tier_of(name)
        if mine not in ("core", "contrib"):
            continue
        for imported in _imports_of(path, name):
            if imported not in known:
                continue  # an attribute, or the package itself
            theirs = tier_of(imported)
            if theirs == "root":
                continue
            if theirs is None or ORDER[theirs] > ORDER[mine]:
                problems.append(f"{name} ({mine}) imports {imported} ({theirs})")
    assert not problems, "\n".join(problems)


@pytest.mark.parametrize("old", sorted(layout.MOVED))
def test_a_moved_path_is_the_same_module(old: str) -> None:
    new = layout.MOVED[old]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        via_old = importlib.import_module(old)
    via_new = importlib.import_module(new)
    assert via_old is via_new
    assert via_old.__name__ == new and via_old.__spec__ is not None and via_old.__spec__.name == new


def test_a_submodule_of_a_moved_package_is_the_same_module() -> None:
    from logbook.contrib.adapters import screentime
    from logbook.contrib.adapters.takeout import maps

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        import logbook.adapters.takeout.maps as via_old

        from logbook.adapters import screentime as via_from

    assert via_old is maps and via_from is screentime


def test_an_old_path_warns_once_where_it_is_imported() -> None:
    """A fresh interpreter: the first import of an old path is a DeprecationWarning on the importing
    line, naming both paths and the version that drops the old one; a second import is quiet; the
    new path never warns. `from logbook.adapters import immich` warns for the package once: the
    submodule then resolves through the real package and has no old name of its own, while a dotted
    `import logbook.adapters.takeout.maps` names two old paths and warns for each."""
    script = (
        "import warnings\n"
        "with warnings.catch_warnings(record=True) as caught:\n"
        "    warnings.simplefilter('always')\n"
        "    import logbook.store\n"
        "    import logbook.store\n"
        "    import logbook.core.store\n"
        "    from logbook.adapters import immich\n"
        "    import logbook.adapters.takeout.maps\n"
        "for w in caught:\n"
        "    print(w.category.__name__, w.lineno, str(w.message))\n"
    )
    out = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, encoding="utf-8")
    lines = out.stdout.splitlines()
    assert [line.split(" ", 2)[:2] for line in lines] == [
        ["DeprecationWarning", "4"],
        ["DeprecationWarning", "7"],
        ["DeprecationWarning", "8"],
        ["DeprecationWarning", "8"],
    ], out.stdout
    assert lines[0].endswith(
        "logbook.store is logbook.core.store since 0.6; the old name goes in 0.7 (docs/migration-0.6.md)"
    )
    assert "logbook.adapters is logbook.contrib.adapters since 0.6" in lines[1]
    assert "logbook.adapters.takeout is logbook.contrib.adapters.takeout since 0.6" in lines[2]
    assert "logbook.adapters.takeout.maps is logbook.contrib.adapters.takeout.maps since 0.6" in lines[3]


def test_the_migration_page_lists_every_move() -> None:
    text = DOC.read_text(encoding="utf-8")
    for old, new in layout.MOVED.items():
        assert f"`{old}`" in text and f"`{new}`" in text, f"{old} -> {new} is not in {DOC.name}"
    assert layout.REMOVED_IN in text
