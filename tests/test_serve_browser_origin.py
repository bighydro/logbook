"""The Library's forms as a real browser posts them. A browser that submits a form (any method but
GET and HEAD) names where it came from in an `Origin` header, and what it names follows the page's
`Referrer-Policy` (the Fetch standard, "append a request Origin header"): under `no-referrer` it is
`null`, which the write gate refuses, so every act of the Library was a 403 in Chrome, Firefox and
Safari (the owner's, 18 October 2026, naming a place through an SSH tunnel). Under `same-origin` a
form posted from the server's own page carries the page's origin, `http://127.0.0.1:<port>`, and is
answered; nothing goes to any other site, and the gate is as strict as it was. On the four synthetic
years (`library_record.py`), the orgs record and the ideas record; nobody and nothing here exists."""

from __future__ import annotations

import html
import http.client
import json
import re
import threading
from collections import Counter, deque
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import pytest
import test_library_walk as walk
from library_record import BERGEN_WINTER

from logbook.contrib import serve
from logbook.core import store
from logbook.core.store import Logbook

PORT = 8765  # the port the browser's page is read from
TUNNEL = 8766  # an SSH tunnel's other end: the page is read from this port, the server listens on 8765
SAME_ORIGIN = "same-origin"
LEAKY = (
    "no-referrer",
    "origin",
    "unsafe-url",
)  # never: the first refuses every form, the others tell other sites
REFUSED = ("null", "http://localhost:8765", "https://127.0.0.1:8765", "http://192.0.2.1:8765")
POLICIES = frozenset(
    {
        "no-referrer",
        "no-referrer-when-downgrade",
        "same-origin",
        "origin",
        "strict-origin",
        "origin-when-cross-origin",
        "strict-origin-when-cross-origin",
        "unsafe-url",
    }
)  # the Referrer Policy standard's tokens; anything else in the header is ignored
DEFAULT_POLICY = "strict-origin-when-cross-origin"  # a page whose header names none
OVERRIDES = re.compile(
    r"""<meta\s+name\s*=\s*["']?referrer|\breferrerpolicy\s*=|\brel\s*=\s*["'][^"']*noreferrer""", re.I
)

years = walk.years
manifest = walk.manifest
shelf_of_ideas = walk.shelf_of_ideas
holder = walk.holder


# -- the Origin a browser sends ----------------------------------------------------------------------------


def _serialize(url: str) -> str:
    """A URL's origin as a browser writes it: scheme, host and the port when it is not the scheme's."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    host = f"[{host}]" if ":" in host else host
    port = parts.port
    default = {"http": 80, "https": 443}.get(parts.scheme)
    return f"{parts.scheme}://{host}" + (f":{port}" if port is not None and port != default else "")


def _policy(header: str | None) -> str:
    """The page's referrer policy from its `Referrer-Policy` header: the last token a browser knows
    (the header may list several, a fallback first), else the default."""
    known = [t.strip().lower() for t in (header or "").split(",") if t.strip().lower() in POLICIES]
    return known[-1] if known else DEFAULT_POLICY


def browser_origin(header: str | None, page: str, target: str, method: str = "POST") -> str | None:
    """The `Origin` a browser sends when a form on `page` (whose `Referrer-Policy` header is `header`)
    is submitted to `target`, as the Fetch standard's "append a request Origin header" says for a
    navigation (a form's mode is "navigate", never "cors"): none for GET and HEAD; for any other method
    the page's origin, made `null` by `no-referrer`, by `same-origin` when the target is another
    origin, and by the three downgrade policies when an https page posts to a URL that is not https.
    None: no header sent."""
    if method.upper() in ("GET", "HEAD"):
        return None
    origin = _serialize(page)
    policy = _policy(header)
    if policy == "no-referrer":
        return "null"
    if policy in ("no-referrer-when-downgrade", "strict-origin", "strict-origin-when-cross-origin"):
        if urlsplit(page).scheme == "https" and urlsplit(target).scheme != "https":
            return "null"
    elif policy == SAME_ORIGIN and origin != _serialize(target):
        return "null"
    return origin


@pytest.mark.parametrize(
    ("header", "page", "target", "method", "sent"),
    [
        (
            "no-referrer",
            "http://127.0.0.1:8765/places",
            "http://127.0.0.1:8765/places/review",
            "POST",
            "null",
        ),
        (
            "same-origin",
            "http://127.0.0.1:8765/places",
            "http://127.0.0.1:8765/places/review",
            "POST",
            "http://127.0.0.1:8765",
        ),
        (
            "same-origin",
            "http://127.0.0.1:8766/places",
            "http://127.0.0.1:8766/places/review",
            "POST",
            "http://127.0.0.1:8766",
        ),
        (
            "same-origin",
            "http://127.0.0.1:8765/places",
            "http://127.0.0.1:8766/places/review",
            "POST",
            "null",
        ),
        ("same-origin", "http://[::1]:8765/star", "http://[::1]:8765/star", "POST", "http://[::1]:8765"),
        ("same-origin", "http://127.0.0.1:80/", "http://127.0.0.1/star", "POST", "http://127.0.0.1"),
        ("same-origin", "http://127.0.0.1:8765/days", "http://127.0.0.1:8765/days", "GET", None),
        ("no-referrer", "http://127.0.0.1:8765/days", "http://127.0.0.1:8765/days", "HEAD", None),
        (
            None,
            "http://127.0.0.1:8765/places",
            "http://127.0.0.1:8765/places/review",
            "POST",
            "http://127.0.0.1:8765",
        ),
        ("strict-origin-when-cross-origin", "https://example.org/a", "http://example.org/b", "POST", "null"),
        ("unsafe-url", "https://example.org/a", "http://example.org/b", "POST", "https://example.org"),
        (
            "no-referrer, same-origin",
            "http://127.0.0.1:8765/",
            "http://127.0.0.1:8765/star",
            "POST",
            "http://127.0.0.1:8765",
        ),
        (
            "same-origin, no-such-policy",
            "http://127.0.0.1:8765/",
            "http://127.0.0.1:8766/star",
            "POST",
            "null",
        ),
    ],
)
def test_the_origin_a_browser_sends_follows_the_fetch_standard(
    header: str | None, page: str, target: str, method: str, sent: str | None
) -> None:
    assert browser_origin(header, page, target, method) == sent


# -- every page and every error -----------------------------------------------------------------------------


def _walk(site: serve.Site, seeds: list[str]) -> dict[str, serve.Response]:
    """Every page the Library serves from `seeds` on, through every link, up to `walk.EACH` of a kind
    (as `test_library_walk` walks it): the response by its target."""
    queue, seen, kinds = deque(seeds), set(seeds), Counter(walk._sort(seed) for seed in seeds)
    read: dict[str, serve.Response] = {}
    while queue:
        target = queue.popleft()
        path, _, query = target.partition("?")
        response = site.respond(path, query)
        read[target] = response
        text = response.body.decode("utf-8")
        links = (
            [response.location] if response.location else [html.unescape(t) for t in walk.HREF.findall(text)]
        )
        for link in links:
            link = link.partition("#")[0]
            if (
                not link.startswith("/")
                or link.startswith("//")
                or link in seen
                or kinds[walk._sort(link)] >= walk.EACH
            ):
                continue
            kinds[walk._sort(link)] += 1
            seen.add(link)
            queue.append(link)
    return read


def test_every_page_and_every_error_names_its_origin_to_itself_only(
    years: Path,
    manifest: Path,
    shelf_of_ideas: Path,
    holder: dict[str, object],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every page the Library serves (walked from `/` on the four years, the Manifest and the Ideas),
    a photo, a 304, the redirects, and every error a GET or a POST can answer (400, 403, 404, 405,
    409): `Referrer-Policy: same-origin`, never `no-referrer` (every form refused), `origin` or
    `unsafe-url` (the page's address told to other sites); and no page overrides it with a meta tag,
    a form's or a link's `rel=noreferrer` or a `referrerpolicy` attribute."""
    mine = walk._copy(years, tmp_path / "years", monkeypatch)
    theirs = walk._copy(manifest, tmp_path / "orgs", monkeypatch)
    hers = walk._copy(shelf_of_ideas, tmp_path / "ideas", monkeypatch)
    site = walk._years_site(mine)
    read: dict[str, serve.Response] = {}
    for one, seeds in (
        (
            site,
            [
                "/",
                f"/day/{walk.DAY}",
                f"/day/{walk.PHOTO_DAY}",
                "/places",
                "/nowhere",
                "/days?from=2026-13-01",
            ],
        ),
        (walk._manifest_site(theirs), ["/", "/manifest"]),
        (walk._ideas_site(hers), ["/", "/ideas"]),
    ):
        for target, response in _walk(one, seeds).items():
            read[f"{id(one)} {target}"] = response
    page = site.respond(f"/day/{walk.DAY}", "")
    assert page.etag is not None
    read["304"] = site.respond(f"/day/{walk.DAY}", "", page.etag)
    read["/today"] = site.respond(serve.TODAY, "")
    read["/favicon.ico"] = site.respond("/favicon.ico", "")
    (keep, _) = walk._forms(site.respond(f"/day/{walk.PHOTO_DAY}", "").body.decode("utf-8"), "keep")
    read["/photo"] = site.respond(f"/photo/{keep.fields['line']}", "")  # its pixels, or why there are none
    for path in (*serve.WRITE_PATHS, *serve.LINE_ACTS, f"/day/{walk.DAY}/sign"):
        read[f"GET {path}"] = site.respond(path, "")
    read["POST /nowhere"] = site.write("/nowhere", {}, walk.LOOPBACK, f"http://{walk.LOOPBACK}:{PORT}")
    read["POST refused"] = site.write(serve.STAR_PATH, {}, walk.LOOPBACK, "null")
    lock = mine.root.joinpath(*store.LOCK_FILE.parts)
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(json.dumps(holder), encoding="utf-8")
    read["POST busy"] = site.write(
        serve.WITH_PATH,
        {"day": walk.DAY, "names": "Ola Nordmann"},
        walk.LOOPBACK,
        f"http://{walk.LOOPBACK}:{PORT}",
    )
    lock.unlink()
    assert {r.status for r in read.values()} >= {200, 204, 302, 304, 400, 403, 404, 405, 409}
    for target, response in read.items():
        said = response.headers["Referrer-Policy"]
        assert said == SAME_ORIGIN and said not in LEAKY, (target, response.status, said)
        if response.content_type == serve.HTML:
            assert OVERRIDES.search(response.body.decode("utf-8")) is None, target


# -- every act, posted as a browser posts it --------------------------------------------------------------


def _page_of(act: walk.Act) -> str:
    """The page whose form posts the act: the Places page, the journey's, the People queue's year,
    the Manifest's and Ideas' own `back`, the Day or the week the act is on."""
    if (day := serve.DAY_ACT.match(act.path)) is not None:
        return f"/day/{day.group(1)}"
    if (week := serve.WEEK_ACT.match(act.path)) is not None:
        return f"/week/{week.group(1)}"
    if act.path in serve.LINE_ACTS:
        return f"/day/{act.form['day']}"
    if act.path == serve.REVIEW_PATH:
        return f"/places?page={act.form['page']}"
    if act.path == serve.NAME_PATH:
        _, first, last = BERGEN_WINTER.split(":")
        return f"/journeys/{first}/{last}"
    if act.path == serve.PEOPLE_REVIEW_PATH:
        return f"/people?year={act.form['year']}"
    return act.form["back"]


KEYS = ("id", "line", "org", "idea", "day")  # the fields that say which thing a form acts on


def _acts(
    root: Path, years: Path, manifest: Path, shelf_of_ideas: Path, mp: pytest.MonkeyPatch
) -> list[walk.Act]:
    return walk._acts(
        walk._copy(years, root / "years", mp),
        walk._copy(manifest, root / "orgs", mp),
        walk._copy(shelf_of_ideas, root / "ideas", mp),
    )


UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _answer(response: serve.Response) -> tuple[int, str | None]:
    """The status and where it sends the browser, a line's id (drawn anew in each copy) as `ID`."""
    return response.status, None if response.location is None else UUID.sub("ID", response.location)


@pytest.mark.parametrize("port", [PORT, TUNNEL], ids=["the-server-s-port", "a-tunnel-s-other-port"])
def test_every_act_posted_from_its_own_page_is_answered_as_it_is_today(
    years: Path,
    manifest: Path,
    shelf_of_ideas: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    port: int,
) -> None:
    """Every act of the Library's walk (#315: Name this place and its reject, a journey's name, the
    People queue, the Manifest's queue and an org's status, the Ideas' queue and an idea's status,
    Sign, Reflect in words and by a recording, Star, Unstar, With, the photo review's Star and Not a
    keeper), posted with the Origin a browser derives from the page that carries its form (that
    page's own `Referrer-Policy`, read from the server, the page read from `port`), is answered as
    the act is answered today with an Origin passed by hand: a 303 to the same place (or the page
    the act answers with), never a 403. Through a tunnel the page is read from another port of
    127.0.0.1, and that is still this machine (`_loopback_origin`)."""
    today = [
        _answer(a.site.write(a.path, a.form, walk.LOOPBACK, f"http://{walk.LOOPBACK}:{PORT}", a.upload))
        for a in _acts(tmp_path / "today", years, manifest, shelf_of_ideas, monkeypatch)
    ]
    acts = _acts(tmp_path / "browser", years, manifest, shelf_of_ideas, monkeypatch)
    origins: list[str | None] = []
    for act in acts:  # every page read first, as the owner has it open, then each form sent
        page = _page_of(act)
        response = act.site.respond(*page.partition("?")[::2])
        assert response.status == 200, (walk._kind(act), page, response.status)
        text = response.body.decode("utf-8")
        assert OVERRIDES.search(text) is None, page
        forms = [
            f
            for f in walk._forms(text)
            if f.action == act.path and all(f.fields[k] == act.form.get(k) for k in KEYS if k in f.fields)
        ]
        assert forms, (walk._kind(act), page, "the page carries the act's form")
        at = f"http://{walk.LOOPBACK}:{port}"
        origins.append(browser_origin(response.headers["Referrer-Policy"], at + page, at + act.path))
    assert set(origins) == {f"http://{walk.LOOPBACK}:{port}"}
    found = [
        _answer(a.site.write(a.path, a.form, walk.LOOPBACK, origin, a.upload))
        for a, origin in zip(acts, origins, strict=True)
    ]
    assert all(status != 403 for status, _ in found), found
    assert {status for status, _ in today} <= {303, 409} and today.count((303, None)) == 0, today
    assert found == today, [
        (walk._kind(a), f, t) for a, f, t in zip(acts, found, today, strict=True) if f != t
    ]


def test_under_the_old_policy_every_act_was_refused(
    years: Path, manifest: Path, shelf_of_ideas: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's 403, as it was: a page sent with `no-referrer` makes every form's Origin `null`,
    and the gate refuses every act with it, nothing written."""
    acts = _acts(tmp_path, years, manifest, shelf_of_ideas, monkeypatch)
    at = f"http://{walk.LOOPBACK}:{PORT}"
    origin = browser_origin("no-referrer", at + "/places", at + serve.REVIEW_PATH)
    assert origin == "null"
    roots = {a.site.lb.root for a in acts}
    before = {root: walk._files(root) for root in roots}
    for act in acts:
        response = act.site.write(act.path, act.form, walk.LOOPBACK, origin, act.upload)
        assert response.status == 403 and "nothing was written" in response.body.decode("utf-8"), walk._kind(
            act
        )
    assert {root: walk._files(root) for root in roots} == before


@pytest.mark.parametrize("origin", REFUSED)
def test_another_origin_is_still_refused_and_nothing_is_written(
    years: Path,
    manifest: Path,
    shelf_of_ideas: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    origin: str,
) -> None:
    """The gate is as strict as it was: an opaque origin (`null`), a name (`localhost`, which may
    resolve to anything), another scheme (`https`) and another host are refused on every act, a 403
    that says nothing was written, and not a byte of any record changes."""
    acts = _acts(tmp_path, years, manifest, shelf_of_ideas, monkeypatch)
    roots = {a.site.lb.root for a in acts}
    before = {root: (walk._files(root), Logbook(root).meta["head"]) for root in roots}
    for act in acts:
        response = act.site.write(act.path, act.form, walk.LOOPBACK, origin, act.upload)
        page = html.unescape(response.body.decode("utf-8"))
        assert response.status == 403, (walk._kind(act), response.status)
        assert f"origin {origin!r}" in page and "nothing was written" in page, walk._kind(act)
    assert {root: (walk._files(root), Logbook(root).meta["head"]) for root in roots} == before


def test_a_tunnel_s_other_port_is_this_machine() -> None:
    """Through `ssh -L 8766:127.0.0.1:8765` the browser reads the page from 127.0.0.1:8766 and names
    that origin; it is this machine, any port, as `_loopback_origin` says. The refused ones are not."""
    assert serve._loopback_origin(f"http://127.0.0.1:{TUNNEL}")
    assert serve._loopback_origin(f"http://[::1]:{TUNNEL}")
    assert not any(serve._loopback_origin(origin) for origin in REFUSED)


# -- over the socket, as the browser has it ----------------------------------------------------------------


@pytest.fixture
def served(years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[serve.Site, int]]:
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    server = serve.Server(0, site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield site, server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_star_posted_over_the_socket_with_the_origin_the_page_s_header_gives(
    served: tuple[serve.Site, int],
) -> None:
    """The Day page read over the socket, its `Referrer-Policy` read from the wire, and a row's Star
    form posted back with the Origin a browser derives from it: a 303 and the line written; the same
    form with the Origin the old header gave (`null`) is a 403 and nothing more is written."""
    site, port = served
    at = f"http://{walk.LOOPBACK}:{port}"
    connection = http.client.HTTPConnection(walk.LOOPBACK, port, timeout=10)
    try:
        connection.request("GET", f"/day/{walk.DAY}")
        reply = connection.getresponse()
        text = reply.read().decode("utf-8")
        header = reply.getheader("Referrer-Policy")
        assert reply.status == 200 and header == SAME_ORIGIN
        star = next(f for f in walk._forms(text, "star"))
        form = {**star.fields, "act": "star"}
        origin = browser_origin(header, f"{at}/day/{walk.DAY}", at + star.action)
        assert origin == at
        head = site.lb.meta["head"]
        body = urlencode(form).encode("utf-8")
        kind = {"Content-Type": "application/x-www-form-urlencoded"}
        connection.request("POST", star.action, body, {**kind, "Origin": origin})
        reply = connection.getresponse()
        reply.read()
        assert reply.status == 303 and reply.getheader("Referrer-Policy") == SAME_ORIGIN
        moved = Logbook(site.lb.root).meta["head"]
        assert moved != head, "the star is written"
        connection.request("POST", star.action, body, {**kind, "Origin": "null"})
        reply = connection.getresponse()
        assert reply.status == 403 and "nothing was written" in reply.read().decode("utf-8")
        assert reply.getheader("Referrer-Policy") == SAME_ORIGIN
        assert Logbook(site.lb.root).meta["head"] == moved
    finally:
        connection.close()
