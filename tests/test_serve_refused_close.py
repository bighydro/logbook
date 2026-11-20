"""A request the Library refuses before reading its body (a proxy's POST, another host's, one over the
size a form may carry) is answered and its connection closed gracefully: the reply is sent, then at
most `serve.DRAIN_BYTES` of the unread body are read and discarded (never parsed, never kept) for at
most `serve.DRAIN_S`, then the connection is shut for writing and closed. Closing a socket with
received bytes unread sends a reset instead of a close, and on Windows the reset can reach the client
before it has read the reply (WinError 10053 on main's slow tier, 2026-11). On the Oslo persona's
fortnight (`persona.py`), who does not exist; the proxy name is invented."""

from __future__ import annotations

import contextlib
import http.client
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

import pytest
import test_library_walk as walk
from persona import persona_record
from test_serve_hosts import LOOPBACK, SETTING, Served

from logbook.contrib import phone, serve

VIA = ("Via", "1.1 proxy.example.org")  # a proxy that names this machine as the Host: refused, 403


@pytest.fixture(params=[False, True], ids=["live", "built"])
def served(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Served]:
    lb = persona_record(tmp_path, monkeypatch)
    lb.set_meta(**{phone.KEY: SETTING})
    s = Served(lb, built=request.param)
    try:
        yield s
    finally:
        s.close()


def _here(served: Served) -> list[tuple[str, str]]:
    return [("Host", f"{LOOPBACK}:{served.port}"), ("Origin", f"http://{LOOPBACK}:{served.port}")]


def _acts(served: Served) -> list[tuple[str, bytes]]:
    """The Day's Star and Sign forms as a page posts them: bodies the Library would act on, were the
    request not refused."""
    connection = http.client.HTTPConnection(LOOPBACK, served.port, timeout=30)
    try:
        connection.request("GET", f"/day/{walk.WEDNESDAY}", headers={"Host": f"{LOOPBACK}:{served.port}"})
        reply = connection.getresponse()
        page = reply.read().decode("utf-8")
    finally:
        connection.close()
    assert reply.status == 200
    star = walk._forms(page, "star")[0]
    acts = [(star.action, urlencode({**star.fields, "act": "star"}).encode("utf-8"))]
    # the fortnight has no reflection, so no Day shows a Sign form: the form as `_sign_html` posts it
    # with none, which signs the day without one (`logbook day sign`)
    sign = urlencode({"reflection": "", "proposals": ""}).encode("utf-8")
    return [*acts, (f"/day/{walk.WEDNESDAY}/sign", sign)]


def _head(path: str, headers: list[tuple[str, str]], length: int) -> bytes:
    sent = [*headers, ("Content-Type", "application/x-www-form-urlencoded"), ("Content-Length", str(length))]
    lines = "".join(f"{n}: {v}\r\n" for n, v in sent)
    return f"POST {path} HTTP/1.1\r\n{lines}\r\n".encode("latin-1")


def _reply(sock: socket.socket) -> tuple[int, str]:
    """The status and text of one reply read off `sock` (its Content-Length)."""
    got = b""
    while b"\r\n\r\n" not in got:
        chunk = sock.recv(65536)
        assert chunk, f"closed before the reply: {got!r}"
        got += chunk
    raw, _, rest = got.partition(b"\r\n\r\n")
    status_line, *lines = raw.decode("latin-1").split("\r\n")
    found = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in lines)}
    length = int(found.get("content-length", "0"))
    while len(rest) < length:
        chunk = sock.recv(65536)
        assert chunk, "closed inside the reply"
        rest += chunk
    return int(status_line.split()[1]), rest[:length].decode("utf-8")


def _end(sock: socket.socket) -> str:
    """How the connection ends once the reply is read: `closed` (an orderly close) or `reset`. A reset
    after the close is still one: Linux hands the close to `recv` first and keeps the reset as the
    socket's pending error."""
    try:
        while sock.recv(65536):
            pass
    except (ConnectionResetError, ConnectionAbortedError):
        return "reset"
    return "reset" if sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR) else "closed"


def test_a_refused_post_s_connection_closes_and_is_never_reset(served: Served) -> None:
    """The race made certain: the body arrives only after the refusal was sent. The Library reads it
    (and drops it) before it closes, so the connection ends in an orderly close, never a reset; and the
    act the body names is not done."""
    head = str(served.site.lb.meta["head"])
    for path, body in _acts(served):
        served.reads.clear()
        with socket.create_connection((LOOPBACK, served.port), timeout=30) as sock:
            sock.sendall(_head(path, [*_here(served), VIA], len(body)))
            status, text = _reply(sock)
            sock.sendall(body)
            time.sleep(0.05)  # the body in the server's buffer before it could close
            ending = _end(sock)
        assert status == 403, (path, status)
        assert "nothing was written" in text
        assert ending == "closed", path
        assert "current" not in served.reads
    assert str(served.site.lb.meta["head"]) == head


def test_the_same_refused_post_fifty_times_is_answered_every_time(served: Served) -> None:
    """The refused POST of `test_serve_edges`, a body that would be a Star or a Sign, fifty times in a
    row: every reply read in full, a 403 that says nothing was written, and nothing is."""
    head = str(served.site.lb.meta["head"])
    acts = _acts(served)
    served.reads.clear()
    for n in range(50):
        path, body = acts[n % len(acts)]
        connection = http.client.HTTPConnection(LOOPBACK, served.port, timeout=30)
        try:
            connection.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
            for name, value in [*_here(served), VIA]:
                connection.putheader(name, value)
            connection.putheader("Content-Type", "application/x-www-form-urlencoded")
            connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body)
            reply = connection.getresponse()
            status, text = reply.status, reply.read().decode("utf-8")
        finally:
            connection.close()
        assert status == 403, (n, path, status)
        assert "nothing was written" in text, n
    assert "current" not in served.reads
    assert str(served.site.lb.meta["head"]) == head


@pytest.mark.parametrize("proxied", [True, False], ids=["refused", "too-large"])
def test_a_refused_post_over_the_drain_cap_is_answered_or_closed_never_hung(
    served: Served, proxied: bool
) -> None:
    """A body far over what the Library drains (a proxy's POST, refused at the gate; this machine's
    own, over the most a form may carry, a 413): the client gets its status or a closed connection,
    a reset at worst, within a few seconds, never a hang; and nothing is written."""
    head = str(served.site.lb.meta["head"])
    size = 16 * serve.DRAIN_BYTES + max(serve.FORM_BYTES, serve.DRAIN_BYTES)
    headers = [*_here(served), VIA] if proxied else _here(served)
    started = time.monotonic()
    with socket.create_connection((LOOPBACK, served.port), timeout=10) as sock:
        sock.sendall(_head("/star", headers, size))

        def send() -> None:
            with contextlib.suppress(OSError):  # the server stopped reading and closed: the rest is unwanted
                sock.sendall(b"x" * size)

        sender = threading.Thread(target=send, daemon=True)
        sender.start()
        try:
            outcome: tuple[int, str] | str = _reply(sock)
        except (ConnectionResetError, ConnectionAbortedError):
            outcome = "reset"
        except AssertionError:
            outcome = "closed"
        sender.join(timeout=10)
    assert time.monotonic() - started < 10 + 1, "hung"
    assert not sender.is_alive(), "the client's send hung"
    if isinstance(outcome, tuple):
        assert outcome[0] == (403 if proxied else 413), outcome
        assert ("nothing was written" in outcome[1]) if proxied else ("at most" in outcome[1])
    if proxied:  # refused at the gate, nothing read (the owner's own 413 is a page, its footer read)
        assert "current" not in served.reads
    assert str(served.site.lb.meta["head"]) == head


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_a_content_length_of_digits_that_are_not_ascii_is_answered(served: Served, method: str) -> None:
    """`"²".isdigit()` is true and `int("²")` raises: a Content-Length of such a digit (latin-1, as
    headers are read) is no length, and the request is answered, never a traceback and a dropped
    connection."""
    with socket.create_connection((LOOPBACK, served.port), timeout=30) as sock:
        head = f"{method} /star HTTP/1.1\r\nHost: {LOOPBACK}:{served.port}\r\nContent-Length: \u00b2\r\n"
        sock.sendall(f"{head}Connection: close\r\n\r\n".encode("latin-1"))
        status, _ = _reply(sock)
    assert 200 <= status < 500, status
