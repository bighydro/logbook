"""The indexes `index.ADDED` names are given to an index built before them by the Library alone, on a
GET, under the record's writer lock taken without waiting (`Index.add_indexes`, `docs/serve.md`,
*Performance*): never by a write path, never while this process or another holds the lock. A writer
that arrives while they are built waits on the lock, says so in its one line, and then appends; it
never waits inside SQLite's busy timeout. Two writers are two processes here, as they are in life.
Synthetic Oslo persona; nobody in it exists."""

from __future__ import annotations

import contextlib
import html
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import DAYS, persona_record

from logbook.contrib import serve
from logbook.core import index as index_module
from logbook.core import store
from logbook.core.store import LOCK_FILE, Logbook

ROOT = Path(__file__).resolve().parents[1]
DAY = DAYS[2]  # Wednesday 10 June 2026
LOOPBACK = "127.0.0.1"
NOW = datetime(2026, 6, 22, 9, 0, tzinfo=UTC)

HOLDER = """
import sys
from logbook.core.store import Logbook
with Logbook.find().writer(command="sync immich"):
    print("held", flush=True)
    sys.stdin.read()
"""

LATE_WRITER = """
from logbook.core import store
from logbook.core.store import Logbook
store.COMMAND = "sync immich"
line = Logbook.find().append("2026-06-21T20:00:00Z", "immich", "photo", 1,
                             {"schema": "photo/v1", "raw_id": "late:1"})
print(line["seq"])
"""


def _env(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.update({"LOGBOOK_HOME": str(root), "PYTHONPATH": str(ROOT)})
    return env


def _python(root: Path, script: str, **kwargs: Any) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        env=_env(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        **kwargs,
    )


def _names(lb: Logbook) -> set[str]:
    with contextlib.closing(sqlite3.connect(lb.index_path)) as db:
        return {str(n) for (n,) in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}


def _without_added(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """The persona's record, its index current and built before `index.ADDED`."""
    lb = persona_record(tmp_path, monkeypatch)
    with lb.index():
        pass
    with contextlib.closing(sqlite3.connect(lb.index_path)) as db:
        for name in index_module.ADDED:
            db.execute(f"DROP INDEX {name}")
        db.commit()
    assert not set(index_module.ADDED) & _names(lb)
    return lb


def _hidden(form: str) -> dict[str, str]:
    """A page's form as the browser sends it: its hidden fields."""
    return {
        name: html.unescape(value)
        for name, value in re.findall(r'<input type="hidden" name="([^"]+)" value="([^"]*)"', form)
    }


def _note(lb: Logbook, text: str) -> None:
    lb.append("2026-06-21T19:00:00Z", "manual", "note", 1, {"schema": "note/v1", "text": text})


def _holding(lb: Logbook) -> bool:
    """Whether this process holds the record's writer lock."""
    return bool(store._held.get(lb._lock_path()))


def _calls(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Every call of `add_indexes`, by whether this process held the writer lock then: one that does
    fails the test where it happens."""
    calls: list[bool] = []
    add = index_module.Index.add_indexes

    def counted(idx: index_module.Index) -> None:
        calls.append(_holding(idx.lb))
        assert not calls[-1], "add_indexes was called under the writer lock"
        add(idx)

    monkeypatch.setattr(index_module.Index, "add_indexes", counted)
    return calls


@pytest.mark.parametrize("act", ["reflect", "sign"])
def test_a_write_never_adds_the_indexes_and_the_get_after_it_does(
    act: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _without_added(tmp_path, monkeypatch)
    site = serve.Site(lb, now=lambda: NOW)
    if act == "sign":  # the Day's Sign form is there once the day has a reflection
        reflected = {"act": "reflect", "text": "A calm day on the fjord."}
        assert site.write(f"/day/{DAY}/reflect", reflected, LOOPBACK, None).status == 303
    page = site.respond(f"/day/{DAY}")  # the Library has seen this head
    assert page.status == 200
    signing = re.search(r'<form class="sign"[^>]*>.*?</form>', page.body.decode("utf-8"), re.S)
    with contextlib.closing(sqlite3.connect(lb.index_path)) as db:
        for name in index_module.ADDED:  # (the GET gave them; take them away again for the act)
            db.execute(f"DROP INDEX IF EXISTS {name}")
        db.commit()
    _note(lb, "The harbour map is in the drawer.")  # the head moves: a sync while the server runs
    calls = _calls(monkeypatch)
    if act == "sign":
        assert signing is not None
        form = {**_hidden(signing.group(0)), "act": "sign"}
    else:
        form = {"act": act, "text": "A calm day on the fjord."}
    response = site.write(f"/day/{DAY}/{act}", form, LOOPBACK, None)
    assert response.status == 303, response.body[:300]
    assert calls == []  # the act, the first request at the new head, never asked for them
    assert not set(index_module.ADDED) & _names(lb)
    assert not _holding(lb)
    assert site.respond(f"/day/{DAY}").status == 200
    assert calls == [False]  # the GET after it built them, outside the writer
    assert set(index_module.ADDED) <= _names(lb)
    assert not (lb.root / LOCK_FILE).exists()  # and let the lock go


def test_another_writer_holding_the_lock_means_nothing_is_built_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _without_added(tmp_path, monkeypatch)
    site = serve.Site(lb, now=lambda: NOW)
    holder = _python(lb.root, HOLDER, stdin=subprocess.PIPE)
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        with index_module.Index(lb) as idx:
            started = time.monotonic()
            assert idx.add_indexes()  # settled for this head: the next head tries again
            assert time.monotonic() - started < store.LOCK_POLL_S  # no wait: not one poll of a waiting writer
        assert not set(index_module.ADDED) & _names(lb)
        assert site.respond(f"/day/{DAY}").status == 200  # the page is served all the same
        assert not set(index_module.ADDED) & _names(lb)
    finally:
        holder.communicate(timeout=30)  # its stdin closed: it lets the lock go
    assert holder.returncode == 0
    assert site.respond(f"/day/{DAY}").status == 200  # the same head: tried once, not again
    assert not set(index_module.ADDED) & _names(lb)
    _note(lb, "Ola will book the ferry.")
    assert site.respond(f"/day/{DAY}").status == 200  # the next head
    assert set(index_module.ADDED) <= _names(lb)


def test_this_process_holding_the_lock_means_nothing_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _without_added(tmp_path, monkeypatch)
    with lb.writer(), index_module.Index(lb) as idx:
        assert idx.add_indexes() is False  # a write path: never here, and asked again later
        assert _holding(lb) and (lb.root / LOCK_FILE).exists()  # the writer's lock, still the writer's
    assert not set(index_module.ADDED) & _names(lb)


def test_a_get_while_an_act_of_the_server_writes_builds_nothing_and_the_next_get_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _without_added(tmp_path, monkeypatch)
    site = serve.Site(lb, now=lambda: NOW)
    with site._write_lock:  # an act of this server is writing, on another thread
        assert site.respond(f"/day/{DAY}").status == 200
    assert not set(index_module.ADDED) & _names(lb)
    assert site.respond(f"/day/{DAY}").status == 200  # the same head, the next GET
    assert set(index_module.ADDED) <= _names(lb)


def test_a_reader_holding_the_file_means_nothing_is_built_and_the_next_get_does(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _without_added(tmp_path, monkeypatch)
    site = serve.Site(lb, now=lambda: NOW)
    with contextlib.closing(sqlite3.connect(lb.index_path, isolation_level=None)) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM lines").fetchone()  # a page reading, mid-transaction
        assert site.respond(f"/day/{DAY}").status == 200  # no busy wait: served, nothing built
        assert not set(index_module.ADDED) & _names(lb)
        assert not (lb.root / LOCK_FILE).exists()  # the lock let go
        reader.execute("COMMIT")
    assert site.respond(f"/day/{DAY}").status == 200  # the same head, the next GET
    assert set(index_module.ADDED) <= _names(lb)


def test_a_record_folder_that_takes_no_lock_file_serves_its_pages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _without_added(tmp_path, monkeypatch)

    def refused(*_args: Any) -> None:  # a read-only mount, a backup copy, another user's folder
        raise PermissionError("read-only file system")

    monkeypatch.setattr(store, "_take_lock", refused)
    site = serve.Site(lb, now=lambda: NOW)
    assert site.respond(f"/day/{DAY}").status == 200
    assert not set(index_module.ADDED) & _names(lb)


def test_a_writer_that_arrives_while_they_are_built_waits_on_the_lock_and_appends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb = _without_added(tmp_path, monkeypatch)
    monkeypatch.setattr(store, "COMMAND", "logbook serve")
    building, release = threading.Event(), threading.Event()

    def slow() -> int:  # the build of millions of rows, as long as the test holds it
        building.set()
        assert release.wait(30)
        return 1

    connect = sqlite3.connect

    def with_slow(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        db = connect(*args, **kwargs)
        db.create_function("slow", 0, slow)
        return db

    monkeypatch.setattr(index_module.sqlite3, "connect", with_slow)  # this process only
    # first, a statement that holds SQLite's write lock as long as the build does, as a CREATE INDEX would
    added = {"zz_slow_build": "CREATE TABLE slow_build AS SELECT slow() AS done", **index_module.ADDED}
    monkeypatch.setattr(index_module, "ADDED", added)
    seq = int(lb.meta["seq"])
    failed: list[BaseException] = []

    def build() -> None:
        try:
            with index_module.Index(lb) as idx:
                idx.add_indexes()
        except BaseException as e:  # pragma: no cover - reported below
            failed.append(e)

    builder = threading.Thread(target=build)
    builder.start()
    late: subprocess.Popen[str] | None = None
    try:
        assert building.wait(30)
        assert (lb.root / LOCK_FILE).exists()  # the Library holds the writer lock while it builds
        late = _python(lb.root, LATE_WRITER)
        said: list[str] = []
        reader = threading.Thread(target=lambda: said.append(late.stderr.readline() if late.stderr else ""))
        reader.start()
        reader.join(30)
        assert said and "another logbook command is writing to this record (logbook serve, since" in said[0]
        assert said[0].rstrip().endswith("; waiting"), said
        assert int(lb.meta["seq"]) == seq  # waiting on the lock: nothing written yet
    finally:
        release.set()
        builder.join(30)
    assert not failed, failed
    assert late is not None
    out, err = late.communicate(timeout=60)
    assert late.returncode == 0, err
    assert int(out.strip()) == seq + 1
    assert "database is locked" not in err
    assert not (lb.root / LOCK_FILE).exists()
    assert set(index_module.ADDED) - {"zz_slow_build"} <= _names(lb)
    # the index is current with the record afterwards, and `verify` and it agree
    verified_seq, verified_head, errors = lb.verify()
    assert errors == []
    with index_module.Index(lb) as idx:
        assert idx.matches(lb.meta)
        (rows,) = idx.db.execute("SELECT count(*) FROM lines").fetchone()
        (last,) = idx.db.execute("SELECT max(seq) FROM lines").fetchone()
    assert (verified_seq, verified_head) == (int(lb.meta["seq"]), str(lb.meta["head"]))
    assert rows == last == verified_seq == seq + 1
