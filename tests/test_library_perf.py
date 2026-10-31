"""The Library on a record of many lines reads what a page needs through the index, once per head
(`docs/serve.md`, *Performance*). Counted, never timed: the lines read back from the files, the
passes over the owner's stays, the pairs the people review compares, the kinds read whole. The record
is `scripts/bench_library.py`'s synthetic ten years (the Oslo persona, addresses at example.org,
numbers in 07700 900xxx): 10,000 lines in the quick tier, 100,000 in the slow one."""

from __future__ import annotations

import contextlib
import importlib.util
import re
import sqlite3
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from logbook.contrib import people_review, serve
from logbook.core import index as index_module
from logbook.core import stays, store
from logbook.core.store import Logbook

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bench_library.py"
_spec = importlib.util.spec_from_file_location("bench_library", SCRIPT)
assert _spec is not None and _spec.loader is not None
bench: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)

SIZES = [pytest.param(10_000, id="10k"), pytest.param(100_000, id="100k", marks=pytest.mark.slow)]


class Reads:
    """What a request reads: lines from the files by (kind, source), the owner's segments folded, the
    review's pairs compared, the kinds read whole through `Index.by_kind`."""

    def __init__(self, mp: pytest.MonkeyPatch):
        self.lines: Counter[tuple[str, str]] = Counter()
        self.folds = 0
        self.pairs = 0
        self.whole: Counter[str] = Counter()
        read_line_at, fold, evidence = store.read_line_at, stays.fold, people_review.evidence
        by_kind = index_module.Index.by_kind

        def counted_line(fh: Any, offset: int) -> Any:
            line = read_line_at(fh, offset)
            self.lines[(str(line.get("kind")), str(line.get("source")))] += 1
            return line

        def counted_fold(segments: Any) -> Any:
            self.folds += 1
            return fold(segments)

        def counted_pair(*args: Any, **kwargs: Any) -> Any:
            self.pairs += 1
            return evidence(*args, **kwargs)

        def counted_kind(idx: Any, kind: str, *args: Any, **kwargs: Any) -> Any:
            self.whole[kind] += 1
            return by_kind(idx, kind, *args, **kwargs)

        def swept(*_args: Any, **_kwargs: Any) -> Iterator[Any]:
            raise AssertionError("a page swept the month files")

        mp.setattr(store, "read_line_at", counted_line)
        mp.setattr(stays, "fold", counted_fold)
        mp.setattr(people_review, "evidence", counted_pair)
        mp.setattr(index_module.Index, "by_kind", counted_kind)
        for name in ("lines", "lines_unsorted", "located_lines"):
            mp.setattr(Logbook, name, swept)

    def clear(self) -> None:
        self.lines.clear()
        self.whole.clear()
        self.folds = self.pairs = 0

    @property
    def read(self) -> int:
        return sum(self.lines.values())


def _record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lines: int) -> tuple[Logbook, dict[str, Any]]:
    """The benchmark's record of `lines` lines, its index beside it; the environment the builder
    sets is this test's, undone after it."""
    for key, value in bench._environment(tmp_path).items():
        if key.startswith("LOGBOOK_"):
            monkeypatch.setenv(key, value)
    built = bench.build(tmp_path, lines, bench.SEED)
    return Logbook(tmp_path / "record"), built


def _routes(built: dict[str, Any], day: str) -> list[str]:
    fill = {
        "day": day,
        "week": bench.week_of(day),
        "person": built["busiest_person"],
        "org": built["org"],
        "idea": built["idea"],
    }
    return [r.format(**fill) for r in bench.ROUTES if "{journey}" not in r]


@pytest.mark.parametrize("lines", SIZES)
def test_every_route_answers_and_reads_once_per_head(
    lines: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, built = _record(tmp_path, monkeypatch, lines)
    site = serve.Site(lb, now=lambda: bench.NOW)
    day = bench.busiest_day(tmp_path)
    reads = Reads(monkeypatch)
    first: dict[str, Counter[tuple[str, str]]] = {}
    for route in _routes(built, day):
        reads.clear()
        response = site.respond(route)
        assert response.status == (302 if route == "/today" else 200), route
        first[route] = Counter(reads.lines)
        # nights by bisection: a page folds the owner's stays once a reading, never once a day
        assert reads.folds <= 24, (route, reads.folds)
        # the promises and the agents' sessions stream the messages: never all of them in memory
        assert "message" not in reads.whole, (route, dict(reads.whole))
        reads.clear()
        again = site.respond(route)
        assert again.body == response.body
        if route != "/assets":  # the age of a fix moves with the clock: read again, one line a subject
            assert reads.read == 0, (route, dict(reads.lines))
    # the people of the whole record are read once for every person's page
    reads.clear()
    site.respond("/people/019cadd3-6bc0-7dcd-9133-000000000002")
    assert reads.read <= 1, dict(reads.lines)  # the line the last real contact was, at most
    # the Ideas pages read the Notion lines among the events; the review the titles of the rest
    assert first["/ideas"][("event", "notion")] > 0
    # the Day reads its own days (and the record's resolutions and signatures), never the whole record
    marks = {"resolution", "retraction", "signed-day", "star", "keeper", "chapter", "goal", "review"}
    assert sum(n for (kind, _source), n in first[f"/day/{day}"].items() if kind not in marks) < lines / 10


@pytest.mark.parametrize("lines", SIZES)
def test_today_reads_its_days_and_the_readings_kept_beside_the_index(
    lines: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Today (`/`, RFC 0047 §4.1) reads the night before today, a few days back for its memory, and its
    promises and replies owed from the readings kept beside the index (ADR 0025): once those are kept,
    a server started again reads a small part of the record for it and never a whole kind of words,
    and a second visit at the same head reads nothing."""
    lb, _built = _record(tmp_path, monkeypatch, lines)
    serve.Site(lb, now=lambda: bench.NOW).respond(
        "/"
    )  # the first reading keeps its readings beside the index
    reads = Reads(monkeypatch)
    site = serve.Site(lb, now=lambda: bench.NOW)  # the server, started again
    response = site.respond("/")
    assert response.status == 200
    assert reads.folds <= 24, reads.folds
    assert not {"message", "mail", "transcript", "note"} & set(reads.whole), dict(reads.whole)
    who = {"resolution", "retraction", "signed-day", "star", "keeper", "review", "chapter", "goal"}
    read = sum(n for (kind, _source), n in reads.lines.items() if kind not in who)
    assert read < lines / 20, dict(reads.lines)
    reads.clear()
    assert site.respond("/").body == response.body and reads.read == 0, dict(reads.lines)


@pytest.mark.parametrize("lines", SIZES)
def test_the_people_door_reads_the_people_once_and_each_thread_from_the_index(
    lines: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The People door (RFC 0047 §4.3) within the other pages' budget: the people of the whole record
    are read once for the door and every thread on it; a thread is the index's rows of a person's
    lines, never the lines (a card none, a person's whole thread the one line its last real contact
    was); the words of what was said are read only when asked, `door_people.SAID` lines; a reload at
    the same head reads nothing."""
    from logbook.contrib import door_people

    lb, built = _record(tmp_path, monkeypatch, lines)
    site = serve.Site(lb, now=lambda: bench.NOW)
    reads = Reads(monkeypatch)
    busiest, other = built["busiest_person"], "019cadd3-6bc0-7dcd-9133-000000000003"
    for target in ("/people", f"/people?year={bench.NOW.year - 1}"):
        path, _, query = target.partition("?")
        reads.clear()
        response = site.respond(path, query)
        assert response.status == 200, target
        assert reads.folds <= 24, (target, reads.folds)
        assert "message" not in reads.whole, (target, dict(reads.whole))
        reads.clear()
        assert site.respond(path, query).body == response.body and reads.read == 0, (
            target,
            dict(reads.lines),
        )
    for target, most in (
        (f"/people?sel={other}", 0),  # the card: index rows alone
        (f"/people/{busiest}", 1),  # the whole thread: and the line the last real contact was
        (f"/people/{other}?said=1", 1 + door_people.SAID),  # and the words, when asked
    ):
        path, _, query = target.partition("?")
        reads.clear()
        assert site.respond(path, query).status == 200, target
        assert reads.read <= most and reads.folds == 0, (target, dict(reads.lines), reads.folds)
        assert "message" not in reads.whole, (target, dict(reads.whole))


@pytest.mark.parametrize("lines", SIZES)
def test_ask_reads_the_matches_and_the_days_of_its_page(
    lines: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ask (`/ask?q=`, RFC 0047 §4.5) asks the index's search table for the words, reads the hits of its
    page from the files, and for each of its days one reading of that day and the day before (one fold
    of the stays): never a whole kind of words, never the record. The busiest word of the record,
    a full page of it; then its next page; and a second visit at the same head reads nothing."""
    lb, _built = _record(tmp_path, monkeypatch, lines)
    site = serve.Site(lb, now=lambda: bench.NOW)
    reads = Reads(monkeypatch)
    who = {"resolution", "retraction", "signed-day", "star", "keeper", "review", "chapter", "goal"}
    for query in ("q=harbour", "q=harbour&page=2", "q=sail+tide", "q=harbour&standing=1"):
        reads.clear()
        response = site.respond("/ask", query)
        assert response.status == 200, query
        assert response.body.count(b'class="words"') > 0, query
        assert reads.folds <= 24, (query, reads.folds)  # as every page: a reading a day of the page
        assert not {"message", "mail", "transcript", "note", "event"} & set(reads.whole), dict(reads.whole)
        read = sum(n for (kind, _source), n in reads.lines.items() if kind not in who)
        assert read < lines / 20, (query, dict(reads.lines))
        reads.clear()
        assert site.respond("/ask", query).body == response.body and reads.read == 0, dict(reads.lines)


@pytest.mark.parametrize("lines", SIZES)
def test_the_people_review_compares_only_who_could_be_the_same(
    lines: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, _built = _record(tmp_path, monkeypatch, lines)
    reads = Reads(monkeypatch)
    report = people_review.read(lb)
    every = sum(1 for o in report.unplaced if o.writable) * len(report.canonicals)
    assert report.unplaced and report.canonicals
    assert reads.pairs * 20 < every, (reads.pairs, every)


def test_an_index_built_before_its_new_indexes_is_given_them_by_the_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from persona import persona_record

    lb = persona_record(tmp_path, monkeypatch)
    with lb.index():
        pass
    with contextlib.closing(sqlite3.connect(lb.index_path)) as db:
        for name in index_module.ADDED:
            db.execute(f"DROP INDEX {name}")
        db.commit()
    with lb.index() as idx:  # a writer's open, and any reader's but the Library's, adds nothing
        names = {str(n) for (n,) in idx.db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert not set(index_module.ADDED) & names
    serve.Site(lb).respond("/")  # the Library's GET brings the index to the head, and gives it the indexes
    with lb.index() as idx:
        names = {str(n) for (n,) in idx.db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        assert set(index_module.ADDED) <= names
        plan = " ".join(
            str(row[-1])
            for row in idx.db.execute("EXPLAIN QUERY PLAN SELECT file FROM lines WHERE id = ?", ("x",))
        )
        assert "lines_id" in plan


FRONT = ("/", "/shelves")  # the front door (Today) and the old front page, the shelves listed (#404)


def _plans(lb: Logbook, ran: list[str]) -> list[tuple[str, str]]:
    """Each statement `ran` names on the lines table, beside how SQLite reads it (EXPLAIN QUERY PLAN,
    asked of a connection of its own)."""
    found: list[tuple[str, str]] = []
    with contextlib.closing(sqlite3.connect(lb.index_path)) as db:
        for sql in ran:
            if re.search(r"\bFROM lines\b", sql) is None:
                continue
            plan = " | ".join(str(row[-1]) for row in db.execute(f"EXPLAIN QUERY PLAN {sql}"))
            found.append((sql, plan))
    return found


def test_the_front_doors_never_read_the_whole_lines_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Today and the shelves listed, as `logbook serve` renders them (`read_later`: what reads the whole
    record is read off the request): every statement either runs on the lines table is a search, never
    a scan of the table or of a whole index. The shelves' count is the head's seq (what `doctor`
    prints) and their first and last day two steps down the day_local index (`count(*), min(at),
    max(at)` read every row of a record of millions). A search can still read every line of one kind
    (Today reads the record's resolutions, retractions and signatures so): the scale test below times
    that."""
    from persona import persona_record

    lb = persona_record(tmp_path, monkeypatch)
    with lb.index() as idx:
        (lines,) = idx.db.execute("SELECT count(*) FROM lines").fetchone()
    site = serve.Site(lb, read_later=True)
    site.current()  # the index at the head, as the Library brings it when it starts
    monkeypatch.setattr(site, "_day_later_start", lambda: None)  # what is read later is not the request's
    ran: list[str] = []
    opened = index_module.Index.open

    def traced(lb: Logbook) -> index_module.Index:
        idx = opened(lb)
        idx.db.set_trace_callback(ran.append)
        return idx

    monkeypatch.setattr(index_module.Index, "open", traced)
    for path in FRONT:
        ran.clear()
        response = site.respond(path)
        assert response.status == 200, path
        plans = _plans(lb, ran)
        assert plans, (path, ran)  # the page read the index, and was seen here
        scans = [(sql, plan) for sql, plan in plans if "SCAN" in plan]
        assert not scans, (path, scans)
    shelves = site.respond("/shelves").body.decode("utf-8")
    assert f"{lines:,} lines, 2026-06-01 {serve.EN_DASH} 2026-06-21" in shelves


@pytest.mark.stress
def test_the_front_doors_answer_in_a_second_on_the_scale_record() -> None:
    """Today and the shelves listed on the scale harness's record (`tests/perf/run.py`: 2,000,000 lines,
    or LOGBOOK_PERF_LINES), kept in tests/perf/.record, from a server as `logbook serve` makes it
    (`read_later`): warm, each answers in a second. Warm is the first request of a second server, once
    a first has read the page: the index is in the system's memory and nothing is kept from the first
    (a server's second request is the page it kept, and times nothing). What `read_later` reads off the
    request is not started (`_day_later_start`): it is not the request's."""
    import os
    import time

    harness = SCRIPT.parents[1] / "tests" / "perf" / "run.py"
    perf_spec = importlib.util.spec_from_file_location("perf_run", harness)
    assert perf_spec is not None and perf_spec.loader is not None
    run: Any = importlib.util.module_from_spec(perf_spec)
    perf_spec.loader.exec_module(run)
    b = run.bench()
    lines = int(os.environ.get("LOGBOOK_PERF_LINES", run.LINES))
    run.record(b, run.ROOT, lines, run.PEOPLE, False)

    def server(mp: pytest.MonkeyPatch) -> serve.Site:
        site = serve.Site(Logbook(run.ROOT / "record"), now=lambda: b.NOW, read_later=True)
        mp.setattr(site, "_day_later_start", lambda: None)
        return site

    with pytest.MonkeyPatch.context() as mp:
        for key, value in b._environment(run.ROOT).items():
            mp.setenv(key, value)
        for path in FRONT:
            assert server(mp).respond(path).status == 200, path  # cold: the index read into memory
            warm = server(mp)
            t = time.perf_counter()
            response = warm.respond(path)
            warm_s = time.perf_counter() - t
            assert response.status == 200, path
            assert warm_s <= 1.0, (path, warm_s)


@pytest.mark.parametrize("lines", SIZES)
def test_life_reads_what_its_zoom_needs_once_per_head(
    lines: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Life door (`door_life`) within the budget every door meets: the owner's stays folded once a
    reading, never the messages whole, nothing read again at the same head. The Life zoom reads no track
    at all: the marks the index hands out by kind and the days kept beside it, a tenth of the record at
    most; the Year reads its year as the Journeys door does, and shares that reading with it."""
    lb, _built = _record(tmp_path, monkeypatch, lines)
    site = serve.Site(lb, now=lambda: bench.NOW)
    reads = Reads(monkeypatch)
    for query in ("", "zoom=life", "zoom=month", "zoom=week", "zoom=day"):
        reads.clear()
        response = site.respond("/life", query)
        assert response.status == 200, query
        assert reads.folds <= 24, (query, reads.folds)
        assert "message" not in reads.whole, (query, dict(reads.whole))
        if query == "zoom=life":
            assert not [k for k in reads.lines if k[0] == "location"], dict(reads.lines)
            assert reads.read < lines / 10, dict(reads.lines)
        reads.clear()
        again = site.respond("/life", query)
        assert again.body == response.body
        assert reads.read == 0, (query, dict(reads.lines))
    reads.clear()
    site.respond("/journeys")  # the year the Life door read is the Journeys door's, read once
    assert not [k for k in reads.lines if k[0] == "location"], dict(reads.lines)


@pytest.mark.parametrize("lines", SIZES)
def test_the_places_door_reads_what_the_library_keeps_once_per_head(
    lines: int, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Places door (RFC 0047 §4.4) within the budget the other doors meet: the owner's stays folded
    at most as often as a page may (the World's bundle, a year at a time, the closed years kept), no
    message read whole, and asked again at the same head, nothing read at all. The first place's page
    reads the people of the record once (as a person's page does); every other place's reads nothing."""
    lb, _built = _record(tmp_path, monkeypatch, lines)
    site = serve.Site(lb, now=lambda: bench.NOW)
    reads = Reads(monkeypatch)
    door = site.respond("/places")
    assert door.status == 200
    assert reads.folds <= 24, reads.folds
    assert "message" not in reads.whole, dict(reads.whole)
    text = door.body.decode("utf-8")
    ids = re.findall(r'<a class="place-name" href="/places/([a-z0-9-]+)">', text)
    assert ids, "the bench's places, listed"
    year = str(bench.NOW.year - 3)
    for target in ("/places", f"/places?at={year}", *(f"/places/{i}" for i in ids[:3])):
        path, _, query = target.partition("?")
        reads.clear()
        first = site.respond(path, query)
        assert first.status == 200, target
        assert reads.folds <= 24, (target, reads.folds)
        assert "message" not in reads.whole, (target, dict(reads.whole))
        if target.startswith("/places/") and target != f"/places/{ids[0]}":
            assert reads.read == 0, (target, dict(reads.lines))
        reads.clear()
        again = site.respond(path, query)
        assert again.body == first.body and reads.read == 0, (target, dict(reads.lines))
