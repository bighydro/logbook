"""The owner's own phone writes through the Library: behind `tailscale serve --bg 8765` the phone reads
the Day at `https://server.tail1234.ts.net/today`, tailscaled forwards each request to 127.0.0.1:8765
from loopback, and a form's POST carries the browser's `Origin: https://server.tail1234.ts.net`, the
`Host` it asked for and the `Tailscale-User-Login` Tailscale Serve sets. Off by default: without
`phone` in `logbook.json` that POST is refused as it always was. With it, the POST is answered as
this machine's is only when the client, the Origin, the Host and the login all match, and any one
of them alone refuses it with nothing written. `logbook setup phone` writes the setting, and only
it. On the four synthetic years (`library_record.py`), the orgs record and the ideas record; the
tailnet name and the login are invented, and nobody and nothing here exists."""

from __future__ import annotations

import builtins
import html
import http.client
import io
import json
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode

import pytest
import test_library_walk as walk
import test_serve_browser_origin as origins

from logbook import cli
from logbook.contrib import doctor, phone, serve
from logbook.core.store import Logbook

ORIGIN = "https://server.tail1234.ts.net"
HOST = "server.tail1234.ts.net"
LOGIN = "ines@example.org"
SETTING = {"origin": ORIGIN, "login": LOGIN}
TAILNET_PEER = "192.0.2.7"  # a documentation address (RFC 5737): any client that is not loopback
WITH_FORM = {"day": walk.DAY, "names": f"{walk.ASTRID['name']}, Bjørn Lie", "at": "13:30"}  # the walk's With

years = walk.years
manifest = walk.manifest
shelf_of_ideas = walk.shelf_of_ideas


def _acts(root: Path, years: Path, manifest: Path, ideas: Path, mp: pytest.MonkeyPatch) -> list[walk.Act]:
    return origins._acts(root, years, manifest, ideas, mp)


def _set(acts: list[walk.Act], setting: object = SETTING) -> None:
    for root in {a.site.lb.root for a in acts}:
        Logbook(root).set_meta(**{phone.KEY: setting})


def _record(acts: list[walk.Act]) -> dict[Path, tuple[dict[str, bytes], str]]:
    roots = {a.site.lb.root for a in acts}
    return {root: (walk._files(root), str(Logbook(root).meta["head"])) for root in roots}


def _from_the_phone(act: walk.Act) -> str | None:
    """The Origin the phone's browser sends for the act: the page that carries its form read as the
    phone reads it (through Tailscale Serve, so from loopback), its own `Referrer-Policy` applied."""
    page = origins._page_of(act)
    response = act.site.respond(*page.partition("?")[::2])
    assert response.status == 200, (walk._kind(act), page, response.status)
    text = response.body.decode("utf-8")
    forms = [
        f
        for f in walk._forms(text)
        if f.action == act.path and all(f.fields[k] == act.form.get(k) for k in origins.KEYS if k in f.fields)
    ]
    assert forms, (walk._kind(act), page, "the page carries the act's form")
    return origins.browser_origin(response.headers["Referrer-Policy"], ORIGIN + page, ORIGIN + act.path)


def _asked(
    origin: str | None = ORIGIN,
    host: str | None = HOST,
    login: str | None = LOGIN,
    dest: str | None = None,
    forwarded: tuple[str, ...] = ("X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host"),
) -> phone.Asked:
    """The headers as tailscaled forwards the phone's POST: its Origin, Host and login, and the
    `X-Forwarded-*` it adds."""
    one = lambda value: () if value is None else (value,)  # noqa: E731
    names = (*forwarded, *((phone.LOGIN_HEADER,) if login is not None else ()))
    return phone.Asked(one(origin), one(host), one(login), one(dest), names)


# -- without the setting ----------------------------------------------------------------------------------


def test_without_the_setting_the_phone_is_refused_on_every_act(
    years: Path, manifest: Path, shelf_of_ideas: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off by default: the phone's Origin with Tailscale Serve's identity header is a 403 on every act
    of #315's walk, the refusal saying what would allow it, and not a byte of any record changes."""
    acts = _acts(tmp_path, years, manifest, shelf_of_ideas, monkeypatch)
    sent = [_from_the_phone(act) for act in acts]
    assert set(sent) == {ORIGIN}
    before = _record(acts)
    for act, origin in zip(acts, sent, strict=True):
        response = act.site.write(act.path, act.form, walk.LOOPBACK, origin, act.upload, asked=_asked(origin))
        page = html.unescape(response.body.decode("utf-8"))
        assert response.status == 403, (walk._kind(act), response.status)
        assert "nothing was written" in page and "from this machine only" in page, walk._kind(act)
        assert "or from your phone once `logbook setup phone` names it" in page, walk._kind(act)
    assert _record(acts) == before


# -- with the setting -------------------------------------------------------------------------------------


def test_with_the_setting_every_act_from_the_phone_is_answered_as_from_this_machine(
    years: Path, manifest: Path, shelf_of_ideas: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With `phone` set, every act posted from the phone (client loopback, the page's own Origin as
    the phone's browser derives it, the tailnet name as Host, the owner's login) is answered as the
    same act from this machine is: the same 303 to the same place, or the same page."""
    today = [
        origins._answer(
            a.site.write(a.path, a.form, walk.LOOPBACK, f"http://{walk.LOOPBACK}:{origins.PORT}", a.upload)
        )
        for a in _acts(tmp_path / "today", years, manifest, shelf_of_ideas, monkeypatch)
    ]
    acts = _acts(tmp_path / "phone", years, manifest, shelf_of_ideas, monkeypatch)
    _set(acts)
    sent = [_from_the_phone(act) for act in acts]
    assert set(sent) == {ORIGIN}
    found = [
        origins._answer(a.site.write(a.path, a.form, walk.LOOPBACK, o, a.upload, asked=_asked(o)))
        for a, o in zip(acts, sent, strict=True)
    ]
    assert all(status != 403 for status, _ in found), found
    assert {status for status, _ in today} <= {303, 409} and today.count((303, None)) == 0, today
    assert found == today, [
        (walk._kind(a), f, t) for a, f, t in zip(acts, found, today, strict=True) if f != t
    ]


def test_the_origin_is_compared_after_its_normalisation(
    years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The host case-insensitive, the default port written or not, a Host with `:443`: the same origin."""
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    site.lb.set_meta(**{phone.KEY: SETTING})
    form = WITH_FORM
    for origin, host in (
        ("https://Server.Tail1234.TS.net", HOST),
        ("https://server.tail1234.ts.net:443", "SERVER.tail1234.ts.net:443"),
    ):
        response = site.write(serve.WITH_PATH, form, walk.LOOPBACK, origin, asked=_asked(origin, host))
        assert response.status == 303, (origin, host, response.body)


REFUSALS = {
    "a-client-not-loopback": (TAILNET_PEER, _asked()),
    "another-ts-net-origin": (walk.LOOPBACK, _asked("https://laptop.tail1234.ts.net")),
    "another-tailnet": (walk.LOOPBACK, _asked("https://server.tail9999.ts.net")),
    "http-not-https": (walk.LOOPBACK, _asked("http://server.tail1234.ts.net")),
    "another-port": (walk.LOOPBACK, _asked("https://server.tail1234.ts.net:8443")),
    "no-login": (walk.LOOPBACK, _asked(login=None)),
    "another-login": (walk.LOOPBACK, _asked(login="ola@example.org")),
    "the-login-in-another-case": (walk.LOOPBACK, _asked(login="Ines@example.org")),
    "another-host": (walk.LOOPBACK, _asked(host="laptop.tail1234.ts.net")),
    "no-host": (walk.LOOPBACK, _asked(host=None)),
    "a-host-on-another-port": (walk.LOOPBACK, _asked(host="server.tail1234.ts.net:8443")),
    "origin-null": (walk.LOOPBACK, _asked("null")),
    "an-origin-with-a-path": (walk.LOOPBACK, _asked(ORIGIN + "/day")),
    "two-logins": (walk.LOOPBACK, phone.Asked((ORIGIN,), (HOST,), ("ola@example.org", LOGIN), ())),
    "two-hosts": (walk.LOOPBACK, phone.Asked((ORIGIN,), ("laptop.tail1234.ts.net", HOST), (LOGIN,), ())),
    "two-origins": (walk.LOOPBACK, phone.Asked(("https://example.org", ORIGIN), (HOST,), (LOGIN,), ())),
    "from-a-frame": (walk.LOOPBACK, _asked(dest="iframe")),
    "no-headers-passed": (walk.LOOPBACK, None),
}


@pytest.mark.parametrize(("client", "asked"), REFUSALS.values(), ids=REFUSALS.keys())
def test_with_the_setting_each_mismatch_alone_refuses_every_act(
    years: Path,
    manifest: Path,
    shelf_of_ideas: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: str,
    asked: phone.Asked | None,
) -> None:
    """Everything else as the phone sends it, one thing not: a client that is not loopback, another
    tailnet name, `http://`, another port, no login or another (logins are compared exactly), another
    Host or none, `Origin: null`, an origin with a path, a header sent twice, a form posted from inside
    a frame (`Sec-Fetch-Dest: iframe`, which a page that frames the Day would make). Each is a 403 on
    every act, and nothing is written."""
    acts = _acts(tmp_path, years, manifest, shelf_of_ideas, monkeypatch)
    _set(acts)
    before = _record(acts)
    origin = ORIGIN if asked is None or not asked.origin else asked.origin[-1]
    for act in acts:
        response = act.site.write(act.path, act.form, client, origin, act.upload, asked=asked)
        page = html.unescape(response.body.decode("utf-8"))
        assert response.status == 403, (walk._kind(act), response.status)
        assert "nothing was written" in page and "logbook setup phone" in page, walk._kind(act)
    assert _record(acts) == before


CURL = {  # a POST a program sends through Tailscale Serve, no Origin: what tailscaled forwards of it
    "the-tailnet-host": phone.Asked((), (HOST,), (), (), ("X-Forwarded-For", "X-Forwarded-Proto")),
    "the-tailnet-host-alone": phone.Asked((), (HOST,), (), (), ()),
    "with-a-forged-login": phone.Asked((), (HOST,), (LOGIN,), (), (phone.LOGIN_HEADER, "X-Forwarded-For")),
    "a-loopback-host-and-x-forwarded": phone.Asked((), ("127.0.0.1:8765",), (), (), ("X-Forwarded-For",)),
    "a-loopback-host-and-funnel": phone.Asked((), ("127.0.0.1:8765",), (), (), ("Tailscale-Funnel-Request",)),
    "a-loopback-host-and-a-login": phone.Asked((), ("[::1]:8765",), (LOGIN,), (), (phone.LOGIN_HEADER,)),
    "a-name-for-host": phone.Asked((), ("localhost:8765",), (), (), ()),
    "two-hosts": phone.Asked((), ("127.0.0.1:8765", HOST), (), (), ()),
}


@pytest.mark.parametrize("setting", [None, SETTING], ids=["setting-off", "setting-on"])
@pytest.mark.parametrize("asked", CURL.values(), ids=CURL.keys())
def test_a_post_without_origin_through_tailscale_is_refused_on_every_act(
    years: Path,
    manifest: Path,
    shelf_of_ideas: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    asked: phone.Asked,
    setting: dict[str, str] | None,
) -> None:
    """A request is proxied when its Host is not a loopback literal (127.0.0.1 or [::1], any port) or
    when it carries a `Tailscale-*` or `X-Forwarded-*` header; a proxied POST is answered only through
    the phone's checks. So `curl` from any device on the tailnet, with no Origin (and a login forged,
    or none), is a 403 on every act with the setting on and off, and nothing is written."""
    acts = _acts(tmp_path, years, manifest, shelf_of_ideas, monkeypatch)
    if setting is not None:
        _set(acts, setting)
    before = _record(acts)
    for act in acts:
        response = act.site.write(act.path, act.form, walk.LOOPBACK, None, act.upload, asked=asked)
        page = html.unescape(response.body.decode("utf-8"))
        assert response.status == 403, (walk._kind(act), response.status)
        assert "nothing was written" in page and "logbook setup phone" in page, walk._kind(act)
    assert _record(acts) == before


MACHINE = {  # this machine's own requests: the Air's browser, a tunnel, a program on the Air
    "no-headers-passed": None,
    "the-server-s-port": phone.Asked((), ("127.0.0.1:8765",), (), (), ()),
    "ipv6": phone.Asked((), ("[::1]:8765",), (), (), ()),
    "a-tunnel-s-port": phone.Asked((), ("127.0.0.1:8766",), (), (), ()),
    "no-port": phone.Asked((), ("127.0.0.1",), (), (), ()),
    "no-host": phone.Asked((), (), (), (), ()),
}


@pytest.mark.parametrize("setting", [None, SETTING], ids=["setting-off", "setting-on"])
@pytest.mark.parametrize("asked", MACHINE.values(), ids=MACHINE.keys())
def test_this_machine_s_own_requests_are_answered_as_today(
    years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asked: phone.Asked | None, setting: object
) -> None:
    """Host 127.0.0.1 or [::1], any port (or none, as an HTTP/1.0 client sends), and no proxy header:
    answered as today, with no Origin and with this machine's, the setting on or off; a client that is
    not loopback refused as today."""
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    if setting is not None:
        site.lb.set_meta(**{phone.KEY: setting})
    for origin in (None, f"http://{walk.LOOPBACK}:{origins.PORT}", f"http://[::1]:{origins.TUNNEL}"):
        assert site.write(serve.WITH_PATH, WITH_FORM, walk.LOOPBACK, origin, asked=asked).status == 303, (
            origin
        )
    assert site.write(serve.WITH_PATH, WITH_FORM, TAILNET_PEER, None, asked=asked).status == 403
    for refused in origins.REFUSED:
        assert site.write(serve.WITH_PATH, WITH_FORM, walk.LOOPBACK, refused, asked=asked).status == 403


def test_which_requests_are_proxied() -> None:
    assert not phone.proxied(None)
    for host in ("127.0.0.1", "127.0.0.1:8765", "[::1]", "[::1]:8766"):
        assert not phone.proxied(phone.Asked((), (host,), (), (), ())), host
    for host in ("localhost", "localhost:8765", "127.0.0.2:8765", "::1", "[::1]x", HOST, "127.0.0.1:x", ""):
        assert phone.proxied(phone.Asked((), (host,), (), (), ())), host
    for name in ("X-Forwarded-For", "x-forwarded-proto", "Tailscale-User-Login", "tailscale-funnel-request"):
        assert phone.proxied(phone.Asked((), ("127.0.0.1:8765",), (), (), (name,))), name


def test_this_machine_is_answered_as_before_with_the_setting(
    years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The setting adds the phone and takes nothing away: this machine's own origin, any port, is
    answered with the setting as without it, and the four origins refused today are refused still."""
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    site.lb.set_meta(**{phone.KEY: SETTING})
    form = WITH_FORM
    for at in (f"http://{walk.LOOPBACK}:{origins.PORT}", f"http://[::1]:{origins.TUNNEL}"):
        assert site.write(serve.WITH_PATH, form, walk.LOOPBACK, at).status == 303, at
    for refused in origins.REFUSED:
        assert site.write(serve.WITH_PATH, form, walk.LOOPBACK, refused, asked=_asked(refused)).status == 403


@pytest.mark.parametrize(
    "setting",
    [
        {"origin": "http://server.tail1234.ts.net", "login": LOGIN},
        {"origin": "https://example.org", "login": LOGIN},
        {"origin": ORIGIN},
        {"login": LOGIN},
        {"origin": ORIGIN, "login": ""},
        ORIGIN,
        [],
    ],
    ids=["http", "not-ts-net", "no-login", "no-origin", "empty-login", "a-string", "a-list"],
)
def test_a_setting_that_is_not_the_shape_lets_nothing_in(
    years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: object
) -> None:
    """A `phone` written by hand that the setup command would refuse opens nothing: the phone is
    refused as without it (and `doctor` says why), this machine answered as ever."""
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    site.lb.set_meta(**{phone.KEY: setting})
    form = WITH_FORM
    origin = setting.get("origin", ORIGIN) if isinstance(setting, dict) else ORIGIN
    assert site.write(serve.WITH_PATH, form, walk.LOOPBACK, origin, asked=_asked(origin)).status == 403
    assert site.write(serve.WITH_PATH, form, walk.LOOPBACK, f"http://{walk.LOOPBACK}:8765").status == 303


def test_the_setting_is_read_with_each_post(
    years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Library reads `logbook.json` on every request, as it reads `day_start`: the setting takes
    effect, and its removal too, without a restart."""
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    form = WITH_FORM
    assert site.write(serve.WITH_PATH, form, walk.LOOPBACK, ORIGIN, asked=_asked()).status == 403
    site.lb.set_meta(**{phone.KEY: SETTING})
    assert site.write(serve.WITH_PATH, form, walk.LOOPBACK, ORIGIN, asked=_asked()).status == 303
    meta = site.lb.meta
    del meta[phone.KEY]
    site.lb._save_meta(meta)
    assert site.write(serve.WITH_PATH, form, walk.LOOPBACK, ORIGIN, asked=_asked()).status == 403


# -- over the socket, as tailscaled forwards it ----------------------------------------------------------


@pytest.fixture
def served(years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[serve.Site, int]]:
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    site.lb.set_meta(**{phone.KEY: SETTING})
    server = serve.Server(0, site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield site, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(port: int, path: str, body: bytes, headers: list[tuple[str, str]]) -> tuple[int, str]:
    """A POST with the headers as given, a name twice when it is listed twice."""
    connection = http.client.HTTPConnection(walk.LOOPBACK, port, timeout=10)
    try:
        connection.putrequest("POST", path, skip_host=True)
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


def test_a_star_from_the_phone_over_the_socket(served: tuple[serve.Site, int]) -> None:
    """The handler hands the gate the headers tailscaled forwards: the Day read with the phone's Host,
    a row's Star posted with the phone's Origin, Host and login is a 303 and the line written; the
    same with another login, with the login twice or from a frame is a 403 and nothing more is written."""
    site, port = served
    connection = http.client.HTTPConnection(walk.LOOPBACK, port, timeout=10)
    try:
        connection.request("GET", f"/day/{walk.DAY}", headers={"Host": HOST, phone.LOGIN_HEADER: LOGIN})
        reply = connection.getresponse()
        text = reply.read().decode("utf-8")
        header = reply.getheader("Referrer-Policy")
    finally:
        connection.close()
    assert reply.status == 200
    star = next(f for f in walk._forms(text, "star"))
    origin = origins.browser_origin(header, f"{ORIGIN}/day/{walk.DAY}", ORIGIN + star.action)
    assert origin == ORIGIN
    body = urlencode({**star.fields, "act": "star"}).encode("utf-8")
    head = site.lb.meta["head"]
    sent = [
        ("Host", HOST),
        ("Origin", origin),
        (phone.LOGIN_HEADER, LOGIN),
        ("Sec-Fetch-Dest", "document"),
        ("X-Forwarded-For", "100.64.0.7"),
    ]
    status, _ = _post(port, star.action, body, sent)
    assert status == 303
    moved = Logbook(site.lb.root).meta["head"]
    assert moved != head, "the star is written"
    for refused in (
        [("Host", HOST), ("Origin", origin), (phone.LOGIN_HEADER, "ola@example.org")],
        [
            ("Host", HOST),
            ("Origin", origin),
            (phone.LOGIN_HEADER, "ola@example.org"),
            (phone.LOGIN_HEADER, LOGIN),
        ],
        [("Host", HOST), ("Origin", origin), (phone.LOGIN_HEADER, LOGIN), ("Sec-Fetch-Dest", "iframe")],
        [("Host", "laptop.tail1234.ts.net"), ("Origin", origin), (phone.LOGIN_HEADER, LOGIN)],
    ):
        status, page = _post(port, star.action, body, refused)
        assert status == 403 and "nothing was written" in page, refused
    assert Logbook(site.lb.root).meta["head"] == moved


# -- the setting: `logbook setup phone` ------------------------------------------------------------------


@pytest.fixture
def record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "Logbook"
    cli.main(["init", str(root), "--timezone", "Europe/Oslo"])
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook(root)
    lb.set_meta(day_start="06:00", owner_emails=["ines@example.org"])
    return lb


class _Terminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def _answer(monkeypatch: pytest.MonkeyPatch, answer: str, terminal: bool = True) -> list[str]:
    asked: list[str] = []

    def typed(prompt: str = "") -> str:
        asked.append(prompt)
        return answer

    monkeypatch.setattr(builtins, "input", typed)
    monkeypatch.setattr(sys, "stdin", _Terminal() if terminal else io.StringIO())
    return asked


def _rest(meta: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in meta.items() if k != phone.KEY}


def test_setup_phone_prints_what_it_writes_asks_and_writes_the_key_alone(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = record.meta
    asked = _answer(monkeypatch, "y")
    cli.main(["setup", "phone", "--origin", "https://Server.tail1234.ts.net:443", "--login", LOGIN])
    out = capsys.readouterr().out
    assert asked and "[y/N]" in asked[0]
    assert json.dumps({phone.KEY: SETTING}).strip("{}") in out  # what it writes, before it asks
    assert record.meta[phone.KEY] == SETTING
    assert _rest(record.meta) == before, "no other key of logbook.json moves"


def test_setup_phone_writes_nothing_without_a_yes(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = record.meta_path.read_bytes()
    for answer in ("", "n", "no"):
        _answer(monkeypatch, answer)
        cli.main(["setup", "phone", "--origin", ORIGIN, "--login", LOGIN])
        assert "nothing changed" in capsys.readouterr().out
        assert record.meta_path.read_bytes() == before


def test_setup_phone_asks_at_a_terminal_only(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner's yes, typed: piped input (a script, an agent) is refused and nothing written."""
    before = record.meta_path.read_bytes()
    asked = _answer(monkeypatch, "y", terminal=False)
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "phone", "--origin", ORIGIN, "--login", LOGIN])
    assert e.value.code == 2 and not asked
    assert "terminal" in capsys.readouterr().err
    assert record.meta_path.read_bytes() == before


@pytest.mark.parametrize(
    "origin",
    [
        "http://server.tail1234.ts.net",
        "https://server.example.org",
        "https://ts.net",
        "https://tail1234.ts.net",
        "https://server.tail1234.ts.net.example.org",
        "https://server.tail1234.ts.net/",
        "https://server.tail1234.ts.net/today",
        "https://server.tail1234.ts.net?x=1",
        "https://server.tail1234.ts.net#day",
        "https://server.tail1234.ts.net:8443",
        "https://ines@server.tail1234.ts.net",
        "https://100.64.0.1",
        "server.tail1234.ts.net",
        "null",
    ],
)
def test_setup_phone_refuses_an_origin_that_is_not_a_tailnet_name(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], origin: str
) -> None:
    before = record.meta_path.read_bytes()
    asked = _answer(monkeypatch, "y")
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "phone", "--origin", origin, "--login", LOGIN])
    err = capsys.readouterr().err
    assert e.value.code == 2 and not asked
    assert "https://" in err and ".ts.net" in err and "nothing changed" in err
    assert len([s for s in err.strip().split(". ") if s]) == 1, "one sentence"
    assert record.meta_path.read_bytes() == before


@pytest.mark.parametrize(
    "login", ["", "ines", "ines @example.org", "@example.org", "ines@", "inés@example.org"]
)
def test_setup_phone_refuses_a_login_that_is_not_one(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], login: str
) -> None:
    before = record.meta_path.read_bytes()
    _answer(monkeypatch, "y")
    with pytest.raises(SystemExit) as e:
        cli.main(["setup", "phone", "--origin", ORIGIN, "--login", login])
    assert e.value.code == 2 and "nothing changed" in capsys.readouterr().err
    assert record.meta_path.read_bytes() == before


def test_setup_phone_off_removes_the_key_alone(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = record.meta
    record.set_meta(**{phone.KEY: SETTING})
    _answer(monkeypatch, "y")
    cli.main(["setup", "phone", "--off"])
    assert phone.KEY not in record.meta
    assert record.meta == before
    assert "removed" in capsys.readouterr().out
    cli.main(["setup", "phone", "--off"])
    assert "nothing changed" in capsys.readouterr().out
    assert record.meta == before


def test_setup_phone_alone_says_what_is_set(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = record.meta_path.read_bytes()
    cli.main(["setup", "phone"])
    assert "this machine only" in capsys.readouterr().out
    record.set_meta(**{phone.KEY: SETTING})
    cli.main(["setup", "phone"])
    out = capsys.readouterr().out
    assert ORIGIN in out and LOGIN in out
    with pytest.raises(SystemExit):
        cli.main(["setup", "phone", "--origin", ORIGIN])  # the origin and the login go together
    with pytest.raises(SystemExit):
        cli.main(["setup", "phone", "--off", "--origin", ORIGIN, "--login", LOGIN])
    del before


# -- doctor ------------------------------------------------------------------------------------------------


def test_doctor_says_whether_the_phone_may_write(record: Logbook, tmp_path: Path) -> None:
    """One line: this machine only; or the origin and the login shortened, never whole; a warn when
    the setting names an origin and no `tailscale` is found here; nothing about it when doctor
    cannot tell (no PATH to look on)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = {"PATH": str(bin_dir)}
    check = doctor.phone_check(record, env)
    assert check.name == "phone" and check.status == "pass" and "this machine only" in check.detail
    record.set_meta(**{phone.KEY: SETTING})
    warned = doctor.phone_check(record, env, found=lambda name, path: None)
    assert warned.status == "warn" and ORIGIN in warned.detail and "tailscale" in warned.detail
    assert LOGIN not in warned.detail and "i…@example.org" in warned.detail
    passed = doctor.phone_check(record, env, found=lambda name, path: str(bin_dir / name))
    assert passed.status == "pass" and ORIGIN in passed.detail and "i…@example.org" in passed.detail
    assert LOGIN not in passed.detail
    unknown = doctor.phone_check(record, {}, found=lambda name, path: None)
    assert unknown.status == "pass" and "tailscale" not in unknown.detail
    record.set_meta(**{phone.KEY: {"origin": "http://server.tail1234.ts.net", "login": LOGIN}})
    broken = doctor.phone_check(record, env)
    assert broken.status == "warn" and "logbook setup phone" in broken.detail
    assert LOGIN not in broken.detail
    assert any(c.name == "phone" for c in doctor.run(record, {}))


@pytest.mark.parametrize("login", ["ines nordmann@example.org", "ines@x@example.org", " ines@example.org"])
def test_doctor_never_prints_a_login_written_by_hand_whole(record: Logbook, login: str) -> None:
    """A login that is not the shape is a warn that names the key, never the login it holds."""
    record.set_meta(**{phone.KEY: {"origin": ORIGIN, "login": login}})
    check = doctor.phone_check(record, {})
    assert check.status == "warn"
    assert login.strip() not in check.detail and "nordmann" not in check.detail


@pytest.mark.parametrize("setting", [None, SETTING], ids=["setting-off", "setting-on"])
def test_curl_through_tailscale_over_the_socket_is_refused(
    years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, setting: object
) -> None:
    """The review's write, as tailscaled forwards it: a Star posted with no Origin, the tailnet name
    as Host and the `X-Forwarded-*` tailscaled adds (a login forged or none). A 403 and nothing written,
    the setting on and off; the same form posted as the Air's browser posts it is a 303."""
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    if setting is not None:
        site.lb.set_meta(**{phone.KEY: setting})
    server = serve.Server(0, site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        connection = http.client.HTTPConnection(walk.LOOPBACK, port, timeout=10)
        try:
            connection.request("GET", f"/day/{walk.DAY}")
            reply = connection.getresponse()
            text = reply.read().decode("utf-8")
        finally:
            connection.close()
        star = next(f for f in walk._forms(text, "star"))
        body = urlencode({**star.fields, "act": "star"}).encode("utf-8")
        head = site.lb.meta["head"]
        forwarded = [
            ("X-Forwarded-For", "100.64.0.9"),
            ("X-Forwarded-Proto", "https"),
            ("X-Forwarded-Host", HOST),
        ]
        for curl in (
            [("Host", HOST), *forwarded],
            [("Host", HOST), *forwarded, (phone.LOGIN_HEADER, LOGIN)],
            [("Host", HOST)],
            [("Host", f"{walk.LOOPBACK}:{port}"), *forwarded],
            [("Host", f"{walk.LOOPBACK}:{port}"), ("Tailscale-Funnel-Request", "?1")],
        ):
            status, page = _post(port, star.action, body, curl)
            assert status == 403 and "nothing was written" in page, curl
        assert Logbook(site.lb.root).meta["head"] == head
        here = f"http://{walk.LOOPBACK}:{port}"
        status, _ = _post(port, star.action, body, [("Host", f"{walk.LOOPBACK}:{port}"), ("Origin", here)])
        assert status == 303
        assert Logbook(site.lb.root).meta["head"] != head, "the Air's own browser writes as today"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
