"""Logbook.append_many at scale: one dedupe set, open file handles, the chain in memory,
logbook.json every META_EVERY lines, and a valid chain after an interruption."""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from logbook import store
from logbook.store import Logbook


def _draft(i: int, source: str = "dawarich") -> dict[str, Any]:
    # two months, so a batch keeps more than one file open
    month = "04" if i % 2 else "05"
    return {
        "at": f"2026-{month}-12T05:{i % 60:02d}:00Z",
        "source": source,
        "kind": "location",
        "tier": 1,
        "payload": {"schema": "location/v1", "lat": 59.9, "lon": 10.7, "raw_id": f"t:{i}"},
    }


def _drafts(n: int) -> list[dict[str, Any]]:
    return [_draft(i) for i in range(n)]


# -- batching -------------------------------------------------------------------


def test_append_many_writes_meta_every_meta_every_lines_and_at_the_end(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "META_EVERY", 5)
    lb = Logbook.init(tmp_path / "lb", "UTC")
    saves: list[int] = []
    original = Logbook._save_meta

    def counting(self: Logbook, meta: dict[str, Any]) -> None:
        saves.append(meta["seq"])
        original(self, meta)

    monkeypatch.setattr(Logbook, "_save_meta", counting)
    assert lb.append_many(_drafts(23)) == 23
    assert saves == [5, 10, 15, 20, 23]
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 23


def test_append_many_lines_are_in_import_order_across_month_files(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    lb.append_many(_drafts(10))
    raw_ids = [line["payload"]["raw_id"] for line in lb.lines()]
    assert raw_ids == [f"t:{i}" for i in range(10)]  # chain order is import order, not `at` order
    assert len(lb.files()) == 2


def test_append_many_dedupes_against_the_log_and_within_the_batch(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    assert lb.append_many(_drafts(4)) == 4
    again = [*_drafts(6), _draft(5), _draft(2, source="owntracks")]
    assert lb.append_many(again) == 3  # t:4, t:5, and t:2 from the other source
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 7


def test_append_many_reports_progress_every_progress_every_lines(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "PROGRESS_EVERY", 4)
    lb = Logbook.init(tmp_path / "lb", "UTC")
    seen: list[tuple[int, float]] = []
    lb.append_many(_drafts(10), progress=lambda n, elapsed: seen.append((n, elapsed)))
    assert [n for n, _ in seen] == [4, 8]
    assert all(elapsed >= 0 for _, elapsed in seen)


# -- crash safety -----------------------------------------------------------------


def _interrupted(n: int, after: int) -> Iterator[dict[str, Any]]:
    for d in _drafts(n):
        if d["payload"]["raw_id"] == f"t:{after}":
            raise KeyboardInterrupt
        yield d


def test_interrupted_import_leaves_a_valid_chain_and_can_be_resumed(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "META_EVERY", 5)
    lb = Logbook.init(tmp_path / "lb", "UTC")
    with pytest.raises(KeyboardInterrupt):
        lb.append_many(_interrupted(30, after=12))
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 12  # everything written before the interruption is kept
    assert lb.append_many(_drafts(30)) == 18  # re-adding the same export finishes the job
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 30


def test_disk_state_between_checkpoints_is_a_valid_chain(tmp_path, monkeypatch):
    """A kill -9 can strike between checkpoints: what is on disk at that moment must verify,
    so lines and logbook.json only ever change together, at a checkpoint."""
    monkeypatch.setattr(store, "META_EVERY", 5)
    root = tmp_path / "lb"
    lb = Logbook.init(root, "UTC")
    snapshots: list[tuple[int, list[str]]] = []

    def drafts() -> Iterator[dict[str, Any]]:
        for i, d in enumerate(_drafts(13)):
            if i in (7, 12):  # mid-checkpoint moments
                seq, _head, errors = Logbook(root).verify()
                snapshots.append((seq, errors))
            yield d

    lb.append_many(drafts())
    assert snapshots == [(5, []), (10, [])]
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 13


def test_append_after_a_batch_continues_the_chain(tmp_path):
    lb = Logbook.init(tmp_path / "lb", "UTC")
    lb.append_many(_drafts(3))
    line = lb.append(
        at="2026-06-01T00:00:00Z",
        source="manual",
        kind="note",
        tier=2,
        payload={"schema": "note/v1", "text": "after the batch"},
    )
    assert line["seq"] == 4
    seq, _head, errors = lb.verify()
    assert errors == [] and seq == 4
    meta = json.loads((tmp_path / "lb" / "logbook.json").read_text())
    assert meta["seq"] == 4 and meta["head"] == line["hash"]
