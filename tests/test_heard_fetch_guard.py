"""`sync heard`'s guard on every fetch (S3): only the public internet, only the address that was checked.
An address that is not global (the tailnet's 100.64.0.0/10, Tailscale's 100.100.100.100 and a MagicDNS
name that resolves into it among them) is never connected to; the connection goes to the address the
check resolved, never to a second answer of the resolver (a rebinding name), on the first request and on
every redirect, and never through a proxy the environment names; an https page that redirects to http,
and a port other than 80 and 443, are refused. The real opener runs here over a fake socket: nothing
leaves the machine. Synthetic: invented podcasts and the Oslo persona, who does not exist."""

from __future__ import annotations

import io
import json
import socket
from pathlib import Path
from typing import Any

import pytest
from test_heard_sync import FEED, PUBLIC, VTT, FakeTransport, _heard, _listen, _resolve, _run

from logbook.contrib.adapters import heard as step
from logbook.core import policy
from logbook.core.store import Logbook

TZ = "Europe/Oslo"
PUBLIC_2 = "93.184.215.15"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    import os

    lb = Logbook.init(Path(os.environ["LOGBOOK_HOME"]), TZ)
    data = policy.read(lb.root)
    data["heard"] = {"max_tier": 2, "fetch": True}  # the fetches are the owner's to turn on (S9)
    policy.policy_path(lb.root).write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setenv("LOGBOOK_HEARD", "feed")
    monkeypatch.setattr(step, "sleep", lambda _s: None)
    return lb


class FakeSocket:
    """What `socket.create_connection` hands back here: it records what was sent and answers with the
    bytes of one HTTP response."""

    def __init__(self, answer: bytes) -> None:
        self.answer = answer
        self.sent = b""

    def sendall(self, data: bytes) -> None:
        self.sent += data

    def makefile(self, *args: Any, **kwargs: Any) -> io.BytesIO:
        return io.BytesIO(self.answer)

    def setsockopt(self, *args: Any) -> None:
        return None

    def close(self) -> None:
        return None


class Network:
    """`socket.create_connection` with nothing reaching a real host: every address asked is recorded,
    and an address in `answers` gets that response, any other a refused connection."""

    def __init__(self, answers: dict[tuple[str, int], bytes] | None = None) -> None:
        self.answers = answers or {}
        self.connects: list[tuple[str, int]] = []
        self.sockets: list[FakeSocket] = []

    def __call__(self, address: tuple[str, int], *args: Any, **kwargs: Any) -> FakeSocket:
        host, port = address[0], int(address[1])
        self.connects.append((host, port))
        if (host, port) not in self.answers:
            raise ConnectionRefusedError("no network in the tests")
        sock = FakeSocket(self.answers[(host, port)])
        self.sockets.append(sock)
        return sock


def _network(monkeypatch: pytest.MonkeyPatch, answers: dict[tuple[str, int], bytes] | None = None) -> Network:
    net = Network(answers)
    monkeypatch.setattr(socket, "create_connection", net)

    def no_raw_connect(self: socket.socket, address: Any) -> None:
        raise AssertionError(f"a raw connect to {address!r}")

    monkeypatch.setattr(socket.socket, "connect", no_raw_connect)
    return net


class Rebinding:
    """A resolver that answers `first` the first time a host is asked and loopback every time after."""

    def __init__(self, first: dict[str, str]) -> None:
        self.first = first
        self.asked: list[str] = []

    def __call__(self, host: str, port: Any, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
        self.asked.append(host)
        address = self.first.get(host, PUBLIC) if self.asked.count(host) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]


def _response(code: int, headers: dict[str, str], body: bytes = b"") -> bytes:
    reason = {200: "OK", 302: "Found"}[code]
    head = "".join(f"{k}: {v}\r\n" for k, v in {**headers, "Content-Length": str(len(body))}.items())
    return f"HTTP/1.1 {code} {reason}\r\n{head}\r\n".encode("ascii") + body


@pytest.mark.parametrize(
    "url",
    ["http://100.101.102.103/t.vtt", "https://100.100.100.100/t.vtt", "http://[::ffff:100.64.0.1]/t.vtt"],
)
def test_a_tailnet_address_written_out_is_never_connected_to(
    url: str, lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "On the tailnet", url)
    net = _network(monkeypatch)
    _resolve(monkeypatch, {str(url.split("/")[2]).strip("[]"): (url.split("/")[2].strip("[]"),)})

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert net.connects == []
    assert "1 private host" in out and not _heard(lb)


@pytest.mark.parametrize("address", ["100.101.102.103", "100.100.100.100", "198.18.0.1", "192.0.2.7"])
def test_a_name_that_resolves_to_an_address_that_is_not_global_is_never_connected_to(
    address: str, lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "MagicDNS", "https://boat.tail0000.ts.net/t.vtt")
    net = _network(monkeypatch)
    _resolve(monkeypatch, {"boat.tail0000.ts.net": (address,)})

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert net.connects == [] and "1 private host" in out


def test_a_rebinding_resolver_never_gets_the_connection_to_loopback(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Rebound", "https://rebind.example.org/t.vtt")
    net = _network(monkeypatch)
    resolver = Rebinding({"rebind.example.org": PUBLIC})
    monkeypatch.setattr(socket, "getaddrinfo", resolver)

    status, _out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert resolver.asked == ["rebind.example.org"], "resolved once, and that answer is the one connected to"
    assert net.connects == [(PUBLIC, 443)]
    assert ("127.0.0.1", 443) not in net.connects


def test_a_proxy_the_environment_names_is_never_used(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, "http://proxy.example.org:3128")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Direct", "http://havn.example.org/t.vtt")
    net = _network(monkeypatch, {(PUBLIC, 80): _response(200, {"Content-Type": "text/vtt"}, VTT)})
    _resolve(monkeypatch)

    status, _out, err = _run(capsys, "sync", "heard")

    assert status == 0, err
    assert net.connects == [(PUBLIC, 80)]
    (line,) = _heard(lb)
    assert line["payload"]["title"] == "Direct"


def test_every_redirect_hop_connects_to_the_address_it_checked_and_sends_the_name_as_host(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Moved", "http://havn.example.org/a.vtt")
    net = _network(
        monkeypatch,
        {
            (PUBLIC, 80): _response(302, {"Location": "http://cdn.example.org/b.vtt"}),
            (PUBLIC_2, 80): _response(200, {"Content-Type": "text/vtt"}, VTT),
        },
    )
    resolver = Rebinding({"havn.example.org": PUBLIC, "cdn.example.org": PUBLIC_2})
    monkeypatch.setattr(socket, "getaddrinfo", resolver)

    status, _out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert resolver.asked == ["havn.example.org", "cdn.example.org"]
    assert net.connects == [(PUBLIC, 80), (PUBLIC_2, 80)]
    assert b"Host: havn.example.org\r\n" in net.sockets[0].sent
    assert b"Host: cdn.example.org\r\n" in net.sockets[1].sent
    assert len(_heard(lb)) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://havn.example.org:8443/t.vtt",
        "http://havn.example.org:8080/t.vtt",
        "https://havn.example.org:22/t",
    ],
)
def test_a_port_other_than_80_and_443_is_never_connected_to(
    url: str, lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Odd port", url)
    net = _network(monkeypatch)
    _resolve(monkeypatch)

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert net.connects == [] and "1 port" in out


def test_an_https_page_that_redirects_to_http_is_refused_and_never_requested(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Downgraded", f"{FEED}/a.vtt")
    _listen(lb, "2026-10-14T07:00:00Z", "EP-2", "Odd port", f"{FEED}/b.vtt")
    transport = FakeTransport(
        {
            f"{FEED}/a.vtt": (302, {"Location": "http://cdn.example.org/a.vtt"}, b""),
            f"{FEED}/b.vtt": (302, {"Location": "https://cdn.example.org:8443/b.vtt"}, b""),
        }
    )
    transport.install(monkeypatch)

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert transport.requests == [f"{FEED}/a.vtt", f"{FEED}/b.vtt"]
    assert "1 redirect from https to http" in out and "1 port" in out and not _heard(lb)


@pytest.mark.parametrize(
    "url", ["http://a.example%3A22/t.vtt", "https://a.example%3a8443/t.vtt", "http://a.exa%6Dple/t.vtt"]
)
def test_a_host_with_an_escape_in_it_is_never_connected_to(
    url: str, lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """urllib unquotes a host before `http.client` reads its port from it, so `a.example%3A22` would
    connect to port 22 of an address the check took for port 80: a host is a name, and an escape in it
    is refused before any lookup."""
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Escaped", url)
    net = _network(monkeypatch)
    resolver = _resolve(monkeypatch)

    status, out, err = _run(capsys, "sync", "heard")

    assert status == 0 and "Traceback" not in err, err
    assert net.connects == [] and resolver.asked == [] and "1 private host" in out


def test_each_checked_address_is_tried_in_turn_and_no_other(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _listen(lb, "2026-10-14T06:00:00Z", "EP-1", "Two addresses", "http://havn.example.org/t.vtt")
    net = _network(monkeypatch, {(PUBLIC_2, 80): _response(200, {"Content-Type": "text/vtt"}, VTT)})
    _resolve(monkeypatch, {"havn.example.org": (PUBLIC, PUBLIC_2)})

    status, _out, err = _run(capsys, "sync", "heard")

    assert status == 0, err
    assert net.connects == [(PUBLIC, 80), (PUBLIC_2, 80)] and len(_heard(lb)) == 1
