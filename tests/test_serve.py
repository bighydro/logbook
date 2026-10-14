"""`logbook serve [--port N]`: the record read in a browser, from this machine only. Server-rendered
HTML with one inline stylesheet, every page from the index and the readers (`day`, `days`, `trips`,
`places`, `assets status`, `sources --gaps`); nothing is written and nothing leaves the machine:
the server binds 127.0.0.1 and refuses any other host, and no page references a URL outside
itself. Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import html
import http.client
import json
import re
import threading
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import note, persona_record, utc

from logbook import cli
from logbook.contrib import serve
from logbook.core import index
from logbook.core.store import Logbook

PAGES = (
    "/",
    "/day/2026-06-10",
    "/day/2026-06-13",
    "/day/2026-06-15",
    "/days",
    "/days?from=2026-06-08&to=2026-06-21",
    "/trips",
    "/trips?year=2026",
    "/places",
    "/places?page=2",
    "/assets",
    "/gaps",
)
REFERENCE = re.compile(
    r"""(?:href|src|action|formaction|poster|data|srcset|cite)\s*=\s*["']([^"']*)["']""", re.I
)


def _open(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Logbook, serve.Site]:
    lb = persona_record(tmp_path, monkeypatch)
    return lb, serve.Site(lb)


def _files(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


# -- the two promises ---------------------------------------------------------------------------------------


def test_refuses_to_bind_anything_but_loopback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The server listens on this machine only: 0.0.0.0, the empty host, ::, a LAN address and a
    name that may resolve to anything are refused before any socket is opened."""
    lb, _site = _open(tmp_path, monkeypatch)
    for host in (
        "0.0.0.0",
        "",
        "::",
        "0:0:0:0:0:0:0:0",
        "192.168.1.20",
        "10.0.0.5",
        "localhost",
        "example.org",
    ):
        with pytest.raises(serve.HostError, match=r"127\.0\.0\.1"):
            serve.make_server(lb, host=host, port=0)
    with pytest.raises(SystemExit) as e:
        cli.main(["serve", "--host", "0.0.0.0", "--port", "0"])
    assert e.value.code == 2
    assert "127.0.0.1" in capsys.readouterr().err
    server = serve.make_server(lb, port=0)
    try:
        assert server.server_address[0] == "127.0.0.1"
        assert server.server_address[1] > 0
    finally:
        server.server_close()


def test_no_page_references_a_url_outside_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every link, form and image on every page points inside the server: a path from `/`, never
    a scheme, a host or a protocol-relative `//`. No script fetched (the Places page carries one
    inline, for its keys, and a Day one, for its record button, when the server can hear a
    recording; each named by its hash in that page's policy and by nothing else; every other page
    has none and a policy that allows none), no stylesheet link, no frame, no `url()` or `@import`
    in the inline style, and a Content-Security-Policy that would stop a browser following any of
    those even if one slipped in."""
    lb, site = _open(tmp_path, monkeypatch)
    voiced = serve.Site(lb, voice=serve.Voice(lambda path: None))  # type: ignore[arg-type, return-value]
    days = [page for page in PAGES if page.startswith("/day/")]
    for page, server in [*((page, site) for page in PAGES), *((page, voiced) for page in days)]:
        path, _, query = page.partition("?")
        response = server.respond(path, query)
        assert response.status == 200, page
        text = response.body.decode("utf-8")
        low = text.lower()
        for found in REFERENCE.findall(text):
            target = html.unescape(found)
            assert target.startswith("/") and not target.startswith("//"), (page, target)
            assert ":" not in target.split("?")[0], (page, target)
        csp = response.headers["Content-Security-Policy"]
        script = (
            serve.PLACES_SCRIPT_HASH
            if path == "/places"
            else serve.DAY_SCRIPT_HASH
            if server is voiced
            else None
        )
        if script is not None:
            assert text.count("<script") == 1 and "<script src" not in low and "<script>" in text, page
            assert f"script-src '{script}'" in csp and "'unsafe-inline'" not in csp.split("style-src")[0]
            assert "connect-src" not in csp, page
        else:
            assert "<script" not in low and "script-src" not in csp, page
        for tag in (
            "<link",
            "<iframe",
            "<frame",
            "<object",
            "<embed",
            "<base",
            "<meta http-equiv",
        ):
            assert tag not in low, (page, tag)
        style = re.search(r"<style>(.*?)</style>", text, re.S)
        assert style is not None, page
        assert "url(" not in style.group(1) and "@import" not in style.group(1), page
        assert "http://" not in style.group(1) and "https://" not in style.group(1), page
        assert csp.startswith("default-src 'none'"), page


# -- the pages ----------------------------------------------------------------------------------------------


def test_the_day_page_is_the_day_as_a_timeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Wednesday 10 June: lunch with Kari at the cafe. The timeline has the stays and moves in
    order, the lunch and the photo fold under the cafe's row behind a `details` toggle, the
    company is named, and the page links to the days either side."""
    _lb, site = _open(tmp_path, monkeypatch)
    response = site.respond("/day/2026-06-10", "")
    assert response.status == 200 and response.content_type.startswith("text/html")
    text = response.body.decode("utf-8")
    assert "<title>2026-06-10" in text and "Wednesday" in text
    assert 'href="/day/2026-06-09"' in text and 'href="/day/2026-06-11"' in text
    rows = re.findall(r'<li class="row ([a-z]+)"', text)
    assert rows[:3] == ["stay", "move", "stay"], rows
    assert "Office" in text and "Home" in text
    cafe = text[text.index("59.9200,10.7400") :]  # the cafe is not in places.json: its coordinates
    assert "<details" in cafe and "<summary>" in cafe
    assert "1 event" in cafe and "1 photo" in cafe
    assert "Lunch" in text and "Kari Nordmann" in text
    assert "night before" in text and "night after" in text
    assert "<details open>" not in text and 'href="/day/2026-06-10?open=1"' in text
    opened = site.respond("/day/2026-06-10", "open=1").body.decode("utf-8")
    assert "<details open>" in opened and "<details>" not in opened, "every toggle open"
    assert "dawarich" in text, "the sources table"


def test_the_day_page_has_the_flight_and_the_night_away(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _lb, site = _open(tmp_path, monkeypatch)
    text = site.respond("/day/2026-06-15", "").body.decode("utf-8")
    assert "XY 561" in text and "OSL" in text and "ZRH" in text and "tracked" in text
    assert '<li class="row flight"' in text
    assert "(Zurich)" in text and "away" in text
    text = site.respond("/day/2026-06-13", "").body.decode("utf-8")
    assert "aboard Solvind" in text and "Ola Nordmann" in text


def test_the_days_page_is_one_row_per_day_linking_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _lb, site = _open(tmp_path, monkeypatch)
    text = site.respond("/days", "from=2026-06-08&to=2026-06-21").body.decode("utf-8")
    links = re.findall(r'href="/day/(\d{4}-\d{2}-\d{2})"', text)
    assert links == [f"2026-06-{d:02d}" for d in range(8, 22)]
    assert "aboard Solvind" in text and "XY 561" in text and "Zurich" in text
    assert "Kari Nordmann" in text or "with 1" in text
    whole = site.respond("/days", "").body.decode("utf-8")
    assert re.findall(r'href="/day/(\d{4}-\d{2}-\d{2})"', whole) == links, "no window: the record's days"
    assert 'name="from"' in whole and 'name="to"' in whole, "the window is a form"
    backwards = site.respond("/days", "from=2026-06-21&to=2026-06-08")
    assert backwards.status == 400, "a window that runs backwards"


def test_the_trips_page_lists_the_trips_of_the_year(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _lb, site = _open(tmp_path, monkeypatch)
    text = site.respond("/trips", "year=2026").body.decode("utf-8")
    assert "Zurich" in text and "3 nights" in text
    assert html.unescape(re.search(r'href="(/days\?from=2026-06-15&amp;to=2026-06-18)"', text).group(1))  # type: ignore[union-attr]
    assert "aboard solvind" in text.lower()
    assert site.respond("/trips", "").body.decode("utf-8") == text, "no year: the record's last year"
    empty = site.respond("/trips", "year=1999").body.decode("utf-8")
    assert "no trips" in empty or "no days" in empty
    assert site.respond("/trips", "year=abcd").status == 400


def test_places_assets_and_gaps_pages(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _lb, site = _open(tmp_path, monkeypatch)
    places = site.respond("/places", "").body.decode("utf-8")
    for name in ("Home", "Office", "Marina"):
        assert f"<td>{name}</td>" in places
    assert "home" in places and "59.9139" in places
    assets = site.respond("/assets", "").body.decode("utf-8")
    assert "Solvind" in assets and "yacht" in assets and "999000001" in assets
    assert "ago" in assets, "the age of the last fix"
    gaps = site.respond("/gaps", "").body.decode("utf-8")
    assert "dawarich" in gaps and "missing days" in gaps.lower()
    assert "longest silence" in gaps.lower()


def test_unknown_pages_and_bad_days(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _lb, site = _open(tmp_path, monkeypatch)
    assert site.respond("/nothing", "").status == 404
    assert site.respond("/day/", "").status == 404
    assert site.respond("/day/2026-13-45", "").status == 400
    assert site.respond("/day/2026-06-10/extra", "").status == 404
    assert site.respond("/days", "from=yesterday").status == 400
    assert site.respond("/favicon.ico", "").status == 204
    body = site.respond("/day/2026-13-45", "").body.decode("utf-8")
    assert "not a date" in body and "<script" not in body


def test_serving_writes_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb, site = _open(tmp_path, monkeypatch)
    site.respond("/day/2026-06-10", "")  # the first reader builds the index
    head, before = lb.meta["head"], _files(lb.root)
    for page in PAGES:
        path, _, query = page.partition("?")
        site.respond(path, query)
    assert lb.meta["head"] == head and _files(lb.root) == before


# -- a record that moves while it is served ---------------------------------------------------------------


def _sync(lb: Logbook, text: str) -> None:
    """What a sync does while the server runs: another writer appends to the record (here a note at
    noon on the last day), and the head moves."""
    Logbook(lb.root).append_many([note(utc("2026-06-21", "12:00"), text)])


def test_a_page_is_read_again_when_the_head_has_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No restart after a sync: the next request reads the record at its new head."""
    lb, site = _open(tmp_path, monkeypatch)
    before = site.respond("/day/2026-06-21", "")
    assert "a synthetic note from the marina" not in before.body.decode("utf-8")
    _sync(lb, "a synthetic note from the marina")
    after = site.respond("/day/2026-06-21", "")
    assert "a synthetic note from the marina" in after.body.decode("utf-8")
    assert before.etag != after.etag


def test_the_index_is_brought_to_a_moved_head_once_whatever_asks_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The head moved and the index is not current (the writer found it stale and dropped it): the
    first request rebuilds it, once, and the requests that arrive with it wait for that rebuild
    instead of starting their own on the same file."""
    lb, site = _open(tmp_path, monkeypatch)
    site.respond("/", "")
    _sync(lb, "a synthetic note about the mooring")
    lb.index_path.unlink()
    rebuilds: list[int] = []
    original = index.Index.rebuild

    def counted(self: index.Index, *args: Any, **kwargs: Any) -> Any:
        rebuilds.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(index.Index, "rebuild", counted)
    pages = ["/", "/day/2026-06-21", "/days", "/trips", "/places", "/day/2026-06-20"] * 2
    statuses: list[int] = []
    threads = [
        threading.Thread(target=lambda p=p: statuses.append(site.respond(p, "").status)) for p in pages
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert statuses == [200] * len(pages)
    assert len(rebuilds) == 1
    assert "a synthetic note about the mooring" in site.respond("/day/2026-06-21", "").body.decode("utf-8")


def test_the_etag_is_the_head_and_a_reload_at_the_same_head_is_a_304_without_a_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, site = _open(tmp_path, monkeypatch)
    first = site.respond("/day/2026-06-10", "")
    etag = first.etag
    assert etag is not None and etag.startswith(f'"{lb.meta["head"][:12]}')
    assert first.headers["ETag"] == etag
    assert first.headers["Cache-Control"] == "no-cache", "kept by the browser, asked again every time"
    assert site.respond("/day/2026-06-10", "").etag == etag, "the same head, the same tag"

    monkeypatch.setattr(site, "_page", lambda *a: pytest.fail("a 304 renders nothing"))
    again = site.respond("/day/2026-06-10", "", if_none_match=etag)
    assert again.status == 304 and again.body == b"" and again.headers["ETag"] == etag
    assert "Content-Length" not in again.headers
    assert site.respond("/day/2026-06-10", "", if_none_match=f'"other", W/{etag}').status == 304
    monkeypatch.undo()
    assert site.respond("/day/2026-06-11", "", if_none_match=etag).status == 200, "one page's tag only"

    assert site.respond("/day/2026-06-10", "", if_none_match='"stale"').status == 200
    _sync(lb, "a synthetic note")
    moved = site.respond("/day/2026-06-10", "", if_none_match=etag)
    assert moved.status == 200 and moved.etag != etag, "the head moved: the page again"


def test_the_etag_moves_with_the_settings_the_pages_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A place renamed in places.json changes the pages without moving the head: so does the tag."""
    lb, site = _open(tmp_path, monkeypatch)
    etag = site.respond("/places", "").etag
    path = lb.root / "places.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["Harbour"] = data.pop("Marina")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    renamed = site.respond("/places", "", if_none_match=etag)
    assert renamed.status == 200 and "<td>Harbour</td>" in renamed.body.decode("utf-8")
    assert renamed.etag != etag


def test_pages_the_clock_moves_and_errors_carry_no_etag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _lb, site = _open(tmp_path, monkeypatch)
    for path in ("/assets", "/gaps", "/nowhere", "/day/2026-13-45"):
        response = site.respond(path, "")
        assert response.etag is None and "ETag" not in response.headers, path
        assert response.headers["Cache-Control"] == "no-store", path
        for tag in ("*", site.respond("/day/2026-06-10", "").etag or ""):
            assert site.respond(path, "", if_none_match=tag).status == response.status, (path, tag)


def test_today_is_the_current_day_in_the_records_timezone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Oslo in June is UTC+2: 21:59:59 UTC is still Sunday 21 June there, 22:00:00 is Monday."""
    lb = persona_record(tmp_path, monkeypatch)
    clock = [datetime(2026, 6, 21, 21, 59, 59, tzinfo=UTC)]
    site = serve.Site(lb, now=lambda: clock[0])
    late = site.respond("/today", "")
    assert late.status == 302 and late.headers["Location"] == "/day/2026-06-21"
    assert late.headers["Cache-Control"] == "no-store" and late.etag is None
    assert 'href="/day/2026-06-21"' in late.body.decode("utf-8")
    clock[0] = datetime(2026, 6, 21, 22, 0, 0, tzinfo=UTC)
    assert site.respond("/today", "").headers["Location"] == "/day/2026-06-22"
    assert 'href="/today"' in site.respond("/", "").body.decode("utf-8"), "in the navigation"


def test_today_west_of_utc_is_still_yesterday_there(tmp_path: Path) -> None:
    lb = Logbook.init(tmp_path / "ny", "America/New_York")
    site = serve.Site(lb, now=lambda: datetime(2026, 6, 22, 3, 30, tzinfo=UTC))  # 23:30 EDT on the 21st
    assert site.respond("/today", "").headers["Location"] == "/day/2026-06-21"


# -- the socket ---------------------------------------------------------------------------------------------


def test_the_server_answers_over_loopback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The real thing: a server on 127.0.0.1 and a free port, fetched with the stdlib client."""
    lb, _site = _open(tmp_path, monkeypatch)
    server = serve.make_server(lb, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/day/2026-06-10", timeout=10) as reply:
            assert reply.status == 200
            assert reply.headers["Content-Type"].startswith("text/html")
            assert "Office" in reply.read().decode("utf-8")
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/nowhere", timeout=10)
        assert e.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_a_reload_over_the_socket_is_a_304_and_today_a_redirect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, _site = _open(tmp_path, monkeypatch)
    server = serve.make_server(lb, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        connection.request("GET", "/day/2026-06-10")
        reply = connection.getresponse()
        assert reply.status == 200 and reply.read()
        etag = reply.getheader("ETag")
        assert etag is not None
        connection.request("GET", "/day/2026-06-10", headers={"If-None-Match": etag})
        reply = connection.getresponse()
        assert reply.status == 304 and reply.read() == b"" and reply.getheader("ETag") == etag
        connection.request("HEAD", "/day/2026-06-10", headers={"If-None-Match": etag})
        reply = connection.getresponse()
        assert reply.status == 304 and reply.read() == b""
        connection.request("GET", "/today")
        reply = connection.getresponse()
        assert reply.status == 302 and re.fullmatch(
            r"/day/\d{4}-\d{2}-\d{2}", reply.getheader("Location") or ""
        )
        reply.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
