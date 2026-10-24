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
