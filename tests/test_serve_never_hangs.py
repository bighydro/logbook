"""The Library never hangs and never breaks (phase 6 of the Library's rebuild): a page read longer than
the limit is stopped and said so in one sentence, and built in the background when the server
builds; at most `RENDERS` pages are read at once, however many are asked for together; a browser that
leaves stops its reading and is sent nothing, with no traceback in the log; a page the build holds is
answered at once while others are read; an idle connection is closed. Over HTTP, on 127.0.0.1, on the
Oslo persona's fortnight (`persona.py`), who does not exist."""

from __future__ import annotations

import contextlib
import http.client
import io
import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import persona_record

from logbook.contrib import library_build, serve
from logbook.core import cancel
from logbook.core.store import Logbook

JUNE = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)
LOOPBACK = "127.0.0.1"
SLOW = "/days"  # the page made slow here: it reads a line at a time, for ever, until it is stopped


class Slow:
    """`Site._page` for `SLOW`: reads as a reader reads, a check a line, until it is stopped; how many
    are reading now, the most at once, and how many were stopped."""

    def __init__(self, page: Any):
        self.page = page
        self.lock = threading.Lock()
        self.now = self.most = self.stopped = self.started = 0

    def __call__(self, site: serve.Site, path: str, params: dict[str, str]) -> str:
        if path != SLOW:
            return str(self.page(site, path, params))
        with self.lock:
            self.now += 1
            self.started += 1
            self.most = max(self.most, self.now)
        try:
            while True:
                cancel.check()
                time.sleep(0.02)
        except cancel.Cancelled:
            with self.lock:
                self.stopped += 1
            raise
        finally:
            with self.lock:
                self.now -= 1


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return persona_record(tmp_path, monkeypatch)


@pytest.fixture
def slow(monkeypatch: pytest.MonkeyPatch) -> Slow:
    found = Slow(serve.Site._page)

    def page(site: serve.Site, path: str, params: dict[str, str]) -> str:
        return found(site, path, params)

    monkeypatch.setattr(serve.Site, "_page", page)
    return found


@pytest.fixture
def stderr(monkeypatch: pytest.MonkeyPatch) -> io.StringIO:
    """What the server logs (`BaseHTTPRequestHandler.log_message` writes to stderr)."""
    out = io.StringIO()
    monkeypatch.setattr("sys.stderr", out)
    return out


def _start(server: serve.Server) -> Iterator[int]:
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def port(lb: Logbook, slow: Slow) -> Iterator[int]:
    yield from _start(serve.Server(0, serve.Site(lb, now=lambda: JUNE), limit_s=1.0))


def _get(port: int, path: str, timeout: float = 30) -> tuple[int, bytes, float]:
    conn = http.client.HTTPConnection(LOOPBACK, port, timeout=timeout)
    began = time.monotonic()
    conn.request("GET", path)
    answer = conn.getresponse()
    body = answer.read()
    conn.close()
    return answer.status, body, time.monotonic() - began


def _asking(port: int, path: str) -> threading.Thread:
    """A browser asking for `path` in the background, until it is answered or the server closes."""

    def ask() -> None:
        with contextlib.suppress(OSError, http.client.HTTPException):
            _get(port, path)

    thread = threading.Thread(target=ask, daemon=True)
    thread.start()
    return thread


def _until(condition: Any, seconds: float = 10) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return bool(condition())


def test_check_outside_a_scope_does_nothing_and_a_stop_is_never_swallowed() -> None:
    cancel.check()
    token = cancel.Token()
    with cancel.scope(token):
        cancel.check()
        token.cancel("over the limit")
        with pytest.raises(cancel.Cancelled, match="over the limit"):
            try:
                cancel.check()
            except Exception:  # a reader's own broad catch: the stop passes through it
                pytest.fail("a stop was caught as an error")
    cancel.check()


def test_a_page_over_the_limit_is_stopped_and_says_so(port: int, slow: Slow) -> None:
    status, body, took = _get(port, SLOW)
    page = body.decode("utf-8")
    assert status == 503 and "Still reading" in page and "1 s" in page
    assert "spinner" not in page and "<script" not in page
    assert took < 5, "answered at the limit, not when the reading ends"
    assert _until(lambda: slow.stopped == 1), "the reading was stopped, not left running"


def test_other_pages_answer_while_one_is_read(port: int, slow: Slow) -> None:
    _asking(port, SLOW)
    assert _until(lambda: slow.now == 1)
    status, _body, took = _get(port, "/day/2026-06-17")
    assert status == 200 and took < 5


def test_a_whole_menu_at_once_reads_at_most_renders_pages_at_once(port: int, slow: Slow) -> None:
    asked = [_asking(port, SLOW) for _ in range(8)]
    for t in asked:
        t.join(30)
    assert slow.most <= serve.RENDERS, slow.most
    assert slow.started <= 8 and _until(lambda: slow.now == 0)


def test_a_browser_that_leaves_stops_its_reading_and_logs_no_traceback(
    port: int, slow: Slow, stderr: io.StringIO
) -> None:
    with socket.create_connection((LOOPBACK, port), timeout=5) as conn:
        conn.sendall(f"GET {SLOW} HTTP/1.1\r\nHost: {LOOPBACK}\r\n\r\n".encode())
        assert _until(lambda: slow.now == 1)
    assert _until(lambda: slow.stopped == 1, 5), "stopped when the browser left, before the limit"
    time.sleep(0.3)
    logged = stderr.getvalue()
    assert "Traceback" not in logged and "BrokenPipe" not in logged and "ConnectionReset" not in logged


def test_a_broken_pipe_is_the_browser_leaving_never_an_error() -> None:
    handler = serve.Handler.__new__(serve.Handler)
    handler.request_version = "HTTP/1.1"
    handler.requestline = "GET / HTTP/1.1"
    handler.command = "GET"
    handler.close_connection = False
    handler.client_address = (LOOPBACK, 1)

    class Gone(io.RawIOBase):
        def writable(self) -> bool:
            return True

        def write(self, b: Any) -> int:
            raise BrokenPipeError(32, "Broken pipe")

    handler.wfile = Gone()  # type: ignore[assignment]
    handler.log_request = lambda *_a, **_k: None  # type: ignore[method-assign]
    handler._send(serve.Response(200, b"<p>x</p>"), body=True)
    assert handler.close_connection is True


def test_a_page_the_build_holds_answers_at_once_while_the_pool_is_full(lb: Logbook, slow: Slow) -> None:
    library = library_build.Library(lb, now=lambda: JUNE)
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library, only=["/people"])
    server = serve.Server(0, serve.Site(lb, now=lambda: JUNE, library=library), limit_s=20.0)
    for port in _start(server):
        for _ in range(serve.RENDERS + 1):
            _asking(port, SLOW)
        assert _until(lambda: slow.now == serve.RENDERS)
        status, body, took = _get(port, "/people")
        assert status == 200 and b"built 12:00" in body and took < 2


def test_over_the_limit_with_a_build_the_page_is_built_in_the_background(lb: Logbook, slow: Slow) -> None:
    library = library_build.Library(lb, now=lambda: JUNE)
    site = serve.Site(lb, now=lambda: JUNE, library=library)
    server = serve.Server(0, site, limit_s=1.0)
    asked: list[str] = []

    class Builder:
        def ask(self, target: str) -> None:
            asked.append(target)

        def stop(self) -> None:
            pass

    server.rebuilder = Builder()  # type: ignore[assignment]
    for port in _start(server):
        status, body, _took = _get(port, SLOW + "?from=2026-06-10&to=2026-06-12")
        assert status == 503 and b"being built now, in the background" in body
    assert asked == [SLOW + "?from=2026-06-10&to=2026-06-12"]


def test_an_idle_connection_is_closed(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(serve.Handler, "timeout", 0.5)
    for port in _start(serve.Server(0, serve.Site(lb, now=lambda: JUNE))):
        with socket.create_connection((LOOPBACK, port), timeout=5) as conn:
            began = time.monotonic()
            assert conn.recv(1) == b"", "closed by the server, not left waiting"
            assert time.monotonic() - began < 4
