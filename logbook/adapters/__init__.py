"""Adapters: one per source, export in → observations out (ARCHITECTURE layer 2, ADR 0012).

An adapter is a module with three names:

    NAME: str                                   # the `source` it writes, e.g. "dawarich"
    sniff(path) -> bool                         # "is this file mine?" — cheap, never raises
    run(path, since=None) -> Iterator[dict]     # line drafts: at, end, tz, source, kind, tier, payload

Built-in adapters live in this package. Third-party ones are separate packages that register the
`logbook.adapters` entry point. `all_adapters()` returns both; `find(path)` picks the first whose
sniff says yes. No adapter makes a network call on its default path.
"""

from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

ENTRY_POINT_GROUP = "logbook.adapters"
BUILT_IN = ("dawarich",)


@runtime_checkable
class Adapter(Protocol):
    NAME: str

    def sniff(self, path: Path) -> bool: ...

    def run(self, path: Path, since: str | None = None) -> Iterator[dict[str, Any]]: ...


def all_adapters() -> list[Adapter]:
    """Built-ins first, then entry points; one per NAME (the first registered wins)."""
    found: list[Adapter] = []
    for name in BUILT_IN:
        found.append(import_module(f"{__name__}.{name}"))
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        module = ep.load()
        if isinstance(module, Adapter):
            found.append(module)
    seen: set[str] = set()
    unique: list[Adapter] = []
    for a in found:
        if a.NAME not in seen:
            seen.add(a.NAME)
            unique.append(a)
    return unique


def find(path: Path) -> Adapter | None:
    """The first registered adapter that recognises `path`, or None."""
    return next((a for a in all_adapters() if a.sniff(Path(path))), None)
