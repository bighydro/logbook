"""`logbook serve [--port N]`: the record read in a browser, from this machine only. Server-rendered
HTML with one inline stylesheet, every page from the index and the readers (`day`, `days`, `trips`,
`places`, `assets status`, `sources --gaps`); nothing is written and nothing leaves the machine:
the server binds 127.0.0.1 and refuses any other host, and no page references a URL outside
itself. Synthetic Oslo persona, who does not exist."""

from __future__ import annotations

import html
import re
import threading
import urllib.request
from pathlib import Path

import pytest
from persona import persona_record

from logbook import cli
from logbook.contrib import serve
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
    a scheme, a host or a protocol-relative `//`. No script, no stylesheet link, no frame, no
    `url()` or `@import` in the inline style, and a Content-Security-Policy that would stop a
    browser following any of those even if one slipped in."""
    _lb, site = _open(tmp_path, monkeypatch)
    for page in PAGES:
        path, _, query = page.partition("?")
        response = site.respond(path, query)
        assert response.status == 200, page
        text = response.body.decode("utf-8")
        low = text.lower()
        for found in REFERENCE.findall(text):
            target = html.unescape(found)
            assert target.startswith("/") and not target.startswith("//"), (page, target)
            assert ":" not in target.split("?")[0], (page, target)
        for tag in (
            "<script",
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
        assert response.headers["Content-Security-Policy"].startswith("default-src 'none'"), page


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
