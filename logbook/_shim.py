"""The 0.5 import paths, kept alive for one minor version (`layout.MOVED`, `docs/migration-0.6.md`).

A finder on `sys.meta_path`, installed when `logbook` is imported: `import logbook.store` (or
`from logbook.adapters import immich`, or `import logbook.adapters.takeout.maps`) imports the
module at its new path and registers that same object under the old name, so there is one copy of
every module and a patch through either name lands on it. The first import of each old path warns
once, a DeprecationWarning attributed to the line that imported it. The module itself is left as it
was: its `__name__` and `__spec__` are the new path's."""

from __future__ import annotations

import sys
import warnings
from importlib import import_module
from importlib.abc import Loader, MetaPathFinder
from importlib.machinery import ModuleSpec
from importlib.util import spec_from_loader
from types import ModuleType
from typing import Any

from .layout import MOVED, REMOVED_IN

_WARNED: set[str] = set()


def new_name(old: str) -> str | None:
    """The current path of a moved module, or None when the name was never moved."""
    for before, after in MOVED.items():
        if old == before or old.startswith(before + "."):
            return after + old[len(before) :]
    return None


class _AliasLoader(Loader):
    """Hands the import system the module already loaded at its new path, and puts its own
    `__spec__` back afterwards (the import system sets the alias's on it first)."""

    def __init__(self, module: ModuleType) -> None:
        self.module = module
        self.spec = module.__spec__

    def create_module(self, spec: ModuleSpec) -> ModuleType:
        return self.module

    def exec_module(self, module: ModuleType) -> None:
        module.__spec__ = self.spec


class MovedFinder(MetaPathFinder):
    def find_spec(
        self, fullname: str, path: Any = None, target: ModuleType | None = None
    ) -> ModuleSpec | None:
        new = new_name(fullname)
        if new is None:
            return None
        module = import_module(new)
        if fullname not in _WARNED:
            _WARNED.add(fullname)
            warnings.warn(
                f"{fullname} is {new} since 0.6; the old name goes in {REMOVED_IN} (docs/migration-0.6.md)",
                DeprecationWarning,
                stacklevel=1,  # then past every frame of the import system and of this file
                skip_file_prefixes=("<frozen importlib", __file__),
            )
        return spec_from_loader(fullname, _AliasLoader(module), is_package=hasattr(module, "__path__"))


def install() -> None:
    if not any(isinstance(finder, MovedFinder) for finder in sys.meta_path):
        sys.meta_path.insert(0, MovedFinder())
