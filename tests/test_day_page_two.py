"""The Day page, second pass: the day's photos as a strip under the rows they belong to, starred first,
a thumbnail only from the record's own attachment store and a count for the rest, never a broken
image; the photo review at its foot (Star, Not a keeper) through the star's path and its 409; the
day's track as an inline drawing from the record's own coordinates; every row a link to its line as
written (`/line/ID`), read-only and through the gate; the week's draft on its Sunday and a link to it
from the other six days; the sentence that says what crosses where; many edits of one Drive file one
row with a count; a typed portfolio kept on a busy retry; and `with` on a day no device saw. On the
Oslo persona and the dream's fortnight, who do not exist; no test opens a connection."""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import zlib
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from dream_fortnight import W25, fake, fortnight, run_cli
from orgs_record import TODAY, evidence_record, settle
from persona import CAFE, note, persona_record, photo, utc

from logbook import cli
from logbook.contrib import day_photos, dream, orgs, serve
from logbook.core import attachments, policy
from logbook.core.chain import Line
from logbook.core.store import Logbook

LOOPBACK = "127.0.0.1"
WEDNESDAY, FRIDAY = "2026-06-10", "2026-06-12"
JUNE = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)
NO_DEVICE = "2026-05-02"  # a Saturday before the fortnight: no line at all, the phones were off
CLOCK = ("id", "seq", "prev", "hash", "recorded_at")
BUDGET, CREW = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456", "1ZyXwVuTsRqPoNmLkJiHgFeDcBa6543210"


def _png(colour: tuple[int, int, int]) -> bytes:
    """A one-pixel PNG of `colour`, made here: synthetic pixels."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = b"\x00" + bytes(colour)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


@pytest.fixture(scope="module")
def pristine(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The persona's fortnight with the library's favourites read into keepers (`derive keepers`), so
    the cafe photo of Wednesday is starred."""
    with pytest.MonkeyPatch.context() as mp:
        lb = persona_record(tmp_path_factory.mktemp("day-page-two"), mp)
        cli.main(["derive", "keepers"])
        return lb.root


@pytest.fixture
def lb(pristine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    root = tmp_path / "lb"
    shutil.copytree(pristine, root)
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    return Logbook(root)


def _site(lb: Logbook, **kw: Any) -> serve.Site:
    return serve.Site(lb, now=lambda: JUNE, **kw)


def _page(site: serve.Site, day: str = WEDNESDAY, query: str = "") -> str:
    response = site.respond(f"/day/{day}", query)
    assert response.status == 200, response.body[:300]
    return response.body.decode("utf-8")


def _of(lb: Logbook, kind: str) -> list[Line]:
    return [line for line in Logbook(lb.root).lines() if line["kind"] == kind]


def _at(lb: Logbook, kind: str, at: str) -> Line:
    (found,) = [line for line in _of(lb, kind) if line["at"] == at]
    return found


def _stored_photo(lb: Logbook, at: str, where: tuple[float, float], data: bytes, media: str) -> Line:
    """A photo line whose pixels the attachment store holds (a §1.1 reference under `content`)."""
    attachments.write(lb.root, data)
    draft = photo(at, where)
    draft["payload"]["content"] = attachments.reference(data, media)
    draft["payload"]["raw_id"] = draft["payload"]["asset_id"] = f"stored-{at}"
    draft["source"] = draft["payload"]["library"] = "apple-photos"
    return _append(lb, draft)


def _append(lb: Logbook, draft: dict[str, Any]) -> Line:
    return lb.append(**draft)


def _section(page: str, start: str, end: str = "</section>") -> str:
    """The part of `page` from `start` to `end`; empty when the page has no such part."""
    i = page.find(start)
    return "" if i < 0 else page[i : page.index(end, i)]


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _hold(lb: Logbook) -> dict[str, object]:
    holder = {"pid": os.getppid(), "command": "logbook sync", "since": "2026-06-12T21:00:00Z"}
    path = lb.root / "state" / "writer.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(holder), encoding="utf-8")
    return holder


# -- 1. the photos ---------------------------------------------------------------------------------------


def test_the_photos_are_a_strip_under_their_row_starred_first_and_never_a_broken_image(lb: Logbook) -> None:
    """At the cafe: the library's favourite (a keeper, so starred) and two more, one whose pixels the
    store holds (a PNG), one whose reference names a file the store does not have, and a HEIC the
    store holds, which no browser can be relied on to draw. One strip under the cafe's row: the
    starred photo first, one thumbnail (the PNG, from the server's own path), the other three counted."""
    png = _stored_photo(lb, utc(WEDNESDAY, "12:40"), CAFE, _png((40, 90, 120)), "image/png")
    heic = _stored_photo(
        lb, utc(WEDNESDAY, "12:45"), CAFE, b"\x00\x00\x00\x18ftypheic" + b"\0" * 16, "image/heic"
    )
    lost = photo(utc(WEDNESDAY, "12:50"), CAFE)
    lost["payload"]["content"] = attachments.reference(_png((1, 2, 3)), "image/png")  # never written
    lost["payload"]["raw_id"] = lost["payload"]["asset_id"] = "lost"
    lost_line = _append(lb, lost)
    favourite = _at(lb, "photo", utc(WEDNESDAY, "12:30"))
    page = _page(_site(lb))
    strips = re.findall(r'<ul class="strip"[^>]*>.*?</ul>', page, re.S)
    assert len(strips) == 1, strips
    (strip,) = strips
    assert strip.index(favourite["id"]) < strip.index(png["id"]), "starred first"
    shown_above = page[: page.find('<section class="review"')]
    assert re.findall(r'<img [^>]*src="([^"]+)"', shown_above) == [f"/photo/{png['id']}"], "one thumbnail"
    assert re.search(r"<img [^>]*alt=\"[^\"]+\"", strip) and "max-width" in page
    assert "3 photos not on this machine" in strip, strip
    for line in (heic, lost_line, favourite):
        assert f'src="/photo/{line["id"]}"' not in page
    shown = _site(lb).respond(f"/photo/{png['id']}", "")
    assert shown.status == 200 and shown.content_type == "image/png" and shown.body == _png((40, 90, 120))
    for line in (heic, lost_line, favourite):
        assert _site(lb).respond(f"/photo/{line['id']}", "").status == 404, line["id"]
    assert _site(lb).respond("/photo/not-a-line", "").status == 404
    note_line = _of(lb, "event")[0]
    assert _site(lb).respond(f"/photo/{note_line['id']}", "").status == 404, "only a photo's pixels"


def test_a_photo_is_shown_through_the_gate_and_never_on_a_static_page(lb: Logbook) -> None:
    """A thumbnail is the line's: a reader whose gate leaves the photo out neither lists it nor serves
    its pixels, and a retracted photo is gone from both. The Day's policy lets images come from the
    server and nowhere else, and no other page's does; a static page draws no image at all."""
    png = _stored_photo(lb, utc(WEDNESDAY, "12:40"), CAFE, _png((9, 9, 9)), "image/png")
    response = _site(lb).respond(f"/day/{WEDNESDAY}", "")
    csp = response.headers["Content-Security-Policy"]
    assert csp.startswith("default-src 'none'; img-src 'self';"), csp
    assert "img-src" not in _site(lb).respond("/days", "").headers["Content-Security-Policy"]
    gated = _site(lb, tiers=[2, 3])
    assert png["id"] not in _page(gated) and gated.respond(f"/photo/{png['id']}", "").status == 404
    static = serve.Site(lb, now=lambda: JUNE, href=lambda path: path if path.startswith("/day/") else None)
    text = _page(static)
    assert "<img" not in text and 'class="review"' not in text and "photo not on this machine" not in text
    lb.retract(png["seq"], "the wrong picture")
    assert _site(lb).respond(f"/photo/{png['id']}", "").status == 404
    assert f"/photo/{png['id']}" not in _page(_site(lb))


# -- 1b. the photo review -------------------------------------------------------------------------------


def test_the_review_lists_the_day_s_unstarred_photos_and_star_writes_what_the_cli_writes(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    png = _stored_photo(lb, utc(WEDNESDAY, "12:40"), CAFE, _png((5, 5, 5)), "image/png")
    other = tmp_path / "other"
    shutil.copytree(lb.root, other)
    favourite = _at(lb, "photo", utc(WEDNESDAY, "12:30"))
    site = _site(lb)
    review = _section(_page(site), '<section class="review"')
    assert 'id="photos"' in review and png["id"] in review and favourite["id"] not in review, "unstarred only"
    assert f'src="/photo/{png["id"]}"' in review
    forms = re.findall(r'<form class="keep"[^>]*>.*?</form>', review, re.S)
    assert len(forms) == 2 and all(f'action="{serve.STAR_PATH}"' in f for f in forms)
    assert {re.search(r'name="act" value="([a-z]+)"', f).group(1) for f in forms} == {"star", serve.PASS}
    answer = site.write(
        serve.STAR_PATH,
        {"act": "star", "line": png["id"], "day": WEDNESDAY, "from": "photos"},
        LOOPBACK,
        None,
    )
    assert answer.status == 303 and answer.location == f"/day/{WEDNESDAY}#photos"
    monkeypatch.setenv("LOGBOOK_HOME", str(other))
    cli.main(["star", png["id"]])
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    mine = [k for k in _of(lb, "keeper") if k["payload"]["photo"]["line"] == png["id"]]
    theirs = [
        k
        for k in Logbook(other).lines()
        if k["kind"] == "keeper" and k["payload"]["photo"]["line"] == png["id"]
    ]
    assert len(mine) == len(theirs) == 1
    assert {k: v for k, v in mine[0].items() if k not in CLOCK} == {
        k: v for k, v in theirs[0].items() if k not in CLOCK
    }
    assert png["id"] not in _section(_page(site), '<section class="review"'), "starred: out of the review"


def test_not_a_keeper_writes_no_line_and_the_review_does_not_ask_again(lb: Logbook) -> None:
    """Not a keeper is no line (RFC 0024 rule 3, RFC 0041 rule 4): the review's own bookkeeping in
    `state/photo-review.json`, so the photo is not asked about again; it stays on the Day's strip,
    and starring it later still stars it."""
    png = _stored_photo(lb, utc(WEDNESDAY, "12:40"), CAFE, _png((6, 6, 6)), "image/png")
    site = _site(lb)
    head = lb.meta["head"]
    form = {"act": serve.PASS, "line": png["id"], "day": WEDNESDAY, "from": "photos"}
    answer = site.write(serve.STAR_PATH, form, LOOPBACK, None)
    assert answer.status == 303 and answer.location == f"/day/{WEDNESDAY}#photos"
    assert Logbook(lb.root).meta["head"] == head, "no line"
    assert day_photos.passed(lb.root) == {png["id"]}
    page = _page(site)
    assert png["id"] not in _section(page, '<section class="review"') and f'src="/photo/{png["id"]}"' in page
    again = site.write(serve.STAR_PATH, form, LOOPBACK, None)
    assert again.status == 303 and json.loads(day_photos.state_path(lb.root).read_text("utf-8"))[
        "passed"
    ] == [png["id"]]
    event = _of(lb, "event")[0]
    refused = site.write(serve.STAR_PATH, {**form, "line": event["id"]}, LOOPBACK, None)
    assert refused.status == 400 and "photo" in refused.body.decode("utf-8")
    assert site.write(serve.STAR_PATH, {**form, "act": "star"}, LOOPBACK, None).status == 303
    assert any(k["payload"]["photo"]["line"] == png["id"] for k in _of(lb, "keeper"))


def test_the_review_s_acts_answer_409_while_another_command_writes(lb: Logbook) -> None:
    png = _stored_photo(lb, utc(WEDNESDAY, "12:40"), CAFE, _png((7, 7, 7)), "image/png")
    site = _site(lb)
    holder = _hold(lb)
    before = _files(lb.root)
    for act in ("star", serve.PASS):
        form = {"act": act, "line": png["id"], "day": WEDNESDAY, "from": "photos"}
        response = site.write(serve.STAR_PATH, form, LOOPBACK, None)
        said = response.body.decode("utf-8")
        assert response.status == 409 and serve.BUSY in said, act
        for name, value in form.items():
            assert f'name="{name}" value="{value}"' in said, (act, name)
    assert (
        _files(lb.root) == before
        and json.loads((lb.root / "state" / "writer.lock").read_text("utf-8")) == holder
    )


# -- 2. the track -----------------------------------------------------------------------------------------


def test_the_day_s_track_is_drawn_here_from_the_record_s_coordinates(lb: Logbook) -> None:
    """Wednesday: home, the office, the cafe, the office, home: a dot per stay with a position,
    numbered in order, a line per move between them; no tile, no image, no link inside it."""
    page = _page(_site(lb))
    found = re.search(r'<svg class="track"[^>]*>.*?</svg>', page, re.S)
    assert found is not None
    svg = found.group(0)
    assert svg.count("<circle") >= 3 and svg.count("<line") >= 2 and "km" in svg
    assert "<image" not in svg and "href" not in svg and "url(" not in svg
    labels = re.findall(r"<text[^>]*>([\d, ]+)</text>", svg)
    numbers = sorted(int(n) for label in labels for n in label.split(", "))
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 3, labels
    assert '<svg class="track"' not in _page(_site(lb), NO_DEVICE)


# -- 3. the raw line ---------------------------------------------------------------------------------------


def test_every_row_that_is_a_line_opens_its_line_read_only_and_through_the_gate(lb: Logbook) -> None:
    lunch = _at(lb, "event", utc(WEDNESDAY, "12:00"))
    favourite = _at(lb, "photo", utc(WEDNESDAY, "12:30"))
    page = _page(_site(lb))
    for line in (lunch, favourite):
        assert f'href="/line/{line["id"]}"' in page, line["kind"]
    raw = _site(lb).respond(f"/line/{lunch['id']}", "")
    text = raw.body.decode("utf-8")
    assert raw.status == 200 and raw.etag is not None and "<form" not in text
    assert "Lunch" in text and lunch["hash"] in text and f'href="/day/{WEDNESDAY}"' in text
    assert re.search(r"<pre[^>]*>", text) and "&quot;schema&quot;: &quot;event/v1&quot;" in text
    written = _append(lb, note(utc(WEDNESDAY, "15:00"), "A synthetic thought, tier 2."))
    assert _site(lb).respond(f"/line/{written['id']}", "").status == 200
    gated = _site(lb, tiers=[1])
    hidden = gated.respond(f"/line/{written['id']}", "")
    missing = gated.respond("/line/no-such-line", "")
    assert hidden.status == missing.status == 404
    assert written["id"] not in _page(gated)
    assert hidden.body.decode("utf-8").replace(written["id"], "X") == missing.body.decode("utf-8").replace(
        "no-such-line", "X"
    ), "a line above the gate reads as no line"
    lb.retract(written["seq"], "not what I meant")
    assert "retracted" in _site(lb).respond(f"/line/{written['id']}", "").body.decode("utf-8")
    static = serve.Site(lb, now=lambda: JUNE, href=lambda path: path if path.startswith("/day/") else None)
    assert "/line/" not in _page(static)


# -- 4. the week -------------------------------------------------------------------------------------------


def test_the_week_s_draft_is_on_its_sunday_and_linked_from_the_other_days(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: object
) -> None:
    lb = fortnight(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    from dream_fortnight import ENV

    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    monkeypatch.setattr(dream, "today", lambda: date(2026, 6, 22))
    fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] == 0
    (week,) = [
        line
        for line in Logbook(lb.root).lines()
        if line["kind"] == "draft" and line["payload"]["unit"] == "week" and line["payload"]["subject"] == W25
    ]
    site = serve.Site(lb, now=lambda: datetime(2026, 6, 22, 12, tzinfo=UTC))
    sunday = _page(site, "2026-06-21")
    assert f'id="{serve.WEEK}"' in sunday and W25 in sunday and week["id"] in sunday
    assert "next week" in sunday and f'href="/line/{week["id"]}"' in sunday
    for day in ("2026-06-15", "2026-06-18", "2026-06-20"):
        assert 'href="/day/2026-06-21#week"' in _page(site, day), day
    assert 'href="/day/2026-06-21#week"' not in _page(site, "2026-06-14"), "another week"
    gated = serve.Site(lb, now=lambda: datetime(2026, 6, 22, 12, tzinfo=UTC), tiers=[1])
    assert week["tier"] == 2 and week["id"] not in _page(gated, "2026-06-21"), "the draft's tier"
    assert 'href="/day/2026-06-21#week"' not in _page(gated, "2026-06-15")


# -- 5. the tiers ------------------------------------------------------------------------------------------


def test_one_sentence_under_the_header_says_what_crosses_where(lb: Logbook) -> None:
    page = _page(_site(lb))
    found = re.search(r'<p class="tiers">(.*?)</p>', page)
    assert found is not None and page.index("</dl>") < page.index('<p class="tiers">')
    said = found.group(1).lower()
    assert "tier 1" in said and "tier 2" in said and "tier 3" in said
    assert "where you were" in said and "what was said" in said and "money and health" in said
    assert said.count(".") == 1, "one sentence"


# -- 6. the folds ------------------------------------------------------------------------------------------


def _drive(at: str, end: str | None, file_id: str, name: str, activity: str, count: int) -> dict[str, Any]:
    """A Drive line as `sync drive` writes one: a file's activities of one hour, folded with a count."""
    word = {"edit": "Edited", "rename": "Renamed", "comment": "Commented on"}[activity]
    return {
        "at": at,
        "end": end,
        "source": "drive",
        "kind": "event",
        "tier": 1,
        "payload": {
            "schema": "event/v1",
            "raw_id": f"{file_id}/{activity}@{at}/abc",
            "title": f"{word} {name}" + (f" ×{count}" if count > 1 else ""),
            "all_day": False,
            "calendar": {"id": "google-drive", "name": "Google Drive"},
            "modified_at": end or at,
            "extra": {
                "activity": activity,
                "count": count,
                "file": {"id": file_id, "name": name, "mime_type": "application/vnd.google-apps.document"},
                "by_owner": True,
            },
        },
    }


def test_many_edits_of_one_drive_file_in_a_day_read_as_one_row_with_a_count(lb: Logbook) -> None:
    written = [
        _append(lb, d)
        for d in [
            _drive(utc(WEDNESDAY, "08:20"), utc(WEDNESDAY, "08:50"), BUDGET, "Budget 2027", "edit", 4),
            _drive(utc(WEDNESDAY, "09:05"), None, BUDGET, "Budget 2027", "edit", 1),
            _drive(utc(WEDNESDAY, "10:10"), utc(WEDNESDAY, "10:40"), BUDGET, "Budget 2027", "comment", 2),
            _drive(utc(WEDNESDAY, "10:30"), None, CREW, "Crew list", "rename", 1),
        ]
    ]
    page = _page(_site(lb))
    rows = re.findall(r"<li[^>]*>(?:(?!</li>).)*Budget 2027(?:(?!</li>).)*</li>", page, re.S)
    assert len(rows) == 1, rows
    (row,) = rows
    assert "5 edits, 2 comments" in row and "3 lines" in row
    assert f'href="/line/{written[0]["id"]}"' in row
    assert all(line["id"] in row for line in written[:3])
    crew = re.findall(r"<li[^>]*>(?:(?!</li>).)*Crew list(?:(?!</li>).)*</li>", page, re.S)
    assert len(crew) == 1 and "Renamed Crew list" in crew[0]


# -- 7. the portfolio, kept ---------------------------------------------------------------------------------


def test_a_typed_portfolio_comes_back_typed_on_a_busy_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGBOOK_DIAL_PREFIX", "44")
    lb = evidence_record(tmp_path / "orgs")
    settle(lb)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    org = next(iter(orgs.named(lb).values())).id
    site = serve.Site(lb, now=lambda: datetime.fromisoformat(f"{TODAY}T12:00:00").replace(tzinfo=UTC))
    _hold(lb)
    form = {
        "org": org,
        "back": f"/org/{org}",
        "status": "hold",
        "reason": "",
        "at": "",
        "portfolio": "Fjord holdings",
        "portfolio_was": "",
        "act": "status",
    }
    response = site.write(serve.MANIFEST_STATUS, form, LOOPBACK, None)
    said = response.body.decode("utf-8")
    assert response.status == 409
    assert '<input type="text" name="portfolio" value="Fjord holdings"' in said, said
    assert '<input type="hidden" name="portfolio_was" value=""' in said


# -- 8. with, on a day no device saw ------------------------------------------------------------------------


def test_with_on_a_day_no_device_saw_is_the_line_the_page_writes(
    lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The night the phones were off: no line on the day at all. The Day still has its `with` row and
    says why the record saw nobody; `logbook with DAY NAME --at` and the page's field write the same
    line, byte for byte but for the clock; the header names the person, your word marked."""
    other = tmp_path / "other"
    shutil.copytree(lb.root, other)
    site = _site(lb)
    before = _page(site, NO_DEVICE)
    assert "nothing logged" in before and serve.NO_DEVICE_WITH in before
    answer = site.write(serve.WITH_PATH, {"day": NO_DEVICE, "names": "Ola", "at": "23:00"}, LOOPBACK, None)
    assert answer.status == 303
    monkeypatch.setenv("LOGBOOK_HOME", str(other))
    cli.main(["with", NO_DEVICE, "Ola", "--at", "23:00"])
    assert "with Ola Nordmann" in capsys.readouterr().out
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    (mine,) = [line for line in _of(lb, "note") if line["at"].startswith("2026-05-02")]
    (theirs,) = [
        line
        for line in Logbook(other).lines()
        if line["kind"] == "note" and line["at"].startswith("2026-05-02")
    ]
    assert {k: v for k, v in mine.items() if k not in CLOCK} == {
        k: v for k, v in theirs.items() if k not in CLOCK
    }
    after = _page(site, NO_DEVICE)
    assert "Ola Nordmann (you said)" in after and serve.NO_DEVICE_WITH not in after


def test_not_a_keeper_is_refused_for_any_line_not_a_photo_of_the_day_standing_and_writes_nothing(
    lb: Logbook,
) -> None:
    """A photo of another day, a retracted photo, a photo above the page's gate and an id the record
    does not have: each a 400, and nothing written, not even the review's file. A review file that is
    not what it should be never breaks the Day: the review asks again."""
    png = _stored_photo(lb, utc(WEDNESDAY, "12:40"), CAFE, _png((8, 8, 8)), "image/png")
    gone = _stored_photo(lb, utc(WEDNESDAY, "12:45"), CAFE, _png((8, 8, 9)), "image/png")
    lb.retract(gone["seq"], "a duplicate")
    before = _files(lb.root)
    for site, form in (
        (_site(lb), {"line": png["id"], "day": FRIDAY}),
        (_site(lb), {"line": gone["id"], "day": WEDNESDAY}),
        (_site(lb, tiers=[2, 3]), {"line": png["id"], "day": WEDNESDAY}),
        (_site(lb), {"line": "no-such-line", "day": WEDNESDAY}),
    ):
        response = site.write(serve.STAR_PATH, {**form, "act": serve.PASS, "from": "photos"}, LOOPBACK, None)
        assert response.status == 400, (form, response.body[:200])
    assert _files(lb.root) == before
    path = day_photos.state_path(lb.root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert png["id"] in _section(_page(_site(lb)), '<section class="review"')
    assert (
        _site(lb)
        .write(serve.STAR_PATH, {"line": png["id"], "day": WEDNESDAY, "act": serve.PASS}, LOOPBACK, None)
        .status
        == 303
    )
    assert day_photos.passed(lb.root) == {png["id"]}


def test_a_sealed_photo_is_a_thumbnail_only_where_this_machine_opens_it(tmp_path: Path) -> None:
    """A sealed file (RFC 0029 §7) is drawn only when the identity here opens it to the type its
    reference names: with none, or with one it was not sealed to, it is counted, never an `<img>` the
    server would then answer 404 for."""
    from logbook.core import sealing

    (secret, recipient), (stranger, _) = sealing.generate_identity(), sealing.generate_identity()
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    meta = lb.meta
    meta["recipients"] = [recipient]
    lb._save_meta(meta)
    data = _png((3, 4, 5))
    attachments.write(lb.root, data, [recipient])
    draft = photo(utc(WEDNESDAY, "12:00"), CAFE)
    draft["payload"]["content"] = attachments.reference(data, "image/png")
    line = Logbook(lb.root).append(**draft)
    for name, key, shown in (("owner", secret, True), ("stranger", stranger, False)):
        sealing.write_identity_file(tmp_path / "keys" / f"{name}.txt", key, "test")
        keyed = Logbook(lb.root, identity_file=tmp_path / "keys" / f"{name}.txt")
        assert (day_photos.stored(keyed, line) is not None) is shown, name
        if shown:
            assert day_photos.pixels(keyed, day_photos.stored(keyed, line)) == data  # type: ignore[arg-type]
    keyless = Logbook(lb.root, identity_file=tmp_path / "keys" / "nowhere.txt")
    assert day_photos.stored(keyless, line) is None


# -- what the independent review found -----------------------------------------------------------------------


def test_a_line_whose_retraction_is_above_the_gate_reads_as_no_line(lb: Logbook) -> None:
    """A retraction is tier 2: through a tier-1 gate, a tier-1 line retracted reads as no line, never
    with the retraction's number or its reason; the whole record reads both."""
    lunch = _at(lb, "event", utc(WEDNESDAY, "12:00"))
    lb.retract(lunch["seq"], "a synthetic reason, tier 2")
    gated = _site(lb, tiers=[1]).respond(f"/line/{lunch['id']}", "")
    assert gated.status == 404 and "synthetic reason" not in gated.body.decode("utf-8")
    whole = _site(lb).respond(f"/line/{lunch['id']}", "").body.decode("utf-8")
    assert "retracted by #" in whole and "synthetic reason" in whole


def test_a_draft_the_dream_entry_withholds_is_no_line_on_its_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: object
) -> None:
    """The Day shows a withheld draft's row and never its words (`drafts.allowed`); `/line/ID` keeps to
    it: the week's draft, its entry taken away, is a 404, and again a page once the entry allows it."""
    from dream_fortnight import ENV, set_dream_entry

    lb = fortnight(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    monkeypatch.setattr(dream, "today", lambda: date(2026, 6, 22))
    fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] == 0
    (week,) = [
        line
        for line in Logbook(lb.root).lines()
        if line["kind"] == "draft" and line["payload"]["unit"] == "week" and line["payload"]["subject"] == W25
    ]
    site = serve.Site(lb, now=lambda: datetime(2026, 6, 22, 12, tzinfo=UTC))
    assert site.respond(f"/line/{week['id']}", "").status == 200
    set_dream_entry(lb.root, None)
    withheld = site.respond(f"/line/{week['id']}", "")
    assert withheld.status == 404 and "hours at" not in withheld.body.decode("utf-8")
    assert "hours at" not in _page(site, "2026-06-21")


def test_no_device_saw_is_said_only_of_a_day_that_has_begun_and_holds_no_line(lb: Logbook) -> None:
    site = _site(lb)
    assert serve.NO_DEVICE_WITH not in _page(site, "2026-06-25"), "a day ahead"
    _append(lb, photo(utc("2026-05-03", "12:00"), CAFE))
    page = _page(site, "2026-05-03")
    assert serve.NO_DEVICE_WITH not in page and "nobody the record saw" in page, "a photo saw it"


def test_a_photo_in_no_row_has_its_strip_under_its_own_heading(lb: Logbook) -> None:
    """A day with no stay (the phones off, the camera on): the photo is in no row, and its strip is
    under a heading of its own, with its thumbnail."""
    png = _stored_photo(lb, utc("2026-05-03", "12:00"), CAFE, _png((2, 2, 2)), "image/png")
    page = _page(_site(lb), "2026-05-03")
    above = page[: page.find('<section class="review"')]
    assert "<h2>Photos outside any stay</h2>" in above and f'src="/photo/{png["id"]}"' in above


def test_a_photo_s_tag_is_its_digest_and_a_reload_is_a_304(lb: Logbook) -> None:
    png = _stored_photo(lb, utc(WEDNESDAY, "12:40"), CAFE, _png((1, 1, 1)), "image/png")
    first = _site(lb).respond(f"/photo/{png['id']}", "")
    assert (
        first.status == 200
        and first.etag is not None
        and first.headers["X-Content-Type-Options"] == "nosniff"
    )
    again = _site(lb).respond(f"/photo/{png['id']}", "", if_none_match=first.etag)
    assert again.status == 304 and again.body == b""


def test_a_day_with_thumbnails_and_its_review_fits_a_phone(lb: Logbook) -> None:
    import phone_width

    for n in range(6):
        _stored_photo(lb, utc(WEDNESDAY, f"12:{40 + n}"), CAFE, _png((n, n, n)), "image/png")
    page = _page(_site(lb))
    assert page.count("<img ") >= 12, "six in the strip, six in the review"
    assert phone_width.problems(page) == []
    raw = _site(lb).respond(f"/line/{_of(lb, 'photo')[0]['id']}", "").body.decode("utf-8")
    assert phone_width.problems(raw) == []


def test_a_static_page_links_the_week_to_its_sunday_s_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_network: object
) -> None:
    from dream_fortnight import ENV

    lb = fortnight(tmp_path / "lb")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    for name, value in ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(policy, "today", lambda: date(2026, 6, 20))
    monkeypatch.setattr(dream, "today", lambda: date(2026, 6, 22))
    fake(monkeypatch)
    assert run_cli("dream", "--catch-up")[0] == 0
    static = serve.Site(
        lb,
        now=lambda: datetime(2026, 6, 22, 12, tzinfo=UTC),
        href=lambda path: f"../{path[5:]}.html" if serve.DAY_PATH.match(path) else None,
    )
    assert 'href="../2026-06-21.html#week"' in _page(static, "2026-06-15")
