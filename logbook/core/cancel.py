"""A reading that can be stopped: the Library's per-request limit, and a browser that left.

A reader reads line after line. The server runs a page in a scope (`scope`) holding a token; when
the page outlives its limit, or the connection it was asked on closes, the server sets the token
(`Token.cancel`), and the next line any reader reads in that scope raises `Cancelled`
(`check`, called where every line is read: `store.read_line_at` and `Logbook._parse`). The reading
stops within a line; the `with` blocks around it close what they opened, and nothing it half-built
is kept. Outside a scope `check` costs one context-variable read and does nothing.

`Cancelled` is a `BaseException`, as `KeyboardInterrupt` is, so the readers' `except Exception`
(one page's failure is that page's) never swallows it and reads on."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Iterator
from contextvars import ContextVar


class Cancelled(BaseException):  # an interruption, as KeyboardInterrupt is, not an error
    """The reading was stopped: its message says why (the limit, the browser that left)."""


class Token:
    """One reading's stop: set once, from any thread."""

    def __init__(self) -> None:
        self._set = threading.Event()
        self.reason = ""

    def cancel(self, reason: str) -> None:
        if not self._set.is_set():
            self.reason = reason
            self._set.set()

    @property
    def cancelled(self) -> bool:
        return self._set.is_set()


_current: ContextVar[Token | None] = ContextVar("logbook_cancel", default=None)


@contextlib.contextmanager
def scope(token: Token) -> Iterator[Token]:
    """Read under `token` for the block: `check` raises once it is set."""
    reset = _current.set(token)
    try:
        yield token
    finally:
        _current.reset(reset)


def check() -> None:
    """Raise `Cancelled` when the scope's token is set; nothing outside a scope."""
    token = _current.get()
    if token is not None and token.cancelled:
        raise Cancelled(token.reason)
