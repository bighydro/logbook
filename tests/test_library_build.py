"""The Library built ahead of time (`library_build`, RFC 0047 §8): the doors and shelves written as
files beside the index, never in the record's folder, 0600; served as built, byte for byte the page
the server renders but for one sentence in the footer, without opening the index; today's Day always
rendered; a page no build wrote rendered once and kept; an act drops the pages it changed and asks for
a rebuild. On the Oslo persona's fortnight (`persona.py`), who does not exist."""

from __future__ import annotations

import json
import os
import shutil
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from persona import persona_record

from logbook import cli
from logbook.contrib import library_build, serve
from logbook.core import index as index_module
from logbook.core.store import Logbook

JUNE = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)  # the fortnight's last day, the morning
TODAY = "2026-06-21"
WEDNESDAY = "2026-06-17"
LOOPBACK = "127.0.0.1"


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return persona_record(tmp_path, monkeypatch)


def _built(lb: Logbook) -> tuple[library_build.Library, serve.Site, library_build.Result]:
    library = library_build.Library(lb, now=lambda: JUNE)
    site = serve.Site(lb, now=lambda: JUNE)
    return library, site, library_build.build(lb, site, library)


def _served(lb: Logbook, library: library_build.Library) -> serve.Site:
    return serve.Site(lb, now=lambda: JUNE, library=library)


def test_a_build_writes_every_door_beside_the_index_never_in_the_record(lb: Logbook) -> None:
    library, _site, result = _built(lb)
    pages = library.pages()
    assert set(library_build.DOORS) <= set(pages), set(library_build.DOORS) - set(pages)
    assert result.failed == {} and result.pages == len(pages)
    assert library.folder.parent == lb.index_path.parent, "beside the index, in the cache folder"
    assert lb.root not in library.folder.parents and library.folder != lb.root
    assert not any(p.name == library_build.FOLDER for p in lb.root.rglob("*")), "nothing in the record"
    for target, page in pages.items():
        assert page.file == library_build.file_name(target)
        assert "/" not in page.file and (library.folder / page.file).is_file()
    days = [t for t in pages if t.startswith("/day/")]
    assert f"/day/{TODAY}" not in pages, "today's Day is always rendered"
    assert "/day/2026-06-20" in days and "/day/2026-06-08" in days


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no POSIX modes; the folder is the user's")
def test_the_build_is_the_record_s_user_s_alone(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    assert library.folder.stat().st_mode & 0o777 == 0o700
    for f in library.folder.iterdir():
        assert f.stat().st_mode & 0o777 == 0o600, f.name


def test_a_build_writes_nothing_to_the_record(lb: Logbook) -> None:
    seq, head = lb.meta["seq"], lb.meta["head"]
    _built(lb)
    lb = Logbook(lb.root)
    assert (lb.meta["seq"], lb.meta["head"]) == (seq, head), "no crossing line: the build is not an export"


def test_a_built_page_is_the_server_s_page_and_says_when_it_was_built(lb: Logbook) -> None:
    library, site, _result = _built(lb)
    for target in ("/", "/people", "/days", f"/day/{WEDNESDAY}"):
        path, _, query = target.partition("?")
        page, body = library.page(target) or pytest.fail(target)
        assert body == library_build.stamped(site.respond(path, query).body, "12:00"), target
        assert b'<span class="built">built 12:00</span></footer>' in body
        assert page.status == 200 and page.head == lb.meta["head"]


def test_a_built_page_is_answered_without_opening_the_index(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, _site, _result = _built(lb)
    served = _served(lb, library)

    def opened(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a built page opened the index")

    monkeypatch.setattr(index_module.Index, "open", opened)
    for target in ("/", "/people", "/journeys", "/world", "/gaps", f"/day/{WEDNESDAY}"):
        path, _, query = target.partition("?")
        response = served.respond(path, query)
        assert response.status == 200 and b"built 12:00" in response.body, target
    csp = served.respond("/world").csp
    assert "script-src" in csp, "a page keeps the policy it was answered with"


def test_the_build_is_served_as_built_after_the_head_moves_but_today_is_live(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    served = _served(lb, library)
    before = served.respond("/people").body
    lb.append(
        at="2026-06-21T07:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "The harbour office opens at nine."},
    )
    assert served.respond("/people").body == before, "static: as of the build"
    today = served.respond(f"/day/{TODAY}").body.decode("utf-8")
    assert "The harbour office opens at nine." in today and "built 12:00" not in today


def test_a_page_no_build_wrote_is_rendered_once_and_kept(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    served = _served(lb, library)
    target = "/days?from=2026-06-09&to=2026-06-11"
    assert target not in library.pages()
    first = served.respond("/days", "from=2026-06-09&to=2026-06-11")
    assert first.status == 200
    kept = library.pages()[target]
    assert kept.asked
    again = served.respond("/days", "from=2026-06-09&to=2026-06-11")
    assert again.body == library_build.stamped(first.body, "12:00")
    rebuilt = library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    assert target in library.pages() and rebuilt.failed == {}, "the next build builds it again"


def test_an_unchanged_page_is_a_304_by_its_built_tag(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    served = _served(lb, library)
    tag = served.respond("/people").etag
    assert tag is not None and tag.startswith('"b-')
    assert served.respond("/people", "", tag).status == 304


def test_an_act_drops_the_page_it_returns_to_and_asks_for_a_rebuild(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    asked: list[str] = []
    served = serve.Site(lb, now=lambda: JUNE, library=library, on_act=lambda: asked.append("rebuild"))
    day = "2026-06-20"
    assert f"/day/{day}" in library.pages()
    form = {"act": "reflect", "text": "We sailed home before the wind turned."}
    answered = served.write(f"/day/{day}/reflect", form, LOOPBACK, None)
    assert answered.status == 303
    assert f"/day/{day}" not in library.pages() and "/" not in library.pages()
    assert "/people" in library.pages(), "the rest is the rebuild's, in the background"
    assert asked == ["rebuild"]
    page = served.respond(f"/day/{day}").body.decode("utf-8")
    assert "We sailed home before the wind turned." in page, "the owner sees what was written"


def test_a_refused_act_drops_nothing(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    served = serve.Site(lb, now=lambda: JUNE, library=library, on_act=lambda: pytest.fail("no rebuild"))
    before = set(library.pages())
    refused = served.write("/day/2026-06-20/reflect", {"act": "reflect", "text": "x"}, "10.0.0.5", None)
    assert refused.status == 403
    assert set(library.pages()) == before


def test_a_form_refused_as_older_than_the_record_drops_its_page_so_the_reload_is_current(lb: Logbook) -> None:
    """A built Day carries its forms as the day was at the build; a sync since may make one older than
    the record (409). The reload must not be the same built page again."""
    library, _site, _result = _built(lb)
    served = serve.Site(lb, now=lambda: JUNE, library=library, on_act=lambda: pytest.fail("nothing written"))
    day = "2026-06-19"
    form = {"act": "reflect", "text": "Said aloud.", "dictation": "0190a1b2-0000-7000-8000-000000000000"}
    refused = served.write(f"/day/{day}/reflect", form, LOOPBACK, None)
    assert refused.status == 409
    assert f"/day/{day}" not in library.pages() and "/" in library.pages()
    assert "built 12:00" not in served.respond(f"/day/{day}").body.decode("utf-8")
    assert library_build.touched(
        ["/people", "/people?year=2026", "/people/x", "/peoplex"], "/people/review", 409, "", {}
    ) == [
        "/people",
        "/people?year=2026",
        "/people/x",
    ]


def test_a_full_build_removes_what_it_no_longer_names(lb: Logbook) -> None:
    library, site, _result = _built(lb)
    stray = "/days?from=2026-06-01&to=2026-06-02"
    library.put(stray, site.respond("/days", "from=2026-06-01&to=2026-06-02"), "x")
    page = library.pages()[stray]
    library_build.build(lb, site, library, full=True)
    assert stray not in library.pages() and not (library.folder / page.file).exists()


def test_two_builds_never_run_at_once_and_a_dead_builder_s_lock_is_taken_over(lb: Logbook) -> None:
    library = library_build.Library(lb, now=lambda: JUNE)
    with library.building(), pytest.raises(library_build.Busy):
        library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    lock = library.folder / library_build.LOCK
    lock.write_text(json.dumps({"pid": 2**22 + 12345, "since": "2026-06-21T03:00:00Z"}), encoding="utf-8")
    result = library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    assert result.pages > 0 and not lock.exists()


def test_the_rebuilder_builds_once_for_many_acts(lb: Logbook) -> None:
    library = library_build.Library(lb, now=lambda: JUNE)
    site = serve.Site(lb, now=lambda: JUNE, library=library)
    rebuilder = library_build.Rebuilder(lb, site, library).start()
    try:
        for _ in range(5):
            rebuilder.kick()
        deadline = time.monotonic() + 120
        while rebuilder.builds == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert rebuilder.builds >= 1 and "/" in library.pages()
        time.sleep(0.2)
        assert rebuilder.builds <= 2, "five asks while one build ran: at most one more"
    finally:
        rebuilder.stop()


def test_serve_build_builds_and_says_so_in_one_line(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["serve", "--build"])
    out = capsys.readouterr().out
    assert out.startswith("library: ") and " pages, " in out and " written, " in out
    assert library_build.Library(lb).built()["full"] is True


def test_the_server_answers_from_the_build_over_http(lb: Logbook) -> None:
    import http.client

    library, _site, _result = _built(lb)
    server = serve.Server(0, _served(lb, library))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        conn = http.client.HTTPConnection(LOOPBACK, server.server_address[1], timeout=10)
        conn.request("GET", "/people")
        answer = conn.getresponse()
        body = answer.read()
        assert answer.status == 200 and b"built 12:00" in body
        assert answer.getheader("ETag", "").startswith('"b-')
    finally:
        server.shutdown()
        server.server_close()
    assert os.environ.get("LOGBOOK_HOME")  # the conftest's, never the shell's


def test_a_build_names_its_pages_a_few_times_not_once_a_page(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(library_build, "SAVE_EVERY", 10)
    library = library_build.Library(lb, now=lambda: JUNE)
    saved: list[int] = []
    real = library_build.Library._save

    def counted(self: library_build.Library, pages: Any, built: Any) -> None:
        saved.append(len(pages))
        real(self, pages, built)

    monkeypatch.setattr(library_build.Library, "_save", counted)
    result = library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    assert result.pages > library_build.SAVE_EVERY
    assert len(saved) <= result.pages // library_build.SAVE_EVERY + 3, saved
    assert library_build.Library(lb).pages().keys() == library.pages().keys(), (
        "what was saved is what was built"
    )


# -- incremental: what the lines since the last build touched ---------------------------------------------


def _note(lb: Logbook, at: str, text: str) -> None:
    lb.append(at=at, source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": text})


def test_a_build_after_a_day_renders_what_the_day_touched_and_every_door(lb: Logbook) -> None:
    library, _site, _first = _built(lb)
    before = library.pages()
    assert library.built()["full"] is True
    _note(lb, "2026-06-15T10:00:00Z", "The boat is back in the water.")
    second = library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    built = library.built()
    assert built["full"] is False and second.pages < len(before)
    after = library.pages()
    for day in ("2026-06-15", "2026-06-14"):  # the day, and the day before (its night)
        assert (
            after[f"/day/{day}"].at != before[f"/day/{day}"].at
            or after[f"/day/{day}"].etag != before[f"/day/{day}"].etag
        )
    assert after["/day/2026-06-10"].at == before["/day/2026-06-10"].at, (
        "a day nothing touched is left as built"
    )
    page = library.page("/day/2026-06-15")
    assert page is not None and b"The boat is back in the water." in page[1]
    for door in library_build.DOORS:
        assert door in after, door
    assert set(after) >= set(before), "an incremental build removes nothing"


def test_nothing_appended_renders_the_doors_and_no_day(lb: Logbook) -> None:
    library, _site, _first = _built(lb)
    before = library.pages()
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    after = library.pages()
    assert all(after[t].at == before[t].at for t in before if t.startswith("/day/"))
    assert library.built()["full"] is False


def test_a_resolution_a_setting_or_full_builds_every_page(lb: Logbook) -> None:
    library, _site, _first = _built(lb)
    lb.append(
        at="2026-06-20T09:00:00Z",
        source="manual",
        kind="resolution",
        tier=2,
        payload={
            "schema": "resolution/v1",
            "ref": {"kind": "email", "value": "new.friend@example.org"},
            "entity": {"type": "person", "id": "019ea000-0000-7000-8000-00000000f00d", "registry": "logbook"},
            "label": "Nora Nordmann",
            "method": "owner",
        },
    )
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    assert library.built()["full"] is True, "who is who changed: every page"
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    assert library.built()["full"] is False
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "stays.json").write_text('{"stay_min_s": 900}', encoding="utf-8")
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    assert library.built()["full"] is True, "a setting changed: every page"
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library, full=True)
    assert library.built()["full"] is True


def test_serve_build_full_says_every_page(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(["serve", "--build"])
    assert "(every page;" in capsys.readouterr().out
    cli.main(["serve", "--build"])
    assert "(what changed since the last;" in capsys.readouterr().out
    cli.main(["serve", "--build", "--full"])
    assert "(every page;" in capsys.readouterr().out


def test_a_build_names_its_slowest_pages(lb: Logbook, capsys: pytest.CaptureFixture[str]) -> None:
    library, _site, result = _built(lb)
    slowest = library.built()["slowest"]
    assert 0 < len(slowest) <= library_build.SLOWEST
    assert [s for _t, s in slowest] == sorted((s for _t, s in slowest), reverse=True)
    assert all(t in library.pages() for t, _s in slowest)
    assert result.slowest == [(t, s) for t, s in slowest]
    cli.main(["serve", "--build"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("library: ") and lines[1].startswith("  slowest: ")


def test_a_page_that_says_what_it_read_is_rendered_again_only_for_a_line_of_that() -> None:
    def page(reads: list[Any] | None) -> library_build.Page:
        return library_build.Page("f.html", 200, None, None, "e", "2026-06-21T10:00:00Z", "h", reads=reads)

    built = {
        "/trips?year=2024": page(["2024-01-01", "2025-01-02", []]),
        "/trips?year=2025": page(["2025-01-01", "2026-01-02", []]),
        "/trips?year=2026": page(["2026-01-01", "2026-06-23", []]),
        "/journeys?year=2024": page(["2023-12-01", "2025-02-14", ["draft"]]),
        "/journeys": page(["2025-12-01", "2026-06-23", ["draft"]]),  # the door: this year's
        "/people?year=2024": page(None),
    }

    def wanted(target: str, days: set[str], kinds: set[str], new_years: bool = False) -> bool:
        return library_build._wanted_since(target, days, kinds, built, new_years)

    june = ({"2026-06-15"}, {"note"})
    assert not wanted("/trips?year=2024", *june)
    assert wanted("/trips?year=2026", *june)
    assert wanted("/trips?year=2024", {"2024-03-01"}, {"note"}), "a backfill into the year"
    assert wanted("/trips?year=2025", {"2026-01-01"}, {"note"}), "the night after the year's last day"
    assert not wanted("/trips?year=2025", {"2026-01-05"}, {"note"})
    assert wanted("/trips?year=2024", {"2027-01-02"}, {"location"}, True), "a new year: every pager names it"
    assert wanted("/trips?year=2023", *june), "a year no build wrote"
    assert not wanted("/journeys?year=2024", *june), "this year's journeys are the door's, not a new year"
    assert wanted("/journeys?year=2024", {"2025-02-01"}, {"note"}), "a journey that ran on past the year"
    assert wanted("/journeys?year=2024", {"2026-06-15"}, {"draft"}), "a draft names any journey"
    assert wanted("/people?year=2024", *june), "a page that says nothing reads the whole record"
    assert not wanted("/trips?year=2024", {"2027-01-02"}, {"event"}), "a meeting booked ahead names no year"


def test_the_trips_and_the_journeys_say_what_they_read(lb: Logbook) -> None:
    site = serve.Site(lb, now=lambda: JUNE)
    trips = site.respond("/trips", "year=2026")
    assert trips.reads is not None and trips.reads.first == "2026-06-08" and not trips.reads.kinds
    journeys = site.respond("/journeys", "year=2026")
    assert journeys.reads is not None and "draft" in journeys.reads.kinds
    assert site.respond("/people", "").reads is None, "the People page reads the whole record"


def test_a_build_on_workers_writes_the_pages_one_process_writes(lb: Logbook, tmp_path: Path) -> None:
    one = library_build.Library(lb, now=lambda: JUNE)
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), one)
    pages = {t: one.page(t) for t in one.pages()}
    shutil.rmtree(library_build.folder_of(lb))
    two = library_build.Library(lb, now=lambda: JUNE)
    result = library_build.build(lb, serve.Site(lb, now=lambda: JUNE), two, workers=2)
    assert result.failed == {}
    assert set(two.pages()) == set(pages)
    for target, (page, body) in ((t, two.page(t)) for t in two.pages()):  # type: ignore[misc]
        before, body_before = pages[target]  # type: ignore[misc]
        assert body == body_before, target
        assert (page.status, page.reads, page.etag) == (before.status, before.reads, before.etag), target


def test_a_small_record_builds_in_one_process_and_the_setting_says_how_many(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert library_build.workers_default(lb) == 1
    monkeypatch.setenv(library_build.WORKERS_ENV, "3")
    assert library_build.workers_default(lb) == 3
    monkeypatch.setattr(library_build, "WORKERS_FROM", 0)
    monkeypatch.delenv(library_build.WORKERS_ENV)
    assert 1 <= library_build.workers_default(lb) <= library_build.WORKERS_MOST


def _serve_given(monkeypatch: pytest.MonkeyPatch, *args: str) -> dict[str, Any]:
    """What `logbook serve <args>` hands the server: `serve.serve` caught, nothing bound."""
    given: dict[str, Any] = {}
    monkeypatch.setattr(serve, "serve", lambda lb, **kw: given.update(kw))
    cli.main(["serve", *args])
    return given


def test_serve_is_live_by_default_with_no_limit(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    given = _serve_given(monkeypatch)
    assert given["built"] is False, "live by default: built pages are a lab"
    assert given["limit_s"] == float("inf"), "live, a page is read to its end"
    assert _serve_given(monkeypatch, "--live")["built"] is False, "--live is still accepted"
    assert _serve_given(monkeypatch, "--live", "--limit", "0")["limit_s"] == float("inf")


def test_serve_built_answers_from_the_build_under_the_limit(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    given = _serve_given(monkeypatch, "--built")
    assert given["built"] is True and given["limit_s"] == serve.LIMIT_S == 15.0
    assert _serve_given(monkeypatch, "--built", "--limit", "0")["limit_s"] == float("inf")


def test_serve_live_takes_a_limit_when_given(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    given = _serve_given(monkeypatch, "--live", "--limit", "15")
    assert given["built"] is False and given["limit_s"] == 15.0


# -- the lab's review (#382's list, after v1.0) -----------------------------------------------------------


def _wait_for(rebuilder: library_build.Rebuilder, builds: int) -> None:
    deadline = time.monotonic() + 120
    while rebuilder.builds < builds and time.monotonic() < deadline:
        time.sleep(0.05)
    assert rebuilder.builds >= builds, "the rebuild did not finish"


def test_the_rebuilder_renders_each_page_anew_on_a_site_of_its_own(lb: Logbook) -> None:
    """The server's own site answers from the build: a rebuild through it would keep the built bytes
    again, with a second "built" note, and mark them asked. Its own site, with no build, renders."""
    library, _site, _result = _built(lb)
    asked_before = {t for t, p in library.pages().items() if p.asked}
    served = _served(lb, library)
    _note(lb, "2026-06-20T09:00:00Z", "Kari Nordmann rowed out to the skerry.")
    rebuilder = library_build.Rebuilder(lb, served, library).start()
    try:
        rebuilder.kick()
        _wait_for(rebuilder, 1)
    finally:
        rebuilder.stop()
    page = library.page("/day/2026-06-20") or pytest.fail("the Day is built")
    assert b"Kari Nordmann rowed out to the skerry." in page[1], "rendered anew, not the build kept again"
    for target, (found, body) in ((t, library.page(t) or pytest.fail(t)) for t in library.pages()):
        assert body.count(b'class="built"') <= 1, f"{target}: one built note, never two"
        assert found.asked == (target in asked_before), f"{target}: a rebuild marks no page asked"
    assert rebuilder.site is served and rebuilder.site.library is library, "the server's site is its own"


def test_a_built_page_at_an_older_head_is_served_and_asks_for_one_rebuild_of_that_head(lb: Logbook) -> None:
    """A CLI act or a sync moves the head under a running server: the built page is still answered (its
    footer says when it was built) and one rebuild of the new head is asked for, however many pages are
    asked for meanwhile."""
    library, _site, _result = _built(lb)
    stale: list[str] = []
    served = serve.Site(lb, now=lambda: JUNE, library=library, on_stale=stale.append)
    assert b"built 12:00" in served.respond("/people").body
    assert stale == [], "the build is at the record's head: nothing to ask"
    _note(lb, "2026-06-19T09:00:00Z", "Ola Nordmann mended the jetty.")
    head = str(Logbook(lb.root).meta["head"])
    for door in ("/people", "/days", "/people"):
        answered = served.respond(door)
        assert answered.status == 200 and b"built 12:00" in answered.body, "the last built page, meanwhile"
    assert stale and set(stale) == {head}, "the page told the server which head it is older than"

    rebuilder = library_build.Rebuilder(lb, served, library)
    rebuilder.stale(str(library.built()["head"]))
    assert not rebuilder.wanted(), "the head the build is at: no rebuild"
    rebuilder.stale(head)
    rebuilder.stale(head)
    assert rebuilder.wanted() == 1, "one rebuild per head"
    rebuilder.start()
    try:
        _wait_for(rebuilder, 1)
        rebuilder.stale(head)  # asked again once it is built at that head: nothing more
        assert rebuilder.wanted() == 0 and rebuilder.builds == 1
    finally:
        rebuilder.stop()
    assert library.built()["head"] == head
    page = library.page("/day/2026-06-19") or pytest.fail("the Day is built")
    assert b"Ola Nordmann mended the jetty." in page[1]


def test_the_server_tells_its_rebuilder_of_a_page_older_than_the_head(lb: Logbook) -> None:
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE))
    server = serve.make_server(lb, port=0, built=True)
    try:
        assert server.rebuilder is not None
        assert server.site.on_stale == server.rebuilder.stale
        assert server.rebuilder.site is server.site
    finally:
        server.server_close()


def _held_by_another_process(library: library_build.Library) -> Path:
    """`building.lock` naming a live process that is not this one (this one's parent)."""
    lock = library.folder / library_build.LOCK
    lock.write_text(json.dumps({"pid": os.getppid(), "since": "2026-06-21T03:00:00Z"}), encoding="utf-8")
    return lock


def test_the_server_writes_pages_json_only_under_the_build_lock(lb: Logbook) -> None:
    """Another process building (the 06:00 close) holds the lock and writes `pages.json` whole at its
    end: the server's own additions and drops never write it meanwhile, so neither loses the other's.
    A drop is still kept in this process: the dropped page is rendered, never the build's."""
    library, _site, _result = _built(lb)
    lock = _held_by_another_process(library)
    manifest = library.folder / library_build.MANIFEST
    before = manifest.read_bytes()
    served = serve.Site(lb, now=lambda: JUNE, library=library, on_act=lambda: None)
    assert served.respond("/days", "from=2026-06-09&to=2026-06-11").status == 200
    day = "2026-06-20"
    form = {"act": "reflect", "text": "Per Hansen brought the charts back."}
    assert served.write(f"/day/{day}/reflect", form, LOOPBACK, None).status == 303
    assert manifest.read_bytes() == before, "pages.json written outside the build lock"
    page = served.respond(f"/day/{day}").body.decode("utf-8")
    assert "Per Hansen brought the charts back." in page and "built 12:00" not in page
    assert lock.exists(), "the other process's lock is left to it"
    lock.unlink()
    library.drop(["/gaps"])  # the lock free: taken for the write, and let go
    assert "/gaps" not in json.loads(manifest.read_bytes())["pages"] and not lock.exists()
    assert not list(library.folder.glob(".*.tmp")), "moved into place whole"


def test_a_drop_another_build_did_not_see_stays_dropped_after_it_writes_pages_json(lb: Logbook) -> None:
    library, site, _result = _built(lb)
    seq = int(lb.meta["seq"])  # what the other process's build read, begun before the act
    _note(lb, "2026-06-20T09:00:00Z", "The act the drops are for.")
    lock = _held_by_another_process(library)
    library.drop(["/people"])  # the lock another's: kept here only
    assert library.page("/people") is None
    lock.unlink()
    library.drop(["/days"])  # the lock free: written to pages.json, and kept here too
    # the other build, ending a while after the act on a clock of its own, writes the pages as it read them
    other = library_build.Library(lb, now=lambda: JUNE + timedelta(minutes=5))
    other.put("/people", site.respond("/people"), "x", seq=seq)
    other.put("/days", site.respond("/days"), "x", seq=seq)
    assert "/people" in other.pages() and "/days" in other.pages()
    assert library.page("/people") is None, "built before the act: still dropped here"
    assert library.page("/days") is None, "the same, whichever branch the drop took"
    later = int(Logbook(lb.root).meta["seq"])
    other.put("/people", site.respond("/people"), "y", seq=later)
    assert library.page("/people") is not None, "built after the act: served"


def test_a_built_page_records_the_tiers_it_was_built_at_and_serves_only_that_gate(lb: Logbook) -> None:
    library = library_build.Library(lb, now=lambda: JUNE)
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE, tiers=(1,)), library)
    assert library.built()["tiers"] == [1]
    assert all(p.tiers == [1] for p in library.pages().values())
    every = serve.Site(lb, now=lambda: JUNE, library=library)
    assert b"built 12:00" not in every.respond("/people").body, "a tier-1 page never answers every tier"
    assert library.pages()["/people"].tiers == [1], "and never kept over the gate it was built at"
    one = serve.Site(lb, now=lambda: JUNE, library=library, tiers=(1,))
    assert b"built 12:00" in one.respond("/people").body, "the gate it was built at"
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library)
    assert library.built()["full"] is True, "another gate: every page again"
    assert all(p.tiers is None for p in library.pages().values())
    assert b"built 12:00" in every.respond("/people").body
    assert b"built 12:00" not in one.respond("/people").body, "an every-tier page never answers tier 1"


def test_a_built_page_that_names_no_tiers_is_never_served(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    manifest = library.folder / library_build.MANIFEST
    data = json.loads(manifest.read_bytes())
    for page in data["pages"].values():
        del page["tiers"]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    assert b"built 12:00" not in _served(lb, library).respond("/people").body, "built before tiers were kept"


def test_a_build_of_a_few_pages_does_not_hide_that_the_rest_are_older_than_the_head(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    old = library.built()["head"]
    _note(lb, "2026-06-19T09:00:00Z", "Ines Nordmann painted the shed.")
    library_build.build(lb, serve.Site(lb, now=lambda: JUNE), library, only=["/gaps"])  # a page asked for
    assert library.built()["head"] == old, "the build's head is that of its last whole build"
    stale: list[str] = []
    served = serve.Site(lb, now=lambda: JUNE, library=library, on_stale=stale.append)
    assert b"built 12:00" in served.respond("/people").body
    assert stale == [str(Logbook(lb.root).meta["head"])]


def test_a_rebuild_that_failed_is_tried_again_for_the_same_head(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, _site, _result = _built(lb)
    _note(lb, "2026-06-19T09:00:00Z", "Per Hansen came by with coffee.")
    head = str(Logbook(lb.root).meta["head"])
    said: list[str] = []
    heard = threading.Event()

    def say(text: str) -> None:
        said.append(text)
        heard.set()

    def full_disk(*_args: Any, **_kwargs: Any) -> library_build.Result:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(library_build, "build", full_disk)
    rebuilder = library_build.Rebuilder(lb, _served(lb, library), library, say).start()
    try:
        rebuilder.stale(head)
        assert heard.wait(60) and "failed" in said[0]
        heard.clear()
        rebuilder.stale(head)
        assert heard.wait(60) and len(said) == 2, "the same head, tried again"
    finally:
        rebuilder.stop()


def test_the_build_lock_is_let_go_only_while_it_is_this_library_s(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    lock = library.folder / library_build.LOCK
    with library.building():
        lock.write_text(json.dumps({"pid": os.getppid()}), encoding="utf-8")  # taken over by another
    assert lock.exists(), "another process's lock is never removed"
    lock.unlink()
    lock.write_text("", encoding="utf-8")  # another process between creating it and naming itself
    with pytest.raises(library_build.Busy):
        library.save()
    assert lock.exists()


def test_a_lock_this_library_left_behind_is_taken_back(lb: Logbook) -> None:
    """Windows may refuse to remove the lock while another process reads it: the file stays, naming
    this process; the next write takes it back rather than calling itself busy for ever."""
    library, _site, _result = _built(lb)
    with library.building():
        held = (library.folder / library_build.LOCK).read_bytes()
    (library.folder / library_build.LOCK).write_bytes(held)
    library.save()
    with library.building():
        pass
    other = library_build.Library(lb, now=lambda: JUNE)
    (library.folder / library_build.LOCK).write_bytes(held)
    with pytest.raises(library_build.Busy):
        other.save()  # another Library of this process never takes it


def test_clearing_leaves_a_build_this_process_runs(lb: Logbook) -> None:
    library, _site, _result = _built(lb)
    with library.building():
        library_build.clear(lb)
        assert (library.folder / library_build.MANIFEST).exists()
