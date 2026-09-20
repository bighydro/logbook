"""Adapters: one per source, export in → observations out (ARCHITECTURE layer 2, ADR 0012).

Two kinds share one registry. A *file* adapter reads an export you already hold:

    NAME: str                                   # the `source` it writes, e.g. "dawarich"
    sniff(path) -> bool                         # "is this file mine?" — cheap, never raises
    run(path, since=None) -> Iterator[dict]     # line drafts: at, end, tz, source, kind, tier, payload

`run` may also take an optional `counts: dict[str, int]`; when it does, `logbook add` passes one and
reports what the adapter skipped (`skipped_no_timestamp`, `skipped_bad_coordinates`, `skipped_no_ref`, ...;
the phrases live in `cli.SKIP_PHRASES`).

A *live* adapter pulls from a service you run, and only when `logbook sync <NAME>` asks it to:

    NAME: str
    ENV: tuple[str, ...]                        # the environment variables it reads
    configure(env) -> Config | None             # None when one of them is absent
    pull(config, since=None) -> Iterator[dict]  # the same line drafts, oldest first
    watermark(draft) -> str | None              # the `since` that would pull this draft again

`since` and the watermark are in the *source's* clock (when it received or last changed the item),
not the event's: `logbook sync` stores the largest watermark of a completed pull and passes it back
as `since`, so an old photo uploaded tomorrow is picked up by tomorrow's sync. A line's `at` is the
event time regardless.

Built-in adapters live in this package. Third-party ones are separate packages that register the
`logbook.adapters` entry point. `all_adapters()` returns both kinds; `find(path)` asks only file
adapters; `live(name)` resolves a live one. No file adapter makes a network call, and a live adapter
makes them only inside `pull`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from importlib import import_module
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

ENTRY_POINT_GROUP = "logbook.adapters"
BUILT_IN = ("dawarich", "immich", "takeout.location", "ios_contacts", "whatsapp", "imessage")


@runtime_checkable
class Adapter(Protocol):
    """A file adapter."""

    NAME: str

    def sniff(self, path: Path) -> bool: ...

    def run(self, path: Path, since: str | None = None) -> Iterator[dict[str, Any]]: ...


@runtime_checkable
class LiveAdapter(Protocol):
    NAME: str
    ENV: tuple[str, ...]

    def configure(self, env: Mapping[str, str]) -> object | None: ...

    def pull(
        self,
        config: Any,
        since: str | None = None,
        progress: Callable[[int, float], None] | None = None,
        counts: dict[str, int] | None = None,
    ) -> Iterator[dict[str, Any]]: ...

    def watermark(self, draft: dict[str, Any]) -> str | None: ...


def all_adapters() -> list[Adapter | LiveAdapter]:
    """Built-ins first, then entry points; one per NAME (the first registered wins)."""
    found: list[Adapter | LiveAdapter] = []
    for name in BUILT_IN:
        found.append(import_module(f"{__name__}.{name}"))
    for ep in entry_points(group=ENTRY_POINT_GROUP):
        module = ep.load()
        if isinstance(module, Adapter | LiveAdapter):
            found.append(module)
    seen: set[str] = set()
    unique: list[Adapter | LiveAdapter] = []
    for a in found:
        if a.NAME not in seen:
            seen.add(a.NAME)
            unique.append(a)
    return unique


def file_adapters() -> list[Adapter]:
    return [a for a in all_adapters() if isinstance(a, Adapter)]


def live_adapters() -> list[LiveAdapter]:
    return [a for a in all_adapters() if isinstance(a, LiveAdapter)]


def find(path: Path) -> Adapter | None:
    """The first registered file adapter that recognises `path`, or None."""
    return next((a for a in file_adapters() if a.sniff(Path(path))), None)


def live(name: str) -> LiveAdapter | None:
    """The live adapter called `name`, or None."""
    return next((a for a in live_adapters() if name == a.NAME), None)
