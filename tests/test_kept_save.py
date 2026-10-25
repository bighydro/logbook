"""A kept reading moved into place whole when two threads of one process save it at once (`kept.save`):
`logbook serve` answers on threads, and two requests for Today at once each save the promises' kept
reading. Each thread writes its own temporary file, so neither moves the other's bytes, and on
Windows neither moves a file the other still holds open. A save that cannot finish, its temporary
file held by someone else as well, leaves the reading unsaved and raises nothing: the next reading
reads the record again. No record is needed; the file holds synthetic data."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest

from logbook.core import kept


def test_two_threads_saving_at_once_each_move_their_own_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    at = tmp_path / "promises-whole.json"
    both_written = threading.Barrier(2, timeout=10)
    moved: dict[str, bytes] = {}
    real_replace = os.replace

    def replace(src: Any, dst: Any) -> None:
        both_written.wait()  # each thread has written its file before either moves one
        moved[threading.current_thread().name] = Path(src).read_bytes()
        both_written.wait()
        real_replace(src, dst)

    monkeypatch.setattr(kept.os, "replace", replace)
    data = {name: {"seq": n, "proposals": [name] * (n + 1)} for n, name in enumerate(("first", "second"))}
    threads = [threading.Thread(target=kept.save, args=(at, data[name]), name=name) for name in data]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert {name: json.loads(found) for name, found in moved.items()} == data
    assert json.loads(at.read_bytes()) in data.values()
    assert [p.name for p in tmp_path.iterdir()] == [at.name], "no temporary file left behind"


def test_a_save_that_cannot_move_its_file_or_remove_it_raises_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows' refusal, both times: the file is in use by another process (WinError 32)."""
    at = tmp_path / "promises-whole.json"

    def in_use(*_: Any, **__: Any) -> None:
        raise PermissionError(32, "The process cannot access the file because it is being used")

    monkeypatch.setattr(kept.os, "replace", in_use)
    monkeypatch.setattr(Path, "unlink", in_use)
    kept.save(at, {"seq": 1})
    assert not at.exists()
