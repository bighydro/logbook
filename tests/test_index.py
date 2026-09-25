"""index.sqlite: a disposable locator for the files (ADR 0001, 0007). Built by `logbook index` or by
the first reader that finds it missing or stale; kept current by append/append_many; never read by
verify. Deleting it loses nothing."""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import cli, index, store
from logbook.export import write_day_package
from logbook.store import Logbook

ROOT = Path(__file__).resolve().parents[1]
TZ = "Europe/Oslo"  # UTC+1 in March: 23:30Z on the 1st is 00:30 local on the 2nd


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    """Four lines, two per local day; three share UTC date 2026-03-01. No index yet."""
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append(
        at="2026-03-01T07:30:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.911, "lon": 10.75, "raw_id": "trk:1"},
    )
    lb.append(
        at="2026-03-01T22:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "late dinner"},
    )
    lb.append(  # 00:30 local on 2026-03-02
        at="2026-03-01T23:30:00Z",
        source="sim-phone",
        kind="location",
        tier=1,
        payload={"schema": "location/v1", "lat": 59.92, "lon": 10.74, "raw_id": "trk:2"},
    )
    lb.append(
        at="2026-03-02T08:00:00Z",
        source="sim-calendar",
        kind="event",
        tier=1,
        payload={"schema": "event/v1", "title": "Standup"},
    )
    return lb


def _rows(lb: Logbook, sql: str) -> list[tuple[Any, ...]]:
    """Read the index with a connection that is closed before the call returns: an open handle
    would stop the code under test from deleting the file (Windows refuses; Unix does not)."""
    with closing(sqlite3.connect(lb.root / "index.sqlite")) as db:
        return list(db.execute(sql))


def _tamper(lb: Logbook, *sql: str) -> None:
    """Run statements against the index and close the connection before returning."""
    with closing(sqlite3.connect(lb.root / "index.sqlite")) as db:
        for statement in sql:
            db.execute(statement)
        db.commit()


def _build(lb: Logbook) -> None:
    """Build (or refresh) the index and close it; a test must never hold an Index open."""
    with lb.index():
        pass


def _head_in_index(lb: Logbook) -> str:
    return str(_rows(lb, "SELECT value FROM meta WHERE key = 'head'")[0][0])


def _draft(i: int, source: str = "dawarich") -> dict[str, Any]:
    return {
        "at": f"2026-04-12T05:{i % 60:02d}:00Z",
        "source": source,
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.9, "lon": 10.7, "raw_id": f"t:{i}"},
    }


# -- logbook index -----------------------------------------------------------------


def test_index_command_builds_from_the_files_and_records_the_head(lb: Logbook, capsys):
    assert not (lb.root / "index.sqlite").exists()
    cli.main(["index"])
    out = capsys.readouterr().out
    assert "indexed 4 lines" in out and "index.sqlite" in out
    assert _rows(lb, "SELECT count(*) FROM lines") == [(4,)]
    assert _head_in_index(lb) == lb.meta["head"]
    columns = [r[1] for r in _rows(lb, "PRAGMA table_info(lines)")]
    assert columns == [
        "seq",
        "id",
        "at",
        "day_local",
        "kind",
        "source",
        "tier",
        "raw_id",
        "file",
        "offset",
        "supersedes",
        "entity",
        "media",
    ]
    indexes = {r[0] for r in _rows(lb, "SELECT name FROM sqlite_master WHERE type = 'index'")}
    assert {"lines_day_local", "lines_source_raw_id", "lines_kind_at"} <= indexes


def test_index_rows_carry_the_local_day_and_where_the_line_is_in_the_files(lb: Logbook):
    _build(lb)
    rows = _rows(lb, "SELECT seq, day_local, source, raw_id, file, offset FROM lines ORDER BY seq")
    assert [r[1] for r in rows] == ["2026-03-01", "2026-03-01", "2026-03-02", "2026-03-02"]
    assert rows[0][2:4] == ("sim-phone", "trk:1") and rows[1][3] is None
    for seq, _day, _source, _raw, file, offset in rows:
        with (lb.root / file).open("rb") as fh:
            fh.seek(offset)
            assert json.loads(fh.readline())["seq"] == seq
    assert rows[0][4] == "logbook/2026/03.jsonl"


def test_index_build_reports_progress_every_build_progress_every_lines(lb: Logbook, monkeypatch):
    monkeypatch.setattr(index, "BUILD_PROGRESS_EVERY", 3)
    seen: list[int] = []
    lb.index_rebuild(progress=lambda n, elapsed: seen.append(n))
    assert seen == [3]


# -- readers check the head and rebuild -------------------------------------------------


def test_show_looks_a_day_up_by_local_date(lb: Logbook, capsys):
    cli.main(["show", "2026-03-02"])
    out = capsys.readouterr().out
    assert "00:30" in out and "location" in out and "Standup" in out
    cli.main(["show", "2026-03-01"])
    out = capsys.readouterr().out
    assert "late dinner" in out and "08:30" in out and "Standup" not in out


def test_deleting_the_index_loses_nothing_show_rebuilds_it_silently(lb: Logbook, capsys):
    _build(lb)
    cli.main(["show", "2026-03-01"])
    before = capsys.readouterr()
    (lb.root / "index.sqlite").unlink()
    cli.main(["show", "2026-03-01"])
    after = capsys.readouterr()
    assert after.out == before.out and after.err == ""
    assert (lb.root / "index.sqlite").exists() and _head_in_index(lb) == lb.meta["head"]


def test_a_stale_index_is_rebuilt_before_it_is_read(lb: Logbook):
    _build(lb)
    _tamper(lb, "UPDATE meta SET value = 'stale' WHERE key = 'head'", "DELETE FROM lines WHERE seq = 4")
    assert lb.line_by_seq(4) is not None
    assert _head_in_index(lb) == lb.meta["head"] and _rows(lb, "SELECT count(*) FROM lines") == [(4,)]


def test_an_unreadable_index_is_treated_as_missing(lb: Logbook):
    (lb.root / "index.sqlite").write_bytes(b"not a database")
    assert [line["seq"] for line in lb.day_lines("2026-03-02")] == [3, 4]
    assert _head_in_index(lb) == lb.meta["head"]


def test_a_changed_timezone_rebuilds_the_index(lb: Logbook):
    _build(lb)
    meta = lb.meta
    meta["timezone"] = "UTC"
    lb._save_meta(meta)
    assert [line["seq"] for line in lb.day_lines("2026-03-01")] == [1, 2, 3]


def test_verify_never_opens_the_index(lb: Logbook, capsys):
    (lb.root / "index.sqlite").write_bytes(b"not a database")
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 4
    cli.main(["verify"])
    assert capsys.readouterr().out.startswith("valid")
    assert (lb.root / "index.sqlite").read_bytes() == b"not a database"


# -- connections: closed before any unlink, on every platform -------------------------------


def test_an_index_can_be_closed_deleted_and_reopened(lb: Logbook):
    idx = lb.index()
    idx.close()
    (lb.root / "index.sqlite").unlink()  # Windows would refuse this with the connection still open
    with lb.index() as again:
        assert again.by_seq(1) is not None
    assert _head_in_index(lb) == lb.meta["head"]


def test_discard_closes_its_own_connection_and_refuses_while_another_is_open(lb: Logbook):
    """Deleting index.sqlite under an open connection fails on Windows and silently succeeds on
    Unix; `discard` makes it fail everywhere, so the suite catches it on any platform."""
    with lb.index() as held:
        other = index.Index.open(lb)
        with pytest.raises(RuntimeError):
            other.discard()
        assert (lb.root / "index.sqlite").exists() and held.by_seq(1) is not None
    other.discard()  # `held` is closed now; `other` was closed by the refused attempt
    assert not (lb.root / "index.sqlite").exists()


def test_a_closed_index_refuses_to_be_read(lb: Logbook):
    idx = lb.index()
    idx.close()
    with pytest.raises(RuntimeError):
        idx.by_seq(1)


# -- writers keep it current ------------------------------------------------------------


def test_append_keeps_a_current_index_current_without_a_rebuild(lb: Logbook, monkeypatch):
    _build(lb)
    line = lb.append(
        at="2026-03-03T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "x"},
    )
    assert _head_in_index(lb) == line["hash"] == lb.meta["head"]
    assert _rows(lb, "SELECT seq, day_local FROM lines WHERE seq = 5") == [(5, "2026-03-03")]

    def no_rebuild(self: index.Index, progress: Any = None) -> int:
        raise AssertionError("the index was current; nothing should rebuild it")

    monkeypatch.setattr(index.Index, "rebuild", no_rebuild)
    assert [line["seq"] for line in lb.day_lines("2026-03-03")] == [5]


def test_append_discards_a_stale_index_rather_than_extending_it(lb: Logbook):
    _build(lb)
    _tamper(lb, "UPDATE meta SET value = 'stale' WHERE key = 'head'")
    lb.append(
        at="2026-03-03T10:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "x"},
    )
    assert not (lb.root / "index.sqlite").exists()


def test_append_many_updates_the_index_at_each_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "META_EVERY", 5)
    lb = Logbook.init(tmp_path / "lb", "UTC")
    snapshots: list[tuple[int, bool]] = []

    def drafts() -> Iterator[dict[str, Any]]:
        for i in range(13):
            if i in (7, 12):  # between checkpoints
                (count,) = _rows(lb, "SELECT count(*) FROM lines")[0]
                snapshots.append((count, _head_in_index(lb) == lb.meta["head"]))
            yield _draft(i)

    lb.append_many(drafts())
    assert snapshots == [(5, True), (10, True)]
    assert _rows(lb, "SELECT count(*) FROM lines") == [(13,)] and _head_in_index(lb) == lb.meta["head"]


def test_append_many_dedupes_with_one_select_per_batch(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "META_EVERY", 5)
    lb = Logbook.init(tmp_path / "lb", "UTC")
    assert lb.append_many(_draft(i) for i in range(4)) == 4
    statements: list[str] = []
    original_connect = sqlite3.connect

    def tracing(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        db = original_connect(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, "connect", tracing)
    again = [
        *(_draft(i) for i in range(12)),
        _draft(5),
        _draft(2, source="owntracks"),
    ]  # 14 drafts, 3 batches
    assert lb.append_many(again) == 9  # t:4..t:11 and t:2 from the other source
    selects = [s for s in statements if s.lstrip().upper().startswith("SELECT") and "raw_id" in s]
    assert len(selects) == 3
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 13


def test_interrupted_append_many_leaves_the_index_at_the_last_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "META_EVERY", 5)
    lb = Logbook.init(tmp_path / "lb", "UTC")

    def interrupted() -> Iterator[dict[str, Any]]:
        for i in range(30):
            if i == 12:
                raise KeyboardInterrupt
            yield _draft(i)

    with pytest.raises(KeyboardInterrupt):
        lb.append_many(interrupted())
    assert _rows(lb, "SELECT count(*) FROM lines") == [(12,)] and _head_in_index(lb) == lb.meta["head"]
    assert lb.append_many(_draft(i) for i in range(30)) == 18


# -- retract, export ------------------------------------------------------------------


def test_retract_finds_the_line_through_the_index_and_records_the_retraction(lb: Logbook, capsys):
    _build(lb)
    (lb.root / "index.sqlite").unlink()
    cli.main(["retract", "2", "wrong cafe"])
    assert "retracted #2" in capsys.readouterr().out
    assert _rows(lb, "SELECT kind FROM lines WHERE seq = 5") == [("retraction",)]
    cli.main(["show", "2026-03-01"])
    out = capsys.readouterr().out
    assert "retracted #2: wrong cafe" in out and "late dinner" not in out


def test_export_day_reads_the_same_package_with_or_without_the_index(lb: Logbook, tmp_path: Path):
    lb.retract(3, "not me", at="2026-03-05T09:00:00Z")
    write_day_package(lb, "2026-03-02", tmp_path / "a", generated_at="2026-03-06T00:00:00Z")
    (lb.root / "index.sqlite").unlink()
    write_day_package(lb, "2026-03-02", tmp_path / "b", generated_at="2026-03-06T00:00:00Z")
    a, b = (tmp_path / "a" / "package.json").read_bytes(), (tmp_path / "b" / "package.json").read_bytes()
    assert a == b
    entries = json.loads(a)["entries"]
    assert [e["seq"] for e in entries] == [3, 4] and "retracted_by" in entries[0]


def test_export_days_with_a_current_index_does_not_scan_the_files(lb: Logbook, tmp_path: Path, monkeypatch):
    _build(lb)
    calls: list[Path] = []
    original = Logbook.files

    def counting(self: Logbook) -> list[Path]:
        calls.append(self.root)
        return original(self)

    monkeypatch.setattr(Logbook, "files", counting)
    cli.main(["export", "--days", "2026-03-01", "2026-03-02", "--out", str(tmp_path / "o")])
    assert calls == []
    assert sorted(p.name for p in (tmp_path / "o").iterdir()) == ["2026-03-01", "2026-03-02"]


def test_whole_log_export_and_verify_read_the_files_not_the_index(lb: Logbook, tmp_path: Path, capsys):
    _build(lb)
    _tamper(lb, "DELETE FROM lines")  # a lying index; head still matches
    cli.main(["export", str(tmp_path / "all.jsonl")])
    assert "exported 4 lines" in capsys.readouterr().out
    assert len((tmp_path / "all.jsonl").read_text(encoding="utf-8").splitlines()) == 4


def test_index_sqlite_is_in_the_root_ignore_list():
    assert "index.sqlite" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()


# -- resolutions: every resolution/v1 line, in chain order, kept in step by append ------------------


def _resolution(value: str, label: str) -> dict[str, Any]:
    return {
        "schema": "resolution/v1",
        "ref": {"kind": "email", "value": value},
        "entity": {"type": "person", "id": "019cadd3-6bc0-7dcd-9133-043f5aabf2a9", "registry": "logbook"},
        "label": label,
    }


def test_resolutions_lists_every_resolution_line_in_seq_order_and_nothing_else(lb: Logbook):
    lb.append(
        at="2026-03-05T10:00:00Z", source="manual", kind="resolution", tier=2, payload=_resolution("a@x", "A")
    )
    lb.append(
        at="2026-03-04T10:00:00Z", source="manual", kind="resolution", tier=2, payload=_resolution("b@x", "B")
    )
    with lb.index() as idx:  # built from the files: a rebuild
        assert [line["payload"]["label"] for line in idx.resolutions()] == ["A", "B"]
        assert {line["kind"] for line in idx.resolutions()} == {"resolution"}


def test_resolutions_sees_a_line_appended_after_the_index_was_built(lb: Logbook):
    _build(lb)
    lb.append(
        at="2026-03-05T10:00:00Z", source="manual", kind="resolution", tier=2, payload=_resolution("a@x", "A")
    )
    with lb.index() as idx:  # incremental add, no rebuild
        assert [line["payload"]["label"] for line in idx.resolutions()] == ["A"]
