"""Who may read the Library: this machine, and the owner's named phone through Tailscale Serve, never
Funnel. A page asked with a Host that is not this machine's (`rebind.example`, a name a website the
owner opens can point at 127.0.0.1, or `0.0.0.0`) is a 421 and nothing is read; a request through
Tailscale Serve is read only when `logbook setup phone` names the phone and the request is the
phone's (one Host, its host; one login, its login; no Funnel), else a 403 and nothing read. No
page can be framed: every policy says `frame-ancestors 'none'` and every answer `X-Frame-Options:
DENY`. On the Oslo persona's fortnight (`persona.py`), who does not exist; the tailnet name and the
logins are invented."""

from __future__ import annotations

import http.client
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import persona_record

from logbook.contrib import doors, library_build, phone, serve
from logbook.core.store import Logbook

JUNE = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)  # the fortnight's last day, the morning
WEDNESDAY = "2026-06-17"  # a Day the build writes
LOOPBACK = "127.0.0.1"
HOST = "server.tail1234.ts.net"
LOGIN = "ines@example.org"
SETTING = {"origin": f"https://{HOST}", "login": LOGIN}
FORWARDED = [("X-Forwarded-For", "100.64.0.7"), ("X-Forwarded-Proto", "https"), ("X-Forwarded-Host", HOST)]
PAGES = ("/", f"/day/{WEDNESDAY}", "/people", "/shelves")


class Served:
    """A server over the persona's record, the build's pages served as built when `built`; `reads`
    names every reading and built page the server was asked for."""

    def __init__(self, lb: Logbook, built: bool) -> None:
        library = None
        if built:
            library = library_build.Library(lb, now=lambda: JUNE)
            library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
        self.site = serve.Site(lb, now=lambda: JUNE, library=library)
        self.reads: list[str] = []
        quick, current = self.site.quick, self.site.current

        def counted_quick(path: str, *args: Any, **kwargs: Any) -> serve.Response | None:
            self.reads.append(f"quick {path}")
            return quick(path, *args, **kwargs)

        def counted_current(*args: Any, **kwargs: Any) -> Any:
            self.reads.append("current")
            return current(*args, **kwargs)

        self.site.quick = counted_quick  # type: ignore[method-assign]
        self.site.current = counted_current  # type: ignore[method-assign]
        self.server = serve.Server(0, self.site)
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def get(self, path: str, headers: list[tuple[str, str]], method: str = "GET") -> http.client.HTTPResponse:
        """A request with the headers as given, a name twice when it is listed twice, and no Host but
        the ones listed."""
        connection = http.client.HTTPConnection(LOOPBACK, self.port, timeout=30)
        try:
            connection.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for name, value in headers:
                connection.putheader(name, value)
            connection.endheaders()
            reply = connection.getresponse()
            reply.read()
            return reply
        finally:
            connection.close()


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


def _here(port: int) -> list[tuple[str, str]]:
    return [("Host", f"{LOOPBACK}:{port}")]


def _phone(login: str = LOGIN) -> list[tuple[str, str]]:
    return [("Host", HOST), *FORWARDED, (phone.LOGIN_HEADER, login)]


def test_a_built_page_is_one_the_build_wrote(served: Served) -> None:
    """The fixture's premise: with the build, the Wednesday is answered as built, without a reading."""
    if served.site.library is None:
        pytest.skip("the live server builds nothing")
    assert served.site.library.pages().get(f"/day/{WEDNESDAY}") is not None


@pytest.mark.parametrize("path", PAGES)
def test_this_machine_reads_every_page(served: Served, path: str) -> None:
    for headers in (
        _here(served.port),
        [("Host", f"[::1]:{served.port}")],
        [("Host", f"localhost:{served.port}")],
        [("Host", f"LocalHost:{served.port}")],
        [],  # an HTTP/1.0 client sends no Host
    ):
        reply = served.get(path, headers)
        assert reply.status == 200, (path, headers, reply.status)


@pytest.mark.parametrize("path", PAGES)
def test_the_named_phone_reads_every_page(served: Served, path: str) -> None:
    reply = served.get(path, _phone())
    assert reply.status == 200, (path, reply.status)
    reply = served.get(path, [("Host", f"{HOST}:443"), (phone.LOGIN_HEADER, LOGIN)])
    assert reply.status == 200, (path, reply.status)


@pytest.mark.parametrize("path", PAGES)
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_a_host_that_is_not_this_machine_is_a_421_and_nothing_read(
    served: Served, path: str, method: str
) -> None:
    port = served.port
    for headers in (
        [("Host", f"rebind.example:{port}")],
        [("Host", "rebind.example")],
        [("Host", f"0.0.0.0:{port}")],
        [("Host", f"127.0.0.2:{port}")],
        [("Host", f"localhost.rebind.example:{port}")],
        [("Host", f"{LOOPBACK}:{port + 1 if port < 65535 else port - 1}")],  # another port is another server
        [("Host", LOOPBACK)],  # port 80: not this server
    ):
        served.reads.clear()
        reply = served.get(path, headers, method)
        assert reply.status == 421, (path, headers, reply.status)
        assert served.reads == [], (path, headers, served.reads)
        assert reply.getheader("X-Frame-Options") == "DENY"


@pytest.mark.parametrize("path", PAGES)
def test_a_proxied_request_that_is_not_the_phone_s_is_a_403_and_nothing_read(
    served: Served, path: str
) -> None:
    port = served.port
    for headers in (
        [("Host", HOST), *FORWARDED],  # a ts.net Host and no login: a tagged device, or curl
        [("Host", HOST)],
        _phone("ola@example.org"),  # a wrong login
        [("Host", HOST), *FORWARDED, (phone.LOGIN_HEADER, "ola@example.org"), (phone.LOGIN_HEADER, LOGIN)],
        [("Host", HOST), ("Host", HOST), (phone.LOGIN_HEADER, LOGIN)],  # two Host headers
        [("Host", f"{LOOPBACK}:{port}"), ("Host", f"{LOOPBACK}:{port}")],
        [*_phone(), ("Tailscale-Funnel-Request", "?1")],  # Funnel: the open internet
        [("Host", HOST), ("Tailscale-Funnel-Request", "?1")],
        [("Host", "laptop.tail1234.ts.net"), *FORWARDED, (phone.LOGIN_HEADER, LOGIN)],  # another tailnet name
        [("Host", f"{LOOPBACK}:{port}"), *FORWARDED],  # loopback, but through a proxy
        [("Host", f"{LOOPBACK}:{port}"), (phone.LOGIN_HEADER, LOGIN)],
    ):
        served.reads.clear()
        reply = served.get(path, headers)
        assert reply.status == 403, (path, headers, reply.status)
        assert served.reads == [], (path, headers, served.reads)


def test_without_the_setting_every_proxied_request_is_refused(served: Served) -> None:
    served.site.lb.set_meta(**{phone.KEY: None})
    for path in PAGES:
        served.reads.clear()
        reply = served.get(path, _phone())
        assert reply.status == 403, (path, reply.status)
        assert served.reads == []
        assert served.get(path, _here(served.port)).status == 200


def test_the_refusal_names_nothing_of_the_record(served: Served) -> None:
    connection = http.client.HTTPConnection(LOOPBACK, served.port, timeout=30)
    try:
        connection.putrequest("GET", f"/day/{WEDNESDAY}", skip_host=True)
        connection.putheader("Host", f"rebind.example:{served.port}")
        connection.endheaders()
        reply = connection.getresponse()
        text = reply.read().decode("utf-8")
    finally:
        connection.close()
    assert reply.status == 421
    assert "Nordmann" not in text and "Kari" not in text and "Ola" not in text and WEDNESDAY not in text
    meta = served.site.lb.meta
    assert str(meta["head"])[:12] not in text and str(meta["timezone"]) not in text, "no head, no timezone"


def _post(served: Served, path: str, headers: list[tuple[str, str]]) -> tuple[int, str]:
    body = b"act=star&line=x&day=2026-06-17"
    connection = http.client.HTTPConnection(LOOPBACK, served.port, timeout=30)
    try:
        connection.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
        for name, value in [
            *headers,
            ("Content-Type", "application/x-www-form-urlencoded"),
            ("Content-Length", str(len(body))),
        ]:
            connection.putheader(name, value)
        connection.endheaders(body)
        reply = connection.getresponse()
        return reply.status, reply.read().decode("utf-8")
    finally:
        connection.close()


@pytest.mark.parametrize("path", ["/star", "/nowhere", f"/day/{WEDNESDAY}/sign"])
def test_a_post_that_is_not_this_machine_s_or_the_phone_s_reads_nothing(served: Served, path: str) -> None:
    """A rebinding page is same-origin with its own name and could read a POST's refusal: it is the
    same 421 (or 403 through a proxy) before the body is read, naming neither the head nor the
    timezone, and the head does not move."""
    meta = served.site.lb.meta
    head, zone = str(meta["head"]), str(meta["timezone"])
    port = served.port
    rebind = f"http://rebind.example:{port}"
    for headers, status in (
        ([("Host", f"rebind.example:{port}"), ("Origin", rebind)], 421),
        ([("Host", f"rebind.example:{port}")], 421),
        ([("Host", HOST), *FORWARDED], 403),
        ([*_phone(), ("Tailscale-Funnel-Request", "?1")], 403),
    ):
        served.reads.clear()
        found, text = _post(served, path, headers)
        assert found == status, (path, headers, found)
        assert head[:12] not in text and zone not in text, (path, headers)
        assert "nothing was written" in text, (path, headers)
        assert "current" not in served.reads, (path, headers, served.reads)
    assert str(served.site.lb.meta["head"]) == head


@pytest.mark.parametrize("name", ["Forwarded", "Via", "X-Real-IP"])
def test_a_proxy_s_other_headers_are_a_proxy_too(served: Served, name: str) -> None:
    """A proxy that names this machine as the Host still says it is one in `Forwarded`, `Via` or
    `X-Real-IP`: refused, as any proxy that is not the phone's."""
    value = {
        "Forwarded": "for=192.0.2.7;proto=https",
        "Via": "1.1 proxy.example.org",
        "X-Real-IP": "192.0.2.7",
    }
    for path in PAGES:
        served.reads.clear()
        reply = served.get(path, [*_here(served.port), (name, value[name])])
        assert reply.status == 403, (path, name, reply.status)
        assert served.reads == []


def test_a_logbook_json_that_cannot_be_read_refuses_the_phone(served: Served) -> None:
    """The phone's setting is read with each proxied request; a `logbook.json` that is not JSON is a
    403, never a dropped connection, and this machine reads as before."""
    meta_path = served.site.lb.meta_path
    kept = meta_path.read_bytes()
    try:
        meta_path.write_bytes(b"{ not json")
        reply = served.get("/people", _phone())
        assert reply.status == 403
    finally:
        meta_path.write_bytes(kept)
    assert served.get("/people", _phone()).status == 200


# -- framing ----------------------------------------------------------------------------------------------


def test_every_policy_forbids_framing() -> None:
    policies = {
        "CSP": serve.CSP,
        "DAY_CSP": serve.DAY_CSP,
        "DAY_IMAGES": serve.DAY_IMAGES,
        "DOOR_CSP": serve.DOOR_CSP,
        "PLACES_CSP": serve.PLACES_CSP,
        "WORLD_CSP": serve.WORLD_CSP,
        "doors.CSP": doors.CSP,
    }
    for name, policy in policies.items():
        assert "frame-ancestors 'none'" in [d.strip() for d in policy.split(";")], name


OTHERS = (
    "/favicon.ico",
    "/nowhere",
    "/star",
    f"/day/{JUNE.date()}",
    "/places",
)  # an icon, a 404, a 405, live


@pytest.mark.parametrize("path", [*PAGES, *OTHERS])
def test_every_answer_says_it_may_not_be_framed(served: Served, path: str) -> None:
    reply = served.get(path, _here(served.port))
    assert reply.getheader("X-Frame-Options") == "DENY", (path, reply.status)
    policy = reply.getheader("Content-Security-Policy")
    if policy is not None:
        assert "frame-ancestors 'none'" in policy, path


def test_a_policy_kept_by_an_older_build_is_sent_unframed(served: Served) -> None:
    """A page built before every policy forbade frames keeps its policy in `pages.json`; it is sent
    with the clause added, and a policy without it gets it too."""
    old = serve.CSP.replace("; frame-ancestors 'none'", "")
    assert "frame-ancestors" not in old
    assert "frame-ancestors 'none'" in serve.Response(200, b"", csp=old).headers["Content-Security-Policy"]
    library = served.site.library
    if library is None:
        return
    manifest = library.folder / library_build.MANIFEST
    manifest.write_text(manifest.read_text("utf-8").replace("; frame-ancestors 'none'", ""), "utf-8")
    assert "frame-ancestors" not in manifest.read_text("utf-8")
    reply = served.get(f"/day/{WEDNESDAY}", _here(served.port))
    assert reply.status == 200
    assert "frame-ancestors 'none'" in (reply.getheader("Content-Security-Policy") or "")
