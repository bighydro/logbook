"""The adapter registry is one table, pyproject.toml's `logbook.adapters` entry points: every adapter
module under logbook/contrib/adapters/ is in it, every entry in it is an adapter module, the installed package
reports the same names and modules, and `BUILT_IN` — the package's copy of the table in its order,
which the installed metadata sorts away — is what `scripts/adapter_registry.py` generates from it. So
the table the file states and the registry the code reads can never disagree, and a module with no
entry fails here."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path

from logbook.contrib import adapters

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "logbook" / "contrib" / "adapters"
#: adapter modules that are deliberately not registered, each with the reason its docstring gives
UNREGISTERED = {
    "takeout.calendar": "reached through `ics`, which sniffs every iCalendar file, folder or not",
}


def _table() -> dict[str, str]:
    with (ROOT / "pyproject.toml").open("rb") as f:
        return tomllib.load(f)["project"]["entry-points"][adapters.ENTRY_POINT_GROUP]


def _modules() -> dict[str, bool]:
    """Every module under the package → whether it is an adapter (a file or a live one, by protocol)."""
    found = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        name = ".".join(path.relative_to(PACKAGE).with_suffix("").parts)
        module = import_module(f"{adapters.BUILT_IN_PREFIX}{name}")
        found[name] = isinstance(module, adapters.Adapter | adapters.LiveAdapter)
    return found


def test_every_entry_is_an_adapter_module_of_this_package() -> None:
    modules = _modules()
    for name, value in _table().items():
        assert value.startswith(adapters.BUILT_IN_PREFIX), (name, value)
        module = value.removeprefix(adapters.BUILT_IN_PREFIX)
        assert module in modules, f"{name} names {value}, which is not under logbook/contrib/adapters/"
        assert modules[module], f"{name} names {value}, which is neither a file nor a live adapter"
        assert name == module.replace(".", "-").replace("_", "-"), (name, module)


def test_every_adapter_module_is_an_entry_or_deliberately_not() -> None:
    listed = {value.removeprefix(adapters.BUILT_IN_PREFIX) for value in _table().values()}
    on_disk = {name for name, is_adapter in _modules().items() if is_adapter}
    assert on_disk - listed == set(UNREGISTERED), "an adapter module pyproject.toml does not list"
    assert set(UNREGISTERED) <= on_disk, "UNREGISTERED names a module that is not an adapter any more"
    assert not set(UNREGISTERED) & listed, "UNREGISTERED names a module pyproject.toml lists"


def test_built_in_is_the_table_in_its_order() -> None:
    """The tuple the package reads is the table, generated; an edit to either without the script shows
    here, and so does the script disagreeing with this test."""
    table = _table()
    assert tuple(v.removeprefix(adapters.BUILT_IN_PREFIX) for v in table.values()) == adapters.BUILT_IN
    check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "adapter_registry.py"), "--check"],
        capture_output=True,
        encoding="utf-8",
    )
    assert check.returncode == 0, check.stdout + check.stderr


def test_the_installed_package_reports_the_table() -> None:
    """`uv sync` writes the table into the package's metadata, sorted by name; an edit to
    pyproject.toml without a sync shows here."""
    installed = {
        ep.name: ep.value for ep in entry_points(group=adapters.ENTRY_POINT_GROUP) if adapters.is_built_in(ep)
    }
    assert installed == _table()


def test_all_adapters_tries_the_built_ins_in_the_table_order() -> None:
    names = [a.__name__ for a in adapters.all_adapters() if a.__name__.startswith(adapters.BUILT_IN_PREFIX)]
    assert names == list(_table().values())
