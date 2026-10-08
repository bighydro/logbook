"""One writer at a time (#234): `append` and `append_many`, and every command that will append, hold
`state/writer.lock` in the record folder for the whole command, a `sync`'s walk included. A second
writer waits and says so, or with `--no-wait` refuses with exit 2; a lock whose process is gone is
taken over with one line; a reader never takes it. The lock is the courtesy: the guard is the head
re-check before every batch is written, so a batch computed from a stale head is never written.
Two writers are two processes here, as they are in life. Synthetic Oslo persona; nobody in it exists."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from logbook import cli
from logbook.core import store
from logbook.core.store import LOCK_FILE, HeadMoved, Logbook

ROOT = Path(__file__).resolve().parents[1]


def _draft(prefix: str, i: int, source: str = "dawarich") -> dict[str, Any]:
    return {
        "at": f"2026-09-1{i % 3}T{6 + i % 12:02d}:{i % 60:02d}:00Z",
        "source": source,
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.91, "lon": 10.75, "raw_id": f"{prefix}:{i}"},
    }


def _batch(prefix: str, n: int, source: str = "dawarich") -> list[dict[str, Any]]:
    return [_draft(prefix, i, source) for i in range(n)]


def _jsonl(path: Path, drafts: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(d) + "\n" for d in drafts), encoding="utf-8")
    return path


SLOW_WRITER = """
import sys, time
from logbook.core import store
from logbook.core.store import Logbook
store.COMMAND = "sync immich"
lb = Logbook.find()
def drafts():
    for i in range({n}):
        time.sleep({pause})
        yield {{"at": f"2026-09-2{{i % 3}}T07:{{i % 60:02d}}:00Z", "source": "immich", "kind": "photo",
               "tier": 1, "payload": {{"schema": "photo/v1", "raw_id": f"slow:{{i}}"}}}}
print(lb.append_many(drafts()))
"""


def _env(root: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUNBUFFERED"}
    env.update({"LOGBOOK_HOME": str(root), "PYTHONPATH": str(ROOT)})
    return env


def _slow_writer(root: Path, n: int = 6, pause: float = 0.4) -> subprocess.Popen[str]:
    """A writer whose walk takes `n * pause` seconds, in another process; the lock is held from before
    its first draft is asked for."""
    proc = subprocess.Popen(
        [sys.executable, "-c", SLOW_WRITER.format(n=n, pause=pause)],
        env=_env(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
    )
    lock = root / LOCK_FILE
    deadline = time.monotonic() + 20
    while not lock.exists():  # the slow writer has started and holds the lock
        if proc.poll() is not None or time.monotonic() > deadline:
            out, err = proc.communicate()
            raise AssertionError(f"the slow writer did not take the lock: {out!r} {err!r}")
        time.sleep(0.05)
    return proc


def _logbook(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "logbook.cli", *args],
        env=_env(root),
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "Records" / "Logbook"
    monkeypatch.setenv("LOGBOOK_HOME", str(root))
    lb = Logbook.init(root, "Europe/Oslo")
    lb.append_many(_batch("seed", 3, "manual"))
    return root


# -- two processes ------------------------------------------------------------------------------------------


def test_a_second_writer_waits_and_both_batches_chain(root: Path, tmp_path: Path):
    slow = _slow_writer(root)
    fast = _logbook(root, "add", str(_jsonl(tmp_path / "fast.jsonl", _batch("fast", 4))))
    out, err = slow.communicate(timeout=60)
    assert slow.returncode == 0 and out.strip() == "6", (out, err)
    assert fast.returncode == 0, fast.stderr
    assert "another logbook command is writing to this record (sync immich, since 20" in fast.stderr
    assert "); waiting" in fast.stderr
    lb = Logbook(root)
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 3 + 6 + 4
    raw_ids = [line["payload"]["raw_id"] for line in lb.lines()]
    assert raw_ids[3:9] == [f"slow:{i}" for i in range(6)]  # the slow writer's batch first, whole
    assert raw_ids[9:] == [f"fast:{i}" for i in range(4)]  # then the fast one's, chained after it
    assert not (root / LOCK_FILE).exists()


def test_no_wait_refuses_with_exit_2(root: Path, tmp_path: Path):
    slow = _slow_writer(root)
    fast = _logbook(root, "--no-wait", "add", str(_jsonl(tmp_path / "fast.jsonl", _batch("fast", 4))))
    assert fast.returncode == 2
    assert "another logbook command is writing to this record (sync immich, since 20" in fast.stderr
    assert "not waiting" in fast.stderr and "waiting\n" not in fast.stdout
    out, _err = slow.communicate(timeout=60)
    assert slow.returncode == 0 and out.strip() == "6"
    lb = Logbook(root)
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 3 + 6  # nothing of the fast batch


def test_a_stale_lock_is_taken_over_with_one_line(root: Path, tmp_path: Path):
    lock = root / LOCK_FILE
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps({"pid": _dead_pid(), "command": "sync immich", "since": "2026-09-10T06:00:00Z"}),
        encoding="utf-8",
    )
    fast = _logbook(root, "add", str(_jsonl(tmp_path / "fast.jsonl", _batch("fast", 2))))
    assert fast.returncode == 0, fast.stderr
    assert "stale lock" in fast.stderr and "sync immich" in fast.stderr and "taking it over" in fast.stderr
    assert fast.stderr.count("\n") == 1  # one line
    assert "waiting" not in fast.stderr
    assert not lock.exists()
    assert Logbook(root).verify()[2] == []


def _dead_pid() -> int:
    """A pid no process has: a child that has exited, confirmed gone."""
    for _ in range(20):
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()
        if not store._alive(child.pid):
            return child.pid
    pytest.skip("could not find a pid no process has")


def test_a_reader_is_never_blocked(root: Path):
    slow = _slow_writer(root, n=8, pause=0.5)
    started = time.monotonic()
    verify = _logbook(root, "verify")
    day = _logbook(root, "day", "2026-09-10", "--json")
    took = time.monotonic() - started
    assert slow.poll() is None, "the slow writer finished before the readers did; the test proves nothing"
    assert verify.returncode == 0 and "valid" in verify.stdout, verify.stderr
    assert day.returncode == 0, day.stderr
    assert "waiting" not in verify.stderr + day.stderr
    assert took < 4
    slow.communicate(timeout=60)
    assert slow.returncode == 0


# -- the guard: the head re-check ----------------------------------------------------------------------


def test_a_batch_computed_from_a_stale_head_is_never_written(root: Path):
    lb = Logbook(root)
    stale = lb.meta
    after_other: dict[str, Any] = {}

    def drafts() -> Iterator[dict[str, Any]]:
        other = Logbook(root)  # the same process re-enters the lock; the head moves under the slow writer
        other.append_many(_batch("other", 2))
        after_other.update(other.meta)
        yield from _batch("slow", 3)

    with pytest.raises(HeadMoved, match=f"seq {stale['seq']} to seq {after_other.get('seq', 5)}"):
        lb.append_many(drafts())
    seq, head, errors = lb.verify()
    assert errors == [] and (seq, head) == (after_other["seq"], after_other["head"])
    raw_ids = [line["payload"]["raw_id"] for line in lb.lines()]
    assert raw_ids == ["seed:0", "seed:1", "seed:2", "other:0", "other:1"]  # nothing of the stale batch
    assert not (root / LOCK_FILE).exists()


def test_the_lock_is_released_on_the_way_out_and_re_entered_in_process(root: Path):
    lb = Logbook(root)
    lock = root / LOCK_FILE
    with lb.writer("add"):
        assert json.loads(lock.read_text(encoding="utf-8"))["command"] == "add"
        with lb.writer("add"):  # the same process again: held, not waited for
            lb.append("2026-09-10T08:00:00Z", "manual", "note", 1, {"schema": "note/v1", "text": "x"})
        assert lock.exists()
    assert not lock.exists()
    with pytest.raises(RuntimeError), lb.writer("add"):
        raise RuntimeError("the command failed")
    assert not lock.exists()


def test_no_wait_is_a_global_flag(root: Path, capsys: pytest.CaptureFixture[str], monkeypatch):
    monkeypatch.setattr(store, "WAIT", True)  # put back after the test
    cli.main(["--no-wait", "show", "stats"])
    assert store.WAIT is False
    assert "lines" in capsys.readouterr().out
