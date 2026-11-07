"""The edges the privacy review of 26 October left (its LATER list), on the Library's phone check.

Every header a proxy adds makes a request a proxy's, on a read and on a write: `Forwarded`, `Via` and
`X-Real-IP` as well as `Tailscale-*` and `X-Forwarded-*`, whatever their case; a request is this
machine's own only when it carries none of them. And the check is one login at a time: tailscaled
keeps one connection to the Library open for many requests (HTTP/1.1 keep-alive), so the first request
on a connection says whose it is, and a later request on it that names another login, or none, or
comes from this machine on a connection the phone opened, is refused and the connection closed; no
answer one login was given (a page, its ETag) is ever another's. On the Oslo persona's fortnight
(`persona.py`), who does not exist; the tailnet name and the logins are invented."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest
from persona import persona_record
from test_serve_hosts import FORWARDED, HOST, LOGIN, LOOPBACK, PAGES, SETTING, WEDNESDAY, Served, _post

from logbook.contrib import phone

OLA = "ola@example.org"  # a second login on the same tailnet
ORIGIN = f"https://{HOST}"
OTHERS = {  # the proxy headers that are not Tailscale's nor X-Forwarded-*, each as a proxy writes it
    "Forwarded": "for=192.0.2.7;proto=https",
    "Via": "1.1 proxy.example.org",
    "X-Real-IP": "192.0.2.7",
}


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


def _phone(login: str | None = LOGIN) -> list[tuple[str, str]]:
    return [("Host", HOST), *FORWARDED, *([(phone.LOGIN_HEADER, login)] if login is not None else [])]


def _here(port: int) -> list[tuple[str, str]]:
    return [("Host", f"{LOOPBACK}:{port}")]


# -- every proxy header ---------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [*OTHERS, "forwarded", "VIA", "x-real-ip"])
def test_every_proxy_header_makes_a_request_a_proxy_s(name: str) -> None:
    """The check itself: a loopback Host with any proxy's header is not this machine's own, on a read
    (`here`) or a write (`proxied`), whatever the header's case."""
    value = OTHERS.get(name) or next(v for k, v in OTHERS.items() if k.lower() == name.lower())
    asked = phone.Asked((), ("127.0.0.1:8765",), (), (), (name,))
    assert phone.proxied(asked) and not phone.here(asked, 8765) and phone.looks_proxied(asked)
    assert value  # the value is a proxy's own; the name alone decides

    class Headers:
        def __init__(self, pairs: list[tuple[str, str]]) -> None:
            self.pairs = pairs

        def __iter__(self) -> Iterator[str]:
            return iter(n for n, _ in self.pairs)

        def get_all(self, wanted: str) -> list[str] | None:
            found = [v for n, v in self.pairs if n.lower() == wanted.lower()]
            return found or None

    of = phone.Asked.of(Headers([("Host", "127.0.0.1:8765"), (name, value)]))
    assert of.forwarded == (name,) and phone.proxied(of) and not phone.here(of, 8765)


def test_this_machine_s_own_carries_no_proxy_header_and_a_loopback_literal() -> None:
    """A write is this machine's own only with no proxy header and a Host that is a loopback literal:
    `localhost` is a name, and a write that names it is a proxy's to the write gate."""
    plain = phone.Asked((), ("127.0.0.1:8765",), (), ())
    assert not phone.proxied(plain)
    assert not phone.proxied(phone.Asked((), ("[::1]:8765",), (), ()))
    assert phone.proxied(phone.Asked((), ("localhost:8765",), (), ()))
    assert phone.proxied(phone.Asked((), ("server.tail1234.ts.net",), (), ()))


@pytest.mark.parametrize("name", list(OTHERS))
def test_a_post_with_any_proxy_header_is_refused_and_writes_nothing(served: Served, name: str) -> None:
    """A POST that names this machine as its Host and its Origin, through a proxy that says so only in
    `Forwarded`, `Via` or `X-Real-IP`: refused before its body is read, and nothing written."""
    head = str(served.site.lb.meta["head"])
    origin = f"http://{LOOPBACK}:{served.port}"
    for path in ("/star", f"/day/{WEDNESDAY}/sign"):
        served.reads.clear()
        status, text = _post(served, path, [*_here(served.port), ("Origin", origin), (name, OTHERS[name])])
        assert status == 403, (path, name, status)
        assert "nothing was written" in text
        assert "current" not in served.reads
    assert str(served.site.lb.meta["head"]) == head


# -- one login at a time --------------------------------------------------------------------------------


class Reply(NamedTuple):
    status: int
    headers: dict[str, str]  # by name in lower case
    body: bytes

    def getheader(self, name: str) -> str | None:
        return self.headers.get(name.lower())


class Connection:
    """One kept-alive connection to the server, as tailscaled holds one, on a socket of its own (never
    `http.client`, which opens a new connection when the server closes one): each request with the
    headers as given and no Host but the ones listed."""

    def __init__(self, served: Served) -> None:
        self.sock = socket.create_connection((LOOPBACK, served.port), timeout=30)
        self.buffer = b""

    def send(self, method: str, path: str, headers: list[tuple[str, str]], body: bytes = b"") -> Reply:
        head = f"{method} {path} HTTP/1.1\r\n" + "".join(f"{n}: {v}\r\n" for n, v in headers) + "\r\n"
        self.sock.sendall(head.encode("latin-1") + body)
        while b"\r\n\r\n" not in self.buffer:
            self._more()
        raw, _, self.buffer = self.buffer.partition(b"\r\n\r\n")
        status_line, *rest = raw.decode("latin-1").split("\r\n")
        found = {k.strip().lower(): v.strip() for k, _, v in (h.partition(":") for h in rest)}
        length = int(found.get("content-length", "0"))
        while len(self.buffer) < length and method != "HEAD":
            self._more()
        got, self.buffer = self.buffer[:length], self.buffer[length:]
        return Reply(int(status_line.split()[1]), found, got)

    def get(self, path: str, headers: list[tuple[str, str]]) -> Reply:
        return self.send("GET", path, headers)

    def _more(self) -> None:
        chunk = self.sock.recv(65536)
        if not chunk:
            raise ConnectionResetError("closed")
        self.buffer += chunk

    def answered(self, path: str, headers: list[tuple[str, str]]) -> int | None:
        """The status of one more request on this connection, None when the server closed it."""
        try:
            return self.get(path, headers).status
        except OSError:
            return None

    def close(self) -> None:
        self.sock.close()


@pytest.fixture
def connection(served: Served) -> Iterator[Connection]:
    c = Connection(served)
    try:
        yield c
    finally:
        c.close()


def test_one_login_reads_on_and_on_over_one_connection(served: Served, connection: Connection) -> None:
    """The premise: the phone's requests share a connection, and each is answered."""
    for path in (*PAGES, *PAGES):
        reply = connection.get(path, _phone())
        assert reply.status == 200, (path, reply.status)
        assert (reply.getheader("Connection") or "").lower() != "close"


@pytest.mark.parametrize(
    "then",
    [
        pytest.param(_phone(OLA), id="another-login"),
        pytest.param(_phone(None), id="no-login"),
        pytest.param([*_phone(), (phone.LOGIN_HEADER, OLA)], id="two-logins"),
    ],
)
def test_a_login_that_changes_on_a_connection_is_refused_and_the_connection_closed(
    served: Served, connection: Connection, then: list[tuple[str, str]]
) -> None:
    """The phone's login opened the connection; a request on it that names another login, or none, is
    refused, and the connection is closed, so not even the phone's own next request is read on it."""
    assert connection.get("/people", _phone()).status == 200
    served.reads.clear()
    reply = connection.get("/people", then)
    assert reply.status == 403
    assert (reply.getheader("Connection") or "").lower() == "close"
    assert "current" not in served.reads
    assert connection.answered("/people", _phone()) is None


def test_this_machine_on_a_connection_the_phone_opened_is_refused(
    served: Served, connection: Connection
) -> None:
    """A connection is one party's: this machine's own request on the phone's connection, or the
    phone's on this machine's, is a change of who is asking, refused and the connection closed."""
    assert connection.get("/people", _phone()).status == 200
    reply = connection.get("/people", _here(served.port))
    assert reply.status == 403 and (reply.getheader("Connection") or "").lower() == "close"
    other = Connection(served)
    try:
        assert other.get("/people", _here(served.port)).status == 200
        reply = other.get("/people", _phone())
        assert reply.status == 403 and (reply.getheader("Connection") or "").lower() == "close"
    finally:
        other.close()


def test_a_post_whose_login_changes_on_the_connection_writes_nothing(
    served: Served, connection: Connection
) -> None:
    head = str(served.site.lb.meta["head"])
    assert connection.get("/people", _phone()).status == 200
    body = b"act=star&line=x&day=2026-06-17"
    headers = [
        *_phone(OLA),
        ("Origin", ORIGIN),
        ("Content-Type", "application/x-www-form-urlencoded"),
        ("Content-Length", str(len(body))),
    ]
    reply = connection.send("POST", "/star", headers, body)
    text = reply.body.decode("utf-8")
    assert reply.status == 403 and "nothing was written" in text
    assert str(served.site.lb.meta["head"]) == head


def test_a_page_one_login_was_given_is_never_another_s(served: Served) -> None:
    """No decision is kept between requests: the ETag the phone's login was given, sent by another
    login on a fresh connection, is a refusal, never a 304 that says the page is unchanged."""
    first = Connection(served)
    try:
        reply = first.get(f"/day/{WEDNESDAY}", _phone())
        assert reply.status == 200
        etag = reply.getheader("ETag")
    finally:
        first.close()
    other = Connection(served)
    try:
        headers = _phone(OLA) + ([("If-None-Match", etag)] if etag else [])
        assert other.get(f"/day/{WEDNESDAY}", headers).status == 403
    finally:
        other.close()
