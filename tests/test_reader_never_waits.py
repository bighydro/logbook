"""A reader never waits on a writer, and never fights one (phase 6 of the Library's rebuild).

An append writes the line and fsyncs it, then `logbook.json`, then the index (SPEC §3's order). A
reader that comes between the second and the third sees `logbook.json` ahead of the index. Before
this it rebuilt the whole index from the files: minutes on a record of millions of lines, under the
Library's lock with every request behind it, while the writer, finding the index stale at its next
line, deleted it. Now, while a writer holds the lock, a reader reads the index as it stands: the record
up to the last line the index holds, every line of it whole. The Library names that line's head, so a
page's tag is what it read. With no writer, an index left behind (a crash) is rebuilt as before. On
the Oslo persona's fortnight (`persona.py`), who does not exist."""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from persona import persona_record

from logbook.contrib import serve
from logbook.core import index as index_module
from logbook.core import store
from logbook.core.store import Logbook

JUNE = datetime(2026, 6, 21, 10, 0, tzinfo=UTC)


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return persona_record(tmp_path, monkeypatch)


@contextlib.contextmanager
def other_writer(lb: Logbook) -> Iterator[int]:
    """Another live process holding the record's writer lock, as a `sync` would, from here on."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    path = lb._lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"pid": child.pid, "command": "logbook sync", "since": "2026-06-21T09:59:00Z"})
    )
    try:
        yield child.pid
    finally:
        path.unlink(missing_ok=True)
        child.kill()
        child.wait()


def _between(lb: Logbook, monkeypatch: pytest.MonkeyPatch, n: int = 1) -> tuple[int, str]:
    """`n` lines appended as a writer appends them, stopped before the index is told (one: a second
    would find the index behind and drop it, `_index_if_current`): the files and
    `logbook.json` ahead, the index where it was. The seq and head the index holds."""
    with lb.index() as idx:
        seq, head = int(lb.meta["seq"]), str(lb.meta["head"])
        assert idx.matches(lb.meta)
    with monkeypatch.context() as mp:
        mp.setattr(index_module.Index, "add", lambda *_a, **_k: None)
        for k in range(n):
            lb.append(
                at=f"2026-06-21T09:{k:02d}:00Z",
                source="sim-sync",
                kind="note",
                tier=2,
                payload={"schema": "note/v1", "text": f"appended mid-sync {k}"},
            )
    assert int(lb.meta["seq"]) == seq + n
    return seq, head


def test_a_reader_reads_the_index_as_it_stands_while_a_writer_writes(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    seq, head = _between(lb, monkeypatch)

    def rebuilt(*_a: object, **_k: object) -> int:
        raise AssertionError("a reader rebuilt the index from under a writer")

    monkeypatch.setattr(index_module.Index, "rebuild", rebuilt)
    with other_writer(lb), lb.index() as idx:
        assert idx.indexed() == (seq, head)
        assert not any(
            line["payload"].get("text", "").startswith("appended mid-sync") for line in idx.day("2026-06-21")
        )
    assert lb.index_path.exists(), "nothing deleted"


def test_the_library_names_the_head_it_read_and_answers(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    seq, head = _between(lb, monkeypatch)
    monkeypatch.setattr(index_module.Index, "rebuild", lambda *_a, **_k: pytest.fail("no rebuild"))
    site = serve.Site(lb, now=lambda: JUNE)
    with other_writer(lb):
        meta = site.current()
        assert (int(meta["seq"]), str(meta["head"])) == (seq, head), "the tag names what was read"
        for path in ("/", "/days", "/day/2026-06-20", "/people", "/journeys"):
            assert site.respond(path).status == 200, path
        tag = site.respond("/days").etag
    assert tag is not None and tag.startswith(f'"{head[: serve.HEAD_CHARS]}-')


def test_with_no_writer_an_index_left_behind_is_rebuilt_as_before(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    seq, _head = _between(lb, monkeypatch)
    assert not lb._lock_path().exists()
    with lb.index() as idx:
        assert idx.indexed()[0] == seq + 1 and idx.matches(lb.meta)


def test_an_index_of_another_zone_is_never_read_as_behind(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behind means the same index a few lines short: one built for another zone, schema or set of
    recipients is rebuilt, writer or not."""
    _between(lb, monkeypatch)
    with index_module.Index.open(lb) as idx:
        idx.db.execute("UPDATE meta SET value = 'Asia/Tokyo' WHERE key = 'timezone'")
    with other_writer(lb), lb.index() as idx:
        assert idx.matches(lb.meta), "rebuilt: not the same index"


def test_this_process_s_own_writer_counts_as_a_writer(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Library's own acts write from a thread of the server: a request on another thread reads the
    index as it stands too, never rebuilds it under its own server's writer."""
    seq, head = _between(lb, monkeypatch)
    monkeypatch.setattr(index_module.Index, "rebuild", lambda *_a, **_k: pytest.fail("no rebuild"))
    path = lb._lock_path()
    monkeypatch.setitem(store._held, path, 1)
    monkeypatch.setitem(store._holder, path, -1)  # another thread's block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": __import__("os").getpid(), "command": "logbook serve", "since": "x"}))
    try:
        with lb.index() as idx:
            assert idx.indexed() == (seq, head)
    finally:
        path.unlink(missing_ok=True)


def test_a_writer_that_finds_the_index_behind_rebuilds_it_never_writes_on_a_prefix(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behind with no other writer is what a crashed writer leaves: the writer that comes next (its
    own block, this thread) reads a current index, and its lines are indexed after every one before."""
    seq, _head = _between(lb, monkeypatch)
    with lb.writer():
        assert not lb.writing(), "its own block is not another writer"
        with lb.index() as idx:
            assert idx.indexed()[0] == seq + 1 and idx.matches(lb.meta)
        lb.append(
            at="2026-06-21T09:30:00Z",
            source="manual",
            kind="note",
            tier=2,
            payload={"schema": "note/v1", "text": "after the crash"},
        )
    with lb.index() as idx:
        assert idx.indexed()[0] == seq + 2 and idx.matches(lb.meta)
        assert idx.by_seq(seq + 1) is not None, "the line the crash left unindexed is there"
