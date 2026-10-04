"""`ijson`, the `stream` extra: streaming JSON, so a multi-gigabyte export never has to fit in memory.

Five adapters read their export through it (`dawarich`, `spotify`, `google-takeout-location`,
`google-takeout-activity`, `google-takeout-youtube`). It is not a dependency of the package: a
record that never meets such an export needs no parser for it. The adapters import `ijson` from
here, a module object that loads the real one on first use and, when it is not installed, raises
`MissingExtra` naming the extra, which `logbook add` prints as one line and exits 2 on. An adapter's
`sniff` falls back to a look at the file's first bytes, so a file is still recognised and the
message says what to install rather than "no adapter"."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import Any

EXTRA = "openlogbook[stream]"
MESSAGE = (
    "reading this export streams its JSON with ijson, which is not installed; install the stream"
    f" extra: pip install '{EXTRA}'"
)


class MissingExtra(ImportError):
    """`ijson` is not installed; the message names the extra."""


def _import() -> ModuleType:
    try:
        return import_module("ijson")
    except ImportError:
        raise MissingExtra(MESSAGE) from None


def available() -> bool:
    """Whether `ijson` can be imported."""
    try:
        _import()
    except MissingExtra:
        return False
    return True


def json_errors() -> tuple[type[Exception], ...]:
    """What a streamed parse raises: OSError, ValueError and, when ijson is there, its JSONError."""
    try:
        return (OSError, ValueError, _import().JSONError)
    except MissingExtra:
        return (OSError, ValueError)


HEAD_BYTES = 65536


def head(path: Path) -> str:
    """The first bytes of a file as text, for a `sniff` that has no parser: empty when unreadable."""
    try:
        with Path(path).open("rb") as fh:
            return fh.read(HEAD_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


class _Lazy:
    """Stands in for the `ijson` module: the first attribute asked for imports it."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_import(), name)


ijson: Any = _Lazy()  # `from ..stream import ijson`, then `ijson.items(...)` as before
