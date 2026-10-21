"""The Library's Timeline (`/timeline`, `logbook.contrib.timeline_page`, RFC 0043 §11-12) on the demo
record: every zoom a page that fits a phone, carries no script and opens no connection; the day's track
drawn by the Day page's own function; proposed company never shown as confirmed; no number beside a
person's name on any page; the money slot held to the gate; the month, the year and all years read
once for the record as it stands; and `logbook show timeline --json` the very object a page is drawn
from."""

from __future__ import annotations

import contextlib
import html
import io
import json
import re
import shutil
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import phone_width
import pytest

from logbook import cli
from logbook.contrib import serve, timeline_page
from logbook.core import moments, people
from logbook.core.store import Logbook

DAYS, SEED = 30, 7
NOW = datetime(2026, 6, 21, 12, 0, tzinfo=UTC)  # the demo's last week
OFFICE_DAY, ABOARD_DAY = "2026-06-12", "2026-06-20"
PAGES = (
    "/timeline",
    f"/timeline/day/{OFFICE_DAY}",
    f"/timeline/day/{ABOARD_DAY}",
    "/timeline/day/2026-06-26",
    "/timeline/day/2026-06-03",  # a call with Ola at home
    "/timeline/week/2026-W25",
    "/timeline/month/2026-06",
    "/timeline/year/2026",
    "/timeline/life",
)
CLI_OF_PAGES = (  # `show timeline`'s options for each of `PAGES`, its text held to the same guard
    ("--day", "2026-06-21"),
    ("--day", OFFICE_DAY),
    ("--day", ABOARD_DAY),
    ("--day", "2026-06-26"),
    ("--day", "2026-06-03"),
    ("--week", "2026-W25"),
    ("--month", "2026-06"),
    ("--year", "2026"),
    ("--life",),
)
HREF = re.compile(r"""href\s*=\s*["']([^"']*)["']""", re.I)
TAG = re.compile(r"<[^>]+>")


@pytest.fixture(scope="module")
def demo(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    root = tmp_path_factory.mktemp("timeline-page") / "Demo"
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("LOGBOOK_HOME", str(root))
        with contextlib.redirect_stdout(io.StringIO()):
            cli.main(["demo", "--days", str(DAYS), "--seed", str(SEED), "--out", str(root)])
    return Logbook(root)


def _site(lb: Logbook, tiers: tuple[int, ...] | None = None) -> serve.Site:
    return serve.Site(lb, now=lambda: NOW, tiers=tiers)


def _text(page: str) -> str:
    main = page[page.index("<main>") : page.index("</main>")]
    return " ".join(html.unescape(TAG.sub(" ", main)).split())


@pytest.mark.parametrize("path", PAGES)
def test_every_zoom_is_a_page_with_no_script_that_fits_a_phone(demo: Logbook, path: str) -> None:
    response = _site(demo).respond(path)
    assert response.status == 200, response.body[:300]
    page = response.body.decode("utf-8")
    assert "<script" not in page.lower() and "script-src" not in response.csp
    assert response.csp.startswith("default-src 'none'")
    assert all(h.startswith("/") and not h.startswith("//") for h in HREF.findall(page)), "links stay home"
    assert "@import" not in page and "url(" not in page, "nothing fetched"
    assert phone_width.problems(page) == [], path
    assert phone_width.phone_breakpoints(phone_width.parse(page)[1]), path
    assert "nothing read above tier" in page


@pytest.mark.parametrize("path", PAGES)
def test_a_timeline_page_opens_no_connection(demo: Logbook, path: str, no_network: list[str]) -> None:
    assert _site(demo).respond(path).status == 200
    assert no_network == [], f"{path} tried to connect: {no_network}"


def test_the_zooms_are_links_and_the_one_shown_is_not(demo: Logbook) -> None:
    page = _site(demo).respond(f"/timeline/day/{OFFICE_DAY}").body.decode("utf-8")
    links = set(HREF.findall(page))
    assert {
        "/timeline/week/2026-W24",
        "/timeline/month/2026-06",
        "/timeline/year/2026",
        "/timeline/life",
        "/timeline/day/2026-06-11",
        "/timeline/day/2026-06-13",
        f"/day/{OFFICE_DAY}",
    } <= links
    assert "<b>day</b>" in page and f"/timeline/day/{OFFICE_DAY}" not in links
    assert '<a href="/timeline">timeline</a>' in page  # the navigation names it
    assert "/timeline" in HREF.findall(_site(demo).respond("/").body.decode("utf-8"))


def test_the_map_s_place_holds_the_day_s_track_as_the_day_page_draws_it(demo: Logbook) -> None:
    site = _site(demo)
    page = site.respond(f"/timeline/day/{OFFICE_DAY}").body.decode("utf-8")
    day = site.respond(f"/day/{OFFICE_DAY}").body.decode("utf-8")
    track = re.search(r'<svg class="track".*?</svg>', day, re.S)
    assert track is not None and track.group(0) in page
    assert page.index(timeline_page.MAP_LATER) < page.index('<section class="list">')  # the map first


def test_a_moment_folds_to_one_line_and_opens_to_its_detail(demo: Logbook) -> None:
    page = _site(demo).respond(f"/timeline/day/{OFFICE_DAY}").body.decode("utf-8")
    summary = re.search(r"<summary>(.*?)</summary>", page[page.index("Office") - 200 :], re.S)
    assert summary is not None
    line = _text(f"<main>{summary.group(1)}</main>")
    assert line == (  # the people last, after the word `with`: no number stands beside a name
        "Office · 07:50\u201317:25 · 1 conversation · 1 mail thread · paid Havnekiosken"
        " · with Per Hansen, Liv Berg"
    )
    detail = _text(page)
    for said in ("Mooring for the week", "Release sync", "Ola Nordmann · whatsapp"):
        assert said in detail, said
    assert "Havnekiosken -119.00 NOK" in detail


def test_proposed_company_is_pencil_and_never_confirmed(demo: Logbook) -> None:
    page = _site(demo).respond(f"/timeline/day/{ABOARD_DAY}").body.decode("utf-8")
    assert "<dt>with</dt>" not in page  # nobody confirmed aboard that day
    proposed = re.search(r"<dt>proposed</dt><dd>(.*?)</dd>", page, re.S)
    assert proposed is not None and 'class="pencil"' in proposed.group(1)
    assert "Ola Nordmann? (face on photos)" in html.unescape(proposed.group(1))
    assert "Ola Nordmann?" in _text(page)


BESIDE = r"[\s(:×x#·,]*"  # what may stand between a name and a number and still be beside it


def _beside(name: str) -> re.Pattern[str]:
    """A digit before `name`, or after it (a proposed name's `?` aside), with nothing between but
    `BESIDE`: a space, a bracket, a colon, a times sign, a hash, the middle dot, a comma."""
    named = re.escape(name)
    return re.compile(rf"(\d{BESIDE}{named})|({named}\??{BESIDE}\d)")


def test_the_guard_catches_a_number_beside_a_name() -> None:
    """The guard below is only as good as its pattern: each of these must fail it."""
    for said in (
        "Ola Nordmann 3",
        "Ola Nordmann (12)",
        "Ola Nordmann: 4 days",
        "Ola Nordmann × 2",
        "Ola Nordmann #1",
        "Office · 07:50\u201317:25 · Ola Nordmann · 1 conversation",
        "Ola Nordmann, 2 photos",
        "Ola Nordmann? 2",
        "3 · Ola Nordmann",
        "07:50\u201317:25 · Ola Nordmann",
        "with Kari Nordmann, 12 min",
    ):
        names = ("Ola Nordmann", "Kari Nordmann")
        assert any(_beside(name).search(said) for name in names), said
    for said in (
        "Office · 07:50\u201317:25 · 1 conversation · with Ola Nordmann, Kari Nordmann?",
        "Kari Nordmann · iMessage",
        "Ola Nordmann? (face on photos)",
    ):
        assert not any(_beside(name).search(said) for name in ("Ola Nordmann", "Kari Nordmann")), said


def test_no_number_stands_beside_a_person_s_name_on_any_zoom(
    demo: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """VISION: no metrics near people. For every person the record names, nowhere on any zoom, on
    the page or in `show timeline`'s text, is a digit beside the name (`_beside`)."""
    names = [p.name for p in people.directory(demo).known.values()]
    assert "Ola Nordmann" in names
    site = _site(demo)
    monkeypatch.setenv("LOGBOOK_HOME", str(demo.root))
    for path, args in zip(PAGES, CLI_OF_PAGES, strict=True):
        said = _text(site.respond(path).body.decode("utf-8"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cli.main(["show", "timeline", *args])
        for text in (said, out.getvalue()):
            for name in names:
                found = _beside(name).search(text)
                assert found is None, (path, name, found)


def test_a_gate_without_tier_three_shows_no_payment(demo: Logbook) -> None:
    whole = _text(_site(demo).respond(f"/timeline/day/{OFFICE_DAY}").body.decode("utf-8"))
    held = _text(_site(demo, (0, 1, 2)).respond(f"/timeline/day/{OFFICE_DAY}").body.decode("utf-8"))
    assert "Havnekiosken" in whole and "paid" in whole
    assert "Havnekiosken" not in held and "paid" not in held and "payment" not in held
    assert "nothing read above tier 2" in held
    gap = _text(_site(demo).respond("/timeline/day/2026-07-15").body.decode("utf-8"))
    assert "No payment source covers this day; the last day one covers is 2026-06-" in gap
    held_gap = _site(demo, (0, 1, 2)).respond("/timeline/day/2026-07-15").body.decode("utf-8")
    assert "No payment source" not in _text(held_gap)


def test_a_key_that_is_not_one_is_a_400_and_a_path_that_is_none_a_404(demo: Logbook) -> None:
    site = _site(demo)
    assert site.respond("/timeline/day/2026-13-01").status == 400
    assert site.respond("/timeline/week/2026-W60").status == 400
    assert site.respond("/timeline/month/2026-13").status == 400
    assert site.respond("/timeline/someday").status == 404


def test_the_month_the_year_and_all_years_are_read_once_for_the_record_as_it_stands(
    demo: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    site = _site(demo)
    calls: list[str] = []
    real = moments.read

    def counted(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(str(args[1]))
        return real(*args, **kwargs)

    monkeypatch.setattr(moments, "read", counted)
    for path in ("/timeline/month/2026-06", "/timeline/year/2026", "/timeline/life") * 3:
        assert site.respond(path).status == 200
    assert calls == ["month", "year", "life"]


def _cli_json(lb: Logbook, monkeypatch: pytest.MonkeyPatch, *args: str) -> dict[str, Any]:
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["show", "timeline", *args, "--json"])
    found: dict[str, Any] = json.loads(out.getvalue())
    return found


@pytest.mark.parametrize(
    ("args", "zoom", "key"),
    [
        (("--day", OFFICE_DAY), "day", OFFICE_DAY),
        (("--week", "2026-W25"), "week", "2026-W25"),
        (("--month", "2026-06"), "month", "2026-06"),
        (("--year", "2026"), "year", "2026"),
        (("--life",), "life", None),
    ],
)
def test_show_timeline_json_is_the_object_the_page_is_drawn_from(
    demo: Logbook, monkeypatch: pytest.MonkeyPatch, args: tuple[str, ...], zoom: str, key: str | None
) -> None:
    drawn: list[dict[str, Any]] = []
    real = moments.read

    def kept(*a: Any, **k: Any) -> dict[str, Any]:
        found = real(*a, **k)
        drawn.append(found)
        return found

    printed = _cli_json(demo, monkeypatch, *args)
    monkeypatch.setattr(moments, "read", kept)
    path = f"/timeline/{zoom}" + (f"/{key}" if key else "")
    assert _site(demo).respond(path).status == 200
    assert drawn == [printed]
    # and what the page says is in it: each moment's summary, each day, each place
    page = _text(_site(demo).respond(path).body.decode("utf-8"))
    if zoom == "day":
        for item in printed["items"]:
            assert " ".join(moments.item_text(item).split()) in page
    elif zoom == "life":
        for place in printed["places"]:
            assert moments.place_text(place) in page
        for vessel in printed["vessels"]:
            assert moments.vessel_text(vessel) in page
    elif zoom == "week":
        for d in printed["days"]:
            assert f"{d['weekday'][:3]} {d['day']} · night {d['night']['class']}" in page
    else:
        assert moments.counts_text(printed["nights"]) in page


def test_show_timeline_takes_one_zoom(demo: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(demo.root))
    err = io.StringIO()
    with contextlib.redirect_stderr(err), pytest.raises(SystemExit) as stop:
        cli.main(["show", "timeline", "--week", "2026-W25", "--life"])
    assert stop.value.code == 2 and "one zoom at a time" in err.getvalue()
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(["show", "timeline", "--day", OFFICE_DAY])
    assert (
        "Office · 07:50\u201317:25 · 1 conversation · 1 mail thread · paid Havnekiosken · with Per Hansen"
        in (out.getvalue())
    )


ANCHOR = re.compile(r"<a\b[^>]*>")
TARGETS = re.compile(r'class="(?:tap|chip [a-z]+|cell [a-z]*|month)"')
ROWS_OF_TARGETS = re.compile(r'<p class="(?:zooms|pager)">.*?</p>', re.S)  # their links are 44 px by the row


@pytest.mark.parametrize("path", PAGES)
def test_every_link_of_a_zoom_is_a_44_px_target(demo: Logbook, path: str) -> None:
    page = _site(demo).respond(path).body.decode("utf-8")
    main = ROWS_OF_TARGETS.sub("", page[page.index("<main>") : page.index("</main>")])
    small = [a for a in ANCHOR.findall(main) if not TARGETS.search(a)]
    assert small == [], (path, small[:3])
    assert "a.tap{display:inline-block;min-height:2.75rem" in page


def test_every_link_of_the_year_and_all_years_answers(demo: Logbook) -> None:
    site = _site(demo)
    for path in (
        "/timeline/year/2026",
        "/timeline/life",
        "/timeline/week/2026-W25",
        "/timeline/month/2026-06",
    ):
        page = site.respond(path).body.decode("utf-8")
        main = page[page.index("<main>") : page.index("</main>")]  # the navigation's /today is a redirect
        for link in sorted(set(HREF.findall(main))):
            target, _, query = html.unescape(link).partition("?")
            assert site.respond(target, query).status == 200, (path, link)


def test_a_gate_without_the_track_places_no_night_on_the_month_or_all_years(demo: Logbook) -> None:
    site = _site(demo, (0, 2, 3))
    month = _text(site.respond("/timeline/month/2026-06").body.decode("utf-8"))
    assert "no nights" in month and "home 18" not in month
    life = _text(site.respond("/timeline/life").body.decode("utf-8"))
    assert "Home" not in life and "Nordlys" not in life


def test_all_years_is_built_once_after_a_move_and_says_so_meanwhile(
    demo: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's answer on all years: never rebuilt on every move of the head. The first open after
    a move starts one build and, while it runs, the page says so in one line; asked again meanwhile,
    no second build; done, it is kept until the record moves again, and the next open builds anew."""
    shutil.copytree(demo.root, tmp_path / "copy")
    lb = Logbook(tmp_path / "copy")
    gate, built = threading.Event(), []
    real = moments.read

    def slow(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if args[1] == "life":
            built.append(args[1])
            assert gate.wait(60), "the test never let the build finish"
        return real(*args, **kwargs)

    monkeypatch.setattr(moments, "read", slow)
    monkeypatch.setattr(timeline_page, "LIFE_WAIT_S", 0.05)  # a big record's build: longer than the wait
    site = _site(lb)

    def life() -> str:
        response = site.respond("/timeline/life")
        assert response.status == 200
        return _text(response.body.decode("utf-8"))

    def when_built() -> str:
        for _ in range(600):
            said = life()
            if timeline_page.BUILDING not in said:
                return said
            time.sleep(0.05)
        raise AssertionError("all years was never built")

    first = life()
    assert timeline_page.BUILDING in first and "Cabin" not in first
    page = site.respond("/timeline/life").body.decode("utf-8")  # the one line: a page like any other
    assert "<script" not in page and phone_width.problems(page) == [] and "<meta http-equiv" not in page
    assert timeline_page.BUILDING in life() and built == ["life"]  # asked again while it builds: one build
    gate.set()
    done = when_built()
    assert "Cabin · 1 visit since 2026" in done and built == ["life"]
    assert life() == done and built == ["life"]  # kept: read again, nothing built
    gate.clear()
    lb.append(
        at="2026-06-30T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "One more line, as a sync would write it."},
    )
    assert timeline_page.BUILDING in life() and built == ["life", "life"]  # the head moved: built anew, once
    gate.set()
    assert "Cabin · 1 visit since 2026" in when_built() and built == ["life", "life"]
