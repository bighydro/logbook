"""Every Library address from before the doors leads to its door (RFC 0047 §9): a page that moved
answers with a redirect (`doors.REDIRECT_STATUS`, 302 for 1.1 and 301 from 1.2, §15) to its new home,
carrying the moment it named, the query translated; an address that stays answers as it did, and a
POST is never redirected. The table is `doors.MOVED`, §9's rows in order; the server reads it after the
read gate (`Site.gate`), so a request the gate refuses is refused as the new home would refuse it, and
the Location is built from the table and the values it parsed alone. On the Oslo persona's fortnight
(`persona.py`), who does not exist; the tailnet name and the logins are invented."""

from __future__ import annotations

import http.client
import inspect
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from test_serve_hosts import FORWARDED, HOST, LOGIN, LOOPBACK, WEDNESDAY, Served

from logbook.contrib import door_gear, door_life, doors, phone, serve

DOCS = Path(__file__).resolve().parent.parent / "docs" / "serve.md"

# every §9 row that moves, as asked, and where it leads: (old address, Location)
MOVES = {
    "days, a window": ("/days?from=2026-06-08&to=2026-06-14", "/life?from=2026-06-08&to=2026-06-14&zoom=day"),
    "days, from alone": ("/days?from=2026-06-08", "/life?from=2026-06-08&zoom=day"),
    "days, to alone": ("/days?to=2026-06-21", "/life?to=2026-06-21&zoom=day"),
    "days, the last fortnight": ("/days", "/life?zoom=day"),
    "days, empty values": ("/days?from=&to=", "/life?zoom=day"),
    "days, a whole year, as Life's Volumes link it": (
        "/days?from=2025-01-01&to=2025-12-31",
        "/life?year=2025&zoom=year",
    ),
    "trips of a year": ("/trips?year=2026", "/life?year=2026&zoom=year"),
    "trips": ("/trips", "/life?zoom=year"),
    "journeys of a year": ("/journeys?year=2026", "/life?year=2026&zoom=year"),
    "journeys": ("/journeys", "/life?zoom=year"),
    "goals": ("/goals", "/life"),
    "world, a window in one year": ("/world?from=2026-06-08&to=2026-06-21", "/places?at=2026"),
    "world, from alone": ("/world?from=2025-03-01", "/places?at=2025"),
    "world, a window over two years, the year it opens": (
        "/world?from=2025-12-20&to=2026-01-05",
        "/places?at=2025",
    ),
    "world, to alone": ("/world?to=2026-01-05", "/places?at=2026"),
    "world": ("/world", "/places"),
    "a parameter the home does not take": (
        "/days?from=2026-06-08&shape=x&open=1",
        "/life?from=2026-06-08&zoom=day",
    ),
    "search, the words": ("/search?q=Kari", "/ask?q=Kari"),
    "search, what Ask does not take": (
        "/search?q=Kari+Nordmann&kind=note&year=2026&page=2",
        "/ask?q=Kari+Nordmann",
    ),
    "search, a line break typed": ("/search?q=a%0d%0aSet-Cookie:%20b=c", "/ask?q=a%0D%0ASet-Cookie%3A+b%3Dc"),
    "search": ("/search", "/ask"),
    "assets": ("/assets", "/gear/assets"),
    "manifest": ("/manifest", "/gear/manifest"),
    "manifest, a page and a portfolio": (
        "/manifest?page=1&portfolio=Fund+I",
        "/gear/manifest?page=1&portfolio=Fund+I",
    ),
    "manifest, people": ("/manifest/people", "/gear/manifest/people"),
    "an org": ("/org/0a1b", "/gear/org/0a1b"),
    "an org, its money asked": ("/org/0a1b?money=1", "/gear/org/0a1b?money=1"),
    "an org, its money not asked": ("/org/0a1b?money=0", "/gear/org/0a1b"),
    "an org, its id escaped": ("/org/kari%20nordmann%2Fx", "/gear/org/kari%20nordmann%2Fx"),
    "agents": ("/agents", "/gear/agents"),
    "agents, a page and a day": ("/agents?page=2&day=2026-06-17", "/gear/agents?page=2&day=2026-06-17"),
    "a parameter given twice, the last": ("/trips?year=2025&year=2026", "/life?year=2026&zoom=year"),
}
# what answers as on main: the rows that stay, and the rows whose home is not built yet
STAYS = (
    "/",
    "/today",
    f"/day/{WEDNESDAY}",
    "/people",
    "/places",
    "/goals/nobody",
    "/gaps",  # the gear keeps it a link away
    "/journeys/2026-06-12/2026-06-14",  # waits: Life has no journey's name form yet
    "/journeys/2026-02-30/2026-03-01",
    "/ideas",
    "/promises",
)
# a value the new home would refuse: no redirect, a 404, nothing of the value said back
INVALID = (
    "/agents?page=0",
    "/agents?page=x",
    "/manifest?page=-1",
    "/agents?day=17%20June",
    "/org/..",  # a dot segment: no org, and no path the browser would rewrite
    "/org/.",
    "/days?from=2026-13-01",
    "/days?from=2026-06-08&to=2026-06-01",  # backwards
    "/days?from=2026-01-01&to=2026-06-30",  # longer than Life's window of days
    "/days?from=8%20June",
    "/days?to=2026-06-08%0d%0aSet-Cookie:%20a=b",
    "/trips?year=20x6",
    "/journeys?year=26",
    "/days?from=2026-01-01&to=2026-12-30",  # longer than Life's window, and not a whole year
    "/days?from=2026-01-02&to=2027-01-01",
    "/trips?year=%D9%A2%D9%A0%D9%A2%D9%A6",  # a year in digits that are not 0 to 9
    "/days?from=%D9%A2%D9%A0%D9%A2%D9%A6-06-08",
    "/world?from=junk",
    "/world?from=2026-06-21&to=2026-06-08",
)
POSTS = ("/days", "/trips", "/journeys", "/goals", "/world", "/journeys/2026-06-12/2026-06-14")
POSTS += ("/journeys/name",)  # a row that stays: Life's form


@pytest.fixture(scope="module", params=[False, True], ids=["live", "built"])
def served(request: pytest.FixtureRequest, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Served]:
    from persona import persona_record

    with pytest.MonkeyPatch.context() as mp:
        lb = persona_record(tmp_path_factory.mktemp("old-addresses"), mp)
        lb.set_meta(**{phone.KEY: {"origin": f"https://{HOST}", "login": LOGIN}})
        s = Served(lb, built=request.param)
        try:
            yield s
        finally:
            s.close()


def _here(served: Served) -> list[tuple[str, str]]:
    return [("Host", f"{LOOPBACK}:{served.port}")]


def _phone() -> list[tuple[str, str]]:
    return [("Host", HOST), *FORWARDED, (phone.LOGIN_HEADER, LOGIN)]


def _post(served: Served, path: str) -> http.client.HTTPResponse:
    connection = http.client.HTTPConnection(LOOPBACK, served.port, timeout=30)
    try:
        connection.putrequest("POST", path, skip_host=True, skip_accept_encoding=True)
        for name, value in [
            *_here(served),
            ("Content-Type", "application/x-www-form-urlencoded"),
            ("Content-Length", "0"),
        ]:
            connection.putheader(name, value)
        connection.endheaders(b"")
        reply = connection.getresponse()
        reply.read()
        return reply
    finally:
        connection.close()


# -- the rows that move -------------------------------------------------------------------------------------


@pytest.mark.parametrize(("old", "location"), MOVES.values(), ids=MOVES.keys())
@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_an_old_address_leads_to_its_door_with_its_moment(
    served: Served, old: str, location: str, method: str
) -> None:
    reply = served.get(old, _here(served), method)
    assert reply.status == doors.REDIRECT_STATUS, (old, reply.status)
    assert reply.getheader("Location") == location, old
    assert reply.getheader("X-Frame-Options") == "DENY"
    assert reply.getheader("Cache-Control") == "no-store", "a redirect of 1.1 is not kept"


@pytest.mark.parametrize(("old", "location"), MOVES.values(), ids=MOVES.keys())
def test_the_new_home_answers_the_moment_it_was_given(served: Served, old: str, location: str) -> None:
    """The new home answers with a page, or with the 404 the old page gave (an org nobody named)."""
    reply = served.get(location, _here(served))
    path, _, query = old.partition("?")
    was = served.site.respond(path, query).status
    assert reply.status == 200 or reply.status == was == 404, (old, location, reply.status, was)


def test_every_row_that_moves_answers_with_the_one_status() -> None:
    """The 301 switch of 1.2 is one line: `REDIRECT_STATUS`, which every row answers with."""
    assert doors.REDIRECT_STATUS == 302, "RFC 0047 §15: 302 for one release, 1.1; 301 from 1.2"
    site = serve.Site.__new__(serve.Site)  # `moved` reads nothing of the record
    for row in doors.MOVED:
        if row.home is None or row.post or row.waits:
            continue
        example = _example(row.old)
        response = site.moved(example, "")
        assert response is not None and response.status == doors.REDIRECT_STATUS, row.old


def test_the_location_is_the_table_s_and_never_the_host_s(served: Served) -> None:
    for old, location in MOVES.values():
        for host in (f"{LOOPBACK}:{served.port}", f"localhost:{served.port}"):
            reply = served.get(old, [("Host", host)])
            found = reply.getheader("Location") or ""
            split = urlsplit(found)
            assert found == location and not split.scheme and not split.netloc, (old, host, found)
            assert found.startswith("/") and not found.startswith("//")


# -- the gate -----------------------------------------------------------------------------------------------


def test_the_phone_is_led_where_this_machine_is(served: Served) -> None:
    for old, location in MOVES.values():
        reply = served.get(old, _phone())
        assert (reply.status, reply.getheader("Location")) == (doors.REDIRECT_STATUS, location), old


@pytest.mark.parametrize(("old", "location"), MOVES.values(), ids=MOVES.keys())
def test_a_request_the_gate_refuses_is_refused_as_the_new_home_would_be(
    served: Served, old: str, location: str
) -> None:
    """No redirect says a page exists behind the gate: the old address and its new home are answered
    alike, with nothing read and no Location."""
    port = served.port
    for headers in (
        [("Host", f"rebind.example:{port}")],
        [("Host", f"0.0.0.0:{port}")],
        [("Host", HOST), *FORWARDED],
        [("Host", HOST), *FORWARDED, (phone.LOGIN_HEADER, "ola@example.org")],
        [*_phone(), ("Tailscale-Funnel-Request", "?1")],
    ):
        served.reads.clear()
        reply = served.get(old, headers)
        home = served.get(location, headers)
        assert reply.status == home.status and reply.status in (403, 421), (old, headers, reply.status)
        assert reply.getheader("Location") is None, (old, headers)
        assert served.reads == [], (old, headers, served.reads)


def test_without_the_phone_s_setting_the_phone_is_refused_at_an_old_address(served: Served) -> None:
    served.site.lb.set_meta(**{phone.KEY: None})
    try:
        for old, location in MOVES.values():
            reply = served.get(old, _phone())
            assert reply.status == served.get(location, _phone()).status == 403, old
            assert reply.getheader("Location") is None
    finally:
        served.site.lb.set_meta(**{phone.KEY: {"origin": f"https://{HOST}", "login": LOGIN}})


# -- what does not move -------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", STAYS)
def test_an_address_that_stays_answers_as_on_main(served: Served, path: str) -> None:
    reply = served.get(path, _here(served))
    assert reply.status != doors.REDIRECT_STATUS or path == "/today", (path, reply.status)
    assert served.site.moved(path, "") is None, path
    expected = served.site.respond(path, "")
    assert reply.status == expected.status, (path, reply.status, expected.status)
    assert reply.getheader("Location") == expected.location, path


@pytest.mark.parametrize("path", POSTS)
def test_a_post_to_an_old_address_is_never_redirected(served: Served, path: str) -> None:
    reply = _post(served, path)
    assert reply.status not in (301, 302, 303, 307, 308), (path, reply.status)
    assert reply.getheader("Location") is None, path
    expected = served.site.write(path, {}, LOOPBACK, None)
    assert reply.status == expected.status, (path, reply.status, expected.status)


@pytest.mark.parametrize("old", INVALID)
def test_a_value_the_new_home_would_refuse_is_a_404_and_no_redirect(served: Served, old: str) -> None:
    connection = http.client.HTTPConnection(LOOPBACK, served.port, timeout=30)
    try:
        connection.putrequest("GET", old, skip_host=True, skip_accept_encoding=True)
        connection.putheader("Host", f"{LOOPBACK}:{served.port}")
        connection.endheaders()
        reply = connection.getresponse()
        text = reply.read().decode("utf-8")
    finally:
        connection.close()
    assert reply.status == 404, (old, reply.status)
    assert reply.getheader("Location") is None and reply.getheader("Set-Cookie") is None, old
    for value in ("Set-Cookie", "junk", "20x6", "8 June"):
        assert value not in text, (old, value)


DOOR_PAGES = ("/", "/life", "/life?zoom=life", "/life?trip=2026-06-12/2026-06-14", "/people", "/places")
DOOR_PAGES += (
    "/gear",
    "/gear/sources",
    "/gear/agents",
    "/gear/manifest",
    "/gear/manifest/people",
    "/gear/assets",
)


@pytest.mark.parametrize("page", (*DOOR_PAGES, f"/day/{WEDNESDAY}"))
def test_no_link_on_a_door_leads_through_the_table_to_a_404_or_back_to_itself(
    served: Served, page: str
) -> None:
    """The doors link old addresses (Life's Volumes link a year of `/days`): each still opens a page."""
    path, _, query = page.partition("?")
    text = served.site.respond(path, query).body.decode("utf-8")
    for href in sorted(set(re.findall(r'href="(/[^"#]*)', text))):
        target = href.replace("&amp;", "&")
        old, _, asked = target.partition("?")
        found = served.site.moved(old, asked)
        if found is None:
            continue
        assert found.status == doors.REDIRECT_STATUS, (page, target, found.status)
        assert found.location != page, (page, target, "a link back to the page it is on")
        assert served.get(str(found.location), _here(served)).status == 200, (page, target, found.location)


def test_a_path_no_row_names_is_answered_as_on_main(served: Served) -> None:
    for path in ("/journeys/name/again", "/journeys/2026-06-12", "/days/2026-06-12", "/life/days"):
        assert served.site.moved(path, "") is None, path
        assert served.get(path, _here(served)).status == served.site.respond(path, "").status == 404, path


# -- the table, the server and the docs in agreement --------------------------------------------------------


def _example(old: str) -> str:
    """An address of the row's shape: its days the persona's, its id one."""
    return (
        old.replace("{DAY}", WEDNESDAY)
        .replace("{FIRST}", "2026-06-12")
        .replace("{LAST}", "2026-06-14")
        .replace("{ID}", "0a1b")  # an id every id route takes, a promise's hex too
    )


def _routes() -> list[re.Pattern[str]]:
    """Every address the server answers, read from its dispatch (`Site._page`, `Site.respond`) and its
    forms (`WRITE_PATHS`, `LINE_ACTS`, `DAY_ACT`, `WEEK_ACT`)."""
    found: list[re.Pattern[str]] = []
    source = inspect.getsource(serve.Site._page) + inspect.getsource(serve.Site.respond)
    for literal in re.findall(r'path == "([^"]+)"', source):
        found.append(re.compile(re.escape(literal)))
    for name in re.findall(r"\b([A-Z_]+)\.match\(path\)", source):
        found.append(getattr(serve, name))
    for name in re.findall(r"path == ([A-Z_]+)\b", source):
        found.append(re.compile(re.escape(getattr(serve, name))))
    found.extend(re.compile(re.escape(p)) for p in (*serve.WRITE_PATHS, *serve.LINE_ACTS))
    found.extend((serve.DAY_ACT, serve.WEEK_ACT))
    # the gear's addresses, which `_page` hands to `door_gear.page` by their prefix
    gear = (door_gear.GEAR, door_gear.SOURCES, door_gear.CROSSINGS, door_gear.BUILD, *door_gear.OLD)
    found.extend(re.compile(re.escape(p)) for p in gear)
    found.append(re.compile(door_gear.ORG_PATH.pattern.removeprefix("^").removesuffix("$")))
    return found


# the addresses the server answers that §9's table does not list: the doors' own, the pages §9 gives a
# home in its prose (the week, the timeline, search), the shelves listed and what reads nothing
AFTER_THE_TABLE = (
    "/life",
    "/places/0a1b",
    "/shelves",
    "/timeline",
    "/timeline/life",
    "/week/2026-W25",
    "/week/2026-W25/close",
    "/ask",
    "/gear",
    "/gear/sources",
    "/gear/crossings",
    "/gear/build",
    "/gear/agents",
    "/gear/manifest",
    "/gear/manifest/people",
    "/gear/assets",
    "/gear/org/0a1b",
)


def test_every_row_has_a_route_and_every_home_is_one() -> None:
    routes = _routes()
    answered = lambda path: any(r.fullmatch(path) for r in routes)  # noqa: E731
    for row in doors.MOVED:
        assert answered(_example(row.old)), f"{row.old}: a row without a route"
        if row.home is not None and not row.waits:
            assert answered(row.home), f"{row.old} leads to {row.home}, which the server does not answer"


def test_every_route_has_a_row() -> None:
    rows = [doors.pattern(row.old) for row in doors.MOVED]
    examples = [_example(row.old) for row in doors.MOVED] + list(AFTER_THE_TABLE)
    for route in _routes():
        shown = [e for e in examples if route.fullmatch(e)]
        assert shown, f"{route.pattern}: a route the table does not list"
    for path in examples:
        if path in AFTER_THE_TABLE:
            continue
        assert any(r.fullmatch(path) for r in rows), path


def test_the_table_is_section_9_s_rows_in_order() -> None:
    assert [row.old for row in doors.MOVED] == [
        "/", "/today", "/day/{DAY}", "/day/{DAY}/reflect", "/day/{DAY}/sign", "/star", "/with",
        "/days", "/trips", "/journeys", "/journeys/{FIRST}/{LAST}", "/journeys/name", "/goals",
        "/goals/{ID}", "/ideas", "/idea/{ID}", "/ideas/review", "/ideas/status", "/gaps", "/promises",
        "/promises/{ID}", "/people", "/people/{ID}", "/people/review", "/places", "/places/review",
        "/world", "/assets", "/manifest", "/manifest/people", "/org/{ID}", "/manifest/review",
        "/manifest/status", "/agents", "/line/{ID}", "/photo/{ID}",
        "/search",  # §9's prose: search in the Library is Ask v1
    ]  # fmt: skip


def test_the_windows_are_life_s() -> None:
    """A redirect refuses what Life refuses: its window of days and a trip at most as long as Life's."""
    most = {row.old: row.most for row in doors.MOVED if row.most is not None}
    assert most == {"/days": door_life.DAY_MOST, "/journeys/{FIRST}/{LAST}": door_life.TRIP_MOST}


def test_the_docs_name_every_old_address_and_point_at_the_rfc() -> None:
    text = DOCS.read_text(encoding="utf-8")
    assert "RFC 0047 §9" in text
    for row in doors.MOVED:
        assert f"`{row.old.replace('{', '').replace('}', '')}`" in text, row.old
        if row.home is not None:
            assert f"`{row.home.replace('{', '').replace('}', '')}" in text, row.home


# -- the build ----------------------------------------------------------------------------------------------


def test_an_act_drops_the_built_page_its_old_address_leads_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A form on an old page in the gear returns to the old address (`back=/org/ID`), which leads to
    `/gear/org/ID`: under the build, the act drops that page too, so the owner sees what was written."""
    import orgs_record

    from logbook.contrib import library_build, orgs

    lb = orgs_record.settled_record(tmp_path, monkeypatch)
    now = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
    org = sorted(orgs.read(lb, orgs.gate(None, False)).orgs)[0]
    home = f"/gear/org/{org}"
    library = library_build.Library(lb, now=lambda: now)
    library_build.build(lb, serve.Site(lb, now=lambda: now), library, only=[home, "/gear/manifest"])
    assert home in library.pages()
    site = serve.Site(lb, now=lambda: now, library=library)
    form = {
        "act": "status",
        "org": org,
        "back": f"/org/{org}",
        "status": "hold",
        "reason": "Still building boats",
        "at": "",
    }
    answered = site.write(serve.MANIFEST_STATUS, form, LOOPBACK, None)
    assert answered.status == 303 and answered.location == f"/org/{org}", answered.body.decode("utf-8")[-400:]
    assert home not in library.pages(), "the page the 303 leads to, through the table, is dropped"
    assert "/gear/manifest" in library.pages(), "the rest is the rebuild's"


def test_the_org_s_page_through_the_table_is_its_page_in_the_gear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A real org, not a 404: `/org/ID` and `?money=1` lead to the gear's page of the same org, which
    renders it."""
    import orgs_record

    from logbook.contrib import orgs

    lb = orgs_record.settled_record(tmp_path, monkeypatch)
    site = serve.Site(lb, now=lambda: datetime(2026, 10, 12, 20, 0, tzinfo=UTC))
    org = sorted(orgs.read(lb, orgs.gate(None, False)).orgs)[0]
    for query, home in (("", f"/gear/org/{org}"), ("money=1", f"/gear/org/{org}?money=1")):
        found = site.moved(f"/org/{org}", query)
        assert found is not None and found.location == home, (query, found)
        path, _, asked = home.partition("?")
        assert site.respond(path, asked).status == 200, home
