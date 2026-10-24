"""The edges of a reader that finds the index behind (`Logbook.index`, `Logbook.writing`, `Index.behind`).

`tests/test_reader_never_waits.py` covers the plain case: a live writer elsewhere, a reader reads the
index as it stands. Here, what is not a writer (a lock naming a dead pid, or this process's own pid
outside any writer block) leaves the reader to rebuild as before; a writer whose index a reader took
in the gap between `logbook.json` and the index (SPEC §3's order) still brings it forward, line and
all; and on a sealed record the index is behind only when it was opened as it would be now. On the
Oslo persona's fortnight (`persona.py`), who does not exist; the notes name Ines and Ola Nordmann,
who do not either."""

from __future__ import annotations

import contextlib
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from persona import persona_record

from logbook.core import index as index_module
from logbook.core import sealing, store
from logbook.core.store import Logbook


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    return persona_record(tmp_path, monkeypatch)


def _note(text: str) -> dict[str, Any]:
    return {"schema": "note/v1", "text": text}


def _behind(lb: Logbook, monkeypatch: pytest.MonkeyPatch, text: str, tier: int = 2) -> tuple[int, str]:
    """One line appended as a writer appends it, stopped before the index is told: the files and
    `logbook.json` a line ahead, the index where it was. The seq and head the index holds."""
    with lb.index() as idx:
        assert idx.matches(lb.meta)
        held = idx.indexed()
    with monkeypatch.context() as mp:
        mp.setattr(index_module.Index, "add", lambda *_a, **_k: None)
        lb.append(at="2026-06-21T09:00:00Z", source="manual", kind="note", tier=tier, payload=_note(text))
    assert int(lb.meta["seq"]) == held[0] + 1
    return held


def _lock(lb: Logbook, pid: int, command: str = "logbook sync") -> Path:
    path = lb._lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pid": pid, "command": command, "since": "2026-06-21T08:59:00Z"}))
    return path


@contextlib.contextmanager
def _live_writer(lb: Logbook) -> Iterator[None]:
    """Another live process holding the record's writer lock, as a `sync` would."""
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    path = _lock(lb, child.pid)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)
        child.kill()
        child.wait()


def _as_it_is(lb: Logbook) -> index_module.Index:
    """The index file as it is, never rebuilt: what the writer left."""
    return index_module.Index.open(lb)


def _dead_pid() -> int:
    """A pid no process has: a child that has exited, confirmed gone."""
    for _ in range(20):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        pid = child.pid
        del child  # Windows keeps an exited process while a handle to it is open
        if not store._alive(pid):
            return pid
    pytest.fail("could not find a pid no process has")


# -- a lock that is not a writer: the reader rebuilds -------------------------------------------------


def test_a_lock_naming_a_dead_pid_is_no_writer_and_the_reader_rebuilds(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    seq, _head = _behind(lb, monkeypatch, "Coffee with Ines Nordmann")
    path = _lock(lb, _dead_pid())
    try:
        assert not lb.writing()
        with lb.index() as idx:
            assert idx.indexed() == (int(lb.meta["seq"]), str(lb.meta["head"]))
            assert idx.indexed()[0] == seq + 1 and idx.matches(lb.meta)
    finally:
        path.unlink(missing_ok=True)


def test_a_lock_naming_this_process_outside_any_writer_block_is_stale_and_the_reader_rebuilds(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A block of this process that never released its file (`_held` is empty): no writer is writing."""
    seq, _head = _behind(lb, monkeypatch, "Lunch with Ola Nordmann")
    assert not store._held.get(lb._lock_path())
    path = _lock(lb, os.getpid(), "logbook serve")
    try:
        assert not lb.writing()
        with lb.index() as idx:
            assert idx.indexed() == (int(lb.meta["seq"]), str(lb.meta["head"]))
            assert idx.indexed()[0] == seq + 1 and idx.matches(lb.meta)
    finally:
        path.unlink(missing_ok=True)


# -- a reader in the gap: the writer still brings the index forward ----------------------------------


def test_the_writers_add_completes_after_a_reader_took_the_index_behind(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader on another thread (a Library request while the server's act appends) arrives between
    `logbook.json` and the index. It reads the index as it stands; the writer's `Index.add` then
    commits (no IntegrityError, no busy timeout) and the index is current, with the new line in it."""
    with lb.index() as idx:
        assert idx.matches(lb.meta)
        before = idx.indexed()
    monkeypatch.setattr(index_module.Index, "rebuild", lambda *_a, **_k: pytest.fail("no rebuild"))
    seen: list[tuple[int, str]] = []
    failed: list[BaseException] = []
    save = lb._save_meta

    def save_then_read(meta: dict[str, Any]) -> None:
        save(meta)  # logbook.json names the line; the index does not yet

        def read() -> None:
            try:
                reader = Logbook(lb.root)
                assert reader.writing(), "the writer's thread holds the lock"
                with reader.index() as idx:
                    seen.append(idx.indexed())
                    assert idx.by_seq(before[0] + 1) is None, "the reader reads up to the index's last line"
            except BaseException as error:  # carried back to the test's thread
                failed.append(error)

        thread = threading.Thread(target=read)
        thread.start()
        thread.join()

    monkeypatch.setattr(lb, "_save_meta", save_then_read)
    line = lb.append(
        at="2026-06-21T09:15:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload=_note("Ines Nordmann (ines@example.org) aboard Solvind for the afternoon"),
    )
    assert failed == [] and seen == [before]
    assert line["seq"] == before[0] + 1
    with _as_it_is(lb) as idx:
        assert idx.matches(lb.meta), "the writer's own add brought the index to logbook.json"
        found = idx.by_seq(line["seq"])
        assert found is not None and found["hash"] == line["hash"]
        assert found["payload"] == line["payload"]


# -- a sealed record: behind only when opened as now ---------------------------------------------------


@pytest.fixture
def sealed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, lb: Logbook) -> Logbook:
    """The persona's record naming two fresh recipients (as `test_sealing.py`'s `sealed_lb` does), the
    first identity where LOGBOOK_IDENTITY_FILE points, its index built opened."""
    pairs = [sealing.generate_identity() for _ in range(2)]
    meta = lb.meta
    meta["recipients"] = [recipient for _identity, recipient in pairs]
    lb._save_meta(meta)
    path = tmp_path / "keys" / "owner.txt"
    sealing.write_identity_file(path, str(pairs[0][0]), "test")
    monkeypatch.setenv("LOGBOOK_IDENTITY_FILE", str(path))
    keyed = Logbook(lb.root)
    assert keyed.identities
    with keyed.index() as idx:
        assert idx.matches(keyed.meta)
    return keyed


def _opened(lb: Logbook) -> str:
    with _as_it_is(lb) as idx:
        return str(dict(idx.db.execute("SELECT key, value FROM meta"))["opened"])


def test_a_sealed_index_behind_is_read_as_it_stands_while_a_writer_writes(
    sealed: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    seq, head = _behind(sealed, monkeypatch, "Ola Nordmann's birthday, the marina at seven")
    assert sealing.recipients_of(sealed.meta)
    monkeypatch.setattr(index_module.Index, "rebuild", lambda *_a, **_k: pytest.fail("no rebuild"))
    with _live_writer(sealed), sealed.index() as idx:
        assert idx.indexed() == (seq, head)
        assert idx.by_seq(seq + 1) is None
    assert _opened(sealed) == "true"


def test_a_sealed_index_opened_otherwise_is_not_behind_and_is_rebuilt_writer_or_not(
    sealed: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The index was built opened (with the identity); a reader without it would read payloads it may
    not: not the same index a line short, so it is rebuilt, sealed, even with a writer about."""
    _behind(sealed, monkeypatch, "Ines Nordmann's ferry times")
    keyless = Logbook(sealed.root, identity_file=tmp_path / "nowhere.txt")
    assert not keyless.identities
    with _live_writer(keyless):
        assert keyless.writing()
        with _as_it_is(keyless) as idx:
            assert not idx.behind(keyless.meta), "opened differs: stale, not behind"
        with keyless.index() as idx:
            assert idx.matches(keyless.meta)
            assert idx.indexed() == (int(keyless.meta["seq"]), str(keyless.meta["head"]))
    assert _opened(keyless) == "false"


# -- a reading in the gap is kept under the head it read ---------------------------------------------

READ_AT = datetime(2026, 6, 21, 5, 0, tzinfo=UTC)  # the persona's last day, 07:00 in Oslo: the morning
YARD = "kaiwerft.example.org"  # a boatyard the record has not seen; it does not exist, nor does Sindre
BYGDOY = (59.9070, 10.6840)  # a spot west of the city the persona has not been to


def _indexed(lb: Logbook) -> tuple[int, str]:
    with lb.index() as idx:
        return idx.indexed()


def _caught_up(lb: Logbook) -> tuple[int, str]:
    """The writer gone and the index brought to `logbook.json`, as the next reader with no writer about
    brings it. The seq and head it holds."""
    with lb.index() as idx:
        assert idx.matches(lb.meta)
        return idx.indexed()


def test_a_reading_shared_in_the_gap_is_kept_under_the_head_it_read(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A page read while a writer is between `logbook.json` and the index reads the index as it stands
    (`Site.current` names that head); what `Site.shared` and `Site._day_reading` keep of that reading is
    kept under it, so once the writer is done the next page reads the record with the new line, never
    the earlier reading under the new head."""
    from logbook.contrib import serve

    site = serve.Site(lb, now=lambda: READ_AT)
    site.current()
    held = _behind(lb, monkeypatch, "Coffee with Ines Nordmann on the quay")
    with _live_writer(lb):
        assert site.current()["head"] == held[1]
        assert site.shared(("read",), lambda: _indexed(lb)) == held
        assert site._day_reading(("read",), lambda: _indexed(lb)) == held
    now = _caught_up(lb)
    assert now == (held[0] + 1, str(lb.meta["head"]))
    assert site.shared(("read",), lambda: _indexed(lb)) == now, "the earlier reading, kept as the new head's"
    assert site._day_reading(("read",), lambda: _indexed(lb)) == now


def test_the_mornings_readings_asked_in_the_gap_are_keyed_by_the_head_read(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Day's readings beyond the day (`Site._day_later`: the replies owed, the decisions to revisit)
    are kept by the head; one asked for in the gap is kept by the head the page read."""
    from logbook.contrib import serve

    site = serve.Site(lb, now=lambda: READ_AT)
    site.current()
    held = _behind(lb, monkeypatch, "Ola Nordmann asked about the mooring fee")
    with _live_writer(lb):
        page = site.respond("/day/2026-06-21", "")
        assert page.status == 200
    keys = [key for key in site._day_later_kept if key[0] in ("owed", "revisit")]
    assert keys, "the morning asked for its replies owed and its revisits"
    assert {key[-1] for key in keys} == {held[1]}, "kept by the head the page read, not logbook.json's"


def _observed_people(lb: Logbook) -> list[dict[str, Any]]:
    from logbook.contrib import people_review

    return [o._row() for o in people_review.observed(lb)]


def _built_people(lb: Logbook) -> list[dict[str, Any]]:
    from logbook.contrib import people_review

    with lb.index() as idx:
        return [o._row() for o in people_review.build(lb, idx)]


def _observed_orgs(lb: Logbook) -> list[dict[str, Any]]:
    from logbook.contrib import entity_review

    return [o.row() for o in entity_review.observed(lb, "org")]


def _built_orgs(lb: Logbook) -> list[dict[str, Any]]:
    from logbook.contrib import entity_review

    with lb.index() as idx:
        return [o.row() for o in entity_review.build(lb, idx, "org")]


def _observed_places(lb: Logbook) -> list[dict[str, Any]]:
    from logbook.contrib import places_review

    return [o._row() for o in places_review.observed(lb)]


def _built_places(lb: Logbook) -> list[dict[str, Any]]:
    from logbook.contrib import places_review

    return [o._row() for o in places_review.build(lb)]


def _hull_survey() -> list[dict[str, Any]]:
    """A guest at a yard the record has not seen: a person and an org it observes for the first time."""
    from persona import attendee, event

    return [
        event(
            "2026-06-22T08:00:00Z",
            "2026-06-22T09:00:00Z",
            "Hull survey",
            [attendee(f"sindre@{YARD}", "Sindre Nordmann")],
        )
    ]


def _bygdoy_morning() -> list[dict[str, Any]]:
    """Three hours at a spot the record has not seen: a place it observes for the first time."""
    from persona import dwell

    return dwell("2026-06-22", "11:00", "14:00", BYGDOY)


@pytest.mark.parametrize(
    ("kind", "drafts", "observed", "built"),
    [
        ("person", _hull_survey, _observed_people, _built_people),
        ("org", _hull_survey, _observed_orgs, _built_orgs),
        ("place", _bygdoy_morning, _observed_places, _built_places),
    ],
)
def test_an_observed_table_built_in_the_gap_is_stamped_with_the_head_it_read(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, kind: str, drafts: Any, observed: Any, built: Any
) -> None:
    """The review pages' tables (`observed_entities`, in the index file: they outlive the server) are
    stamped with the head of what they were built from; one built in the gap is stamped with the index's
    head, so once the writer has added its lines to the index (`Index.add`, which keeps the tables) the
    next reading builds the table again, with what the lines brought."""
    before = observed(lb)
    with lb.index() as idx:
        assert idx.matches(lb.meta)
        held = idx.indexed()
    adds: list[tuple[Any, Any]] = []
    with monkeypatch.context() as mp:  # the writer, stopped between logbook.json and the index
        mp.setattr(index_module.Index, "add", lambda _idx, *a, **k: adds.append((a, k)))
        lb.append_many(drafts())
    assert adds and int(lb.meta["seq"]) > held[0]
    with _live_writer(lb):
        assert observed(lb) == before, "read in the gap: the record up to the index's last line"
        with _as_it_is(lb) as idx:
            assert idx.observed_stamp(kind)["head"] == held[1], "stamped with the head it was built from"
    with _as_it_is(lb) as idx:  # the writer goes on: its lines added to the index, the tables kept
        for a, k in adds:
            idx.add(*a, **k)
        assert idx.matches(lb.meta)
        assert idx.observed_stamp(kind), "the table built in the gap is still in the index"
    after = observed(lb)
    assert after == built(lb) and len(after) == len(before) + 1, "built again, with what the lines brought"


def test_a_page_and_a_build_made_in_the_gap_name_the_head_they_read(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The footer's head and the build's record name what the page read, as its tag does."""
    from logbook.contrib import library_build, serve

    held = _behind(lb, monkeypatch, "Ola Nordmann brought the new jib")
    ahead = str(lb.meta["head"])
    with _live_writer(lb):
        site = serve.Site(lb, now=lambda: READ_AT)
        body = site.respond("/days", "").body.decode("utf-8")
        assert f"<code>{held[1][: serve.HEAD_CHARS]}…</code>" in body
        assert ahead[: serve.HEAD_CHARS] not in body
        library = library_build.Library(lb, tmp_path / "library")
        library_build.build(lb, site, library, only=["/days"])
        assert library.pages()["/days"].head == held[1]
