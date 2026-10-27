"""No form of the Library is posted from a frame or from another site: on this machine, a POST whose
browser says it came from inside a frame (`Sec-Fetch-Dest` other than `document`) or from another
site (`Sec-Fetch-Site` other than `same-origin` or `none`) is a 403 and nothing is written, with an
Origin or without one; the owner's own form, sent from the server's own page, writes as it did. With
the star and the sign forms of the four synthetic years (`library_record.py`); nobody here exists."""

from __future__ import annotations

import html
import http.client
import threading
from pathlib import Path
from urllib.parse import urlencode

import pytest
import test_library_walk as walk
import test_serve_browser_origin as origins

from logbook.contrib import phone, serve
from logbook.core.store import Logbook

PORT = 8765
HERE = f"http://{walk.LOOPBACK}:{PORT}"

years = walk.years
manifest = walk.manifest
shelf_of_ideas = walk.shelf_of_ideas


def _asked(origin: str | None, dest: str | None = None, site: str | None = None) -> phone.Asked:
    """This machine's browser's headers: the Host it asked, its Origin, and the two `Sec-Fetch-*`."""
    one = lambda value: () if value is None else (value,)  # noqa: E731
    return phone.Asked(one(origin), (f"{walk.LOOPBACK}:{PORT}",), (), one(dest), (), one(site))


def _star_and_sign(
    years: Path, manifest: Path, shelf_of_ideas: Path, root: Path, mp: pytest.MonkeyPatch
) -> list[walk.Act]:
    acts = origins._acts(root, years, manifest, shelf_of_ideas, mp)
    found = [
        a for a in acts if (a.path == serve.STAR_PATH and a.form["act"] == "star") or a.path.endswith("/sign")
    ]
    assert {a.path for a in found} == {serve.STAR_PATH, f"/day/{walk.DAY}/sign"}
    return found


FRAMED_OR_CROSS = [
    pytest.param(HERE, "iframe", "same-origin", id="framed"),
    pytest.param(HERE, "frame", "same-origin", id="frame"),
    pytest.param(HERE, "embed", None, id="embed"),
    pytest.param(None, "iframe", None, id="framed-no-origin"),
    pytest.param(None, "document", "cross-site", id="cross-site-no-origin"),
    pytest.param(None, None, "cross-site", id="cross-site-no-dest"),
    pytest.param(None, "document", "same-site", id="same-site-no-origin"),  # another port of 127.0.0.1
    pytest.param(HERE, "document", "cross-site", id="cross-site-with-origin"),
]


@pytest.mark.parametrize(("origin", "dest", "site"), FRAMED_OR_CROSS)
def test_a_framed_or_cross_site_post_is_refused_and_writes_nothing(
    years: Path,
    manifest: Path,
    shelf_of_ideas: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    origin: str | None,
    dest: str | None,
    site: str | None,
) -> None:
    acts = _star_and_sign(years, manifest, shelf_of_ideas, tmp_path, monkeypatch)
    roots = {a.site.lb.root for a in acts}
    before = {root: (walk._files(root), Logbook(root).meta["head"]) for root in roots}
    for act in acts:
        response = act.site.write(
            act.path, act.form, walk.LOOPBACK, origin, act.upload, asked=_asked(origin, dest, site)
        )
        page = html.unescape(response.body.decode("utf-8"))
        assert response.status == 403, (walk._kind(act), response.status)
        assert "nothing was written" in page, walk._kind(act)
    assert {root: (walk._files(root), Logbook(root).meta["head"]) for root in roots} == before


@pytest.mark.parametrize(
    ("origin", "dest", "site"),
    [
        pytest.param(HERE, "document", "same-origin", id="the-owner-s-form"),
        pytest.param(None, "document", "none", id="typed-by-the-owner"),  # no Origin, as an old browser
        pytest.param(HERE, None, None, id="no-fetch-metadata"),  # a browser that sends none
        pytest.param(HERE, "Document", "Same-Origin", id="any-case"),
    ],
)
def test_the_owner_s_own_form_still_writes(
    years: Path,
    manifest: Path,
    shelf_of_ideas: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    origin: str | None,
    dest: str | None,
    site: str | None,
) -> None:
    acts = _star_and_sign(years, manifest, shelf_of_ideas, tmp_path, monkeypatch)
    for act in acts:
        head = act.site.lb.meta["head"]
        response = act.site.write(
            act.path, act.form, walk.LOOPBACK, origin, act.upload, asked=_asked(origin, dest, site)
        )
        assert response.status == 303, (walk._kind(act), response.status)
        assert act.site.lb.meta["head"] != head, walk._kind(act)


def test_over_the_socket_a_framed_star_is_refused_and_the_page_s_own_writes(
    years: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The handler hands the gate the browser's `Sec-Fetch-*`: the Day's Star posted from a frame, or
    from another site without an Origin, is a 403 and nothing written; from the Day itself, a 303."""
    site = walk._years_site(walk._copy(years, tmp_path / "years", monkeypatch))
    server = serve.Server(0, site)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        here = f"http://{walk.LOOPBACK}:{port}"
        connection = http.client.HTTPConnection(walk.LOOPBACK, port, timeout=10)
        try:
            connection.request("GET", f"/day/{walk.DAY}")
            reply = connection.getresponse()
            text = reply.read().decode("utf-8")
        finally:
            connection.close()
        assert reply.getheader("X-Frame-Options") == "DENY"
        assert "frame-ancestors 'none'" in (reply.getheader("Content-Security-Policy") or "")
        star = next(f for f in walk._forms(text, "star"))
        body = urlencode({**star.fields, "act": "star"}).encode("utf-8")
        head = site.lb.meta["head"]
        loopback = ("Host", f"{walk.LOOPBACK}:{port}")
        for sent in (
            [loopback, ("Origin", here), ("Sec-Fetch-Dest", "iframe"), ("Sec-Fetch-Site", "same-origin")],
            [loopback, ("Sec-Fetch-Dest", "document"), ("Sec-Fetch-Site", "cross-site")],
            [loopback, ("Sec-Fetch-Site", "same-site")],
        ):
            status, page = _post(port, star.action, body, sent)
            assert status == 403 and "nothing was written" in page, sent
        assert Logbook(site.lb.root).meta["head"] == head
        owner = [
            loopback,
            ("Origin", here),
            ("Sec-Fetch-Dest", "document"),
            ("Sec-Fetch-Site", "same-origin"),
        ]
        status, _ = _post(port, star.action, body, owner)
        assert status == 303
        assert Logbook(site.lb.root).meta["head"] != head, "the owner's own star is written"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _post(port: int, path: str, body: bytes, headers: list[tuple[str, str]]) -> tuple[int, str]:
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
        return reply.status, html.unescape(reply.read().decode("utf-8"))
    finally:
        connection.close()
