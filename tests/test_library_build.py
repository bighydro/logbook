"""The Library built ahead of time (`library_build`, RFC 0047 §8): the doors and shelves written as
files beside the index, never in the record's folder, 0600; served as built, byte for byte the page
the server renders but for one sentence in the footer, without opening the index; today's Day always
rendered; a page no build wrote rendered once and kept; an act drops the pages it changed and asks for
a rebuild. On the Oslo persona's fortnight (`persona.py`), who does not exist."""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import UTC, datetime
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
        "/journeys?year=2025": page(["2024-12-01", "2026-02-02", ["draft"]]),
        "/journeys?year=2026": page(["2025-12-01", "2026-06-23", ["draft"]]),
        "/people?year=2024": page(None),
    }
    wanted = library_build._wanted_since
    june = ({"2026-06-15"}, {"note"})
    assert not wanted("/trips?year=2024", *june, built)
    assert wanted("/trips?year=2026", *june, built)
    assert wanted("/trips?year=2024", {"2024-03-01"}, {"note"}, built), "a backfill into the year"
    assert wanted("/trips?year=2025", {"2026-01-01"}, {"note"}, built), "the night after the year's last day"
    assert not wanted("/trips?year=2025", {"2026-01-05"}, {"note"}, built)
    assert wanted("/trips?year=2024", {"2027-01-02"}, {"note"}, built), "a new year: every pager names it"
    assert wanted("/trips?year=2023", *june, built), "a year no build wrote"
    assert not wanted("/journeys?year=2024", *june, built)
    assert wanted("/journeys?year=2024", {"2025-02-01"}, {"note"}, built), (
        "a journey that ran on past the year"
    )
    assert wanted("/journeys?year=2024", {"2026-06-15"}, {"draft"}, built), "a draft names any journey"
    assert wanted("/people?year=2024", *june, built), "a page that says nothing reads the whole record"


def test_the_trips_and_the_journeys_say_what_they_read(lb: Logbook) -> None:
    site = serve.Site(lb, now=lambda: JUNE)
    trips = site.respond("/trips", "year=2026")
    assert trips.reads is not None and trips.reads.first == "2026-06-08" and not trips.reads.kinds
    journeys = site.respond("/journeys", "year=2026")
    assert journeys.reads is not None and "draft" in journeys.reads.kinds
    assert site.respond("/people", "").reads is None, "the People page reads the whole record"
