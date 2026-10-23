"""The last real contacts of the whole record, kept between readings (`people_drift.real_contacts` over
`people.read_whole`'s window, `people_drift._kept`): after every day appended, across a month's end, and
with a day that arrives after the next one, it names the contact the reading of every line names, for
every person; a resolution, a retraction, a corrected line or a backfill into a month already kept reads
the whole record again. On the demo's 45 days from June into July (the Oslo persona, who does not exist)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from logbook.contrib import demo, people_drift
from logbook.core import people
from logbook.core.index import local_date
from logbook.core.store import Logbook


@pytest.fixture
def record(tmp_path: Path) -> Iterator[Any]:
    def make(seed: int, days: int = 45, held: int = 20) -> tuple[Logbook, list[list[dict[str, Any]]]]:
        story = demo.story_of(days, seed, "2026-08-01T00:00:00Z")
        drafts = sorted(story.drafts, key=lambda d: str(d["at"]))
        by_day: dict[str, list[dict[str, Any]]] = {}
        for d in drafts:
            by_day.setdefault(local_date(str(d["at"]), demo.TZ), []).append(d)
        ordered = sorted(by_day)
        first = [d for day in ordered[:held] for d in by_day[day]]

        def held_only(days_: int, seed_: int, recorded_at: str) -> Any:
            story.drafts[:] = first
            return story

        with mock.patch.object(demo, "story_of", held_only):
            lb = demo.generate(tmp_path / f"Demo-{seed}", days=days, seed=seed)
        return lb, [by_day[day] for day in ordered[held:]]

    yield make


class Count:
    """The month files each reading of the messages was asked for."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.files: list[tuple[str | None, str | None]] = []
        from logbook.core import index

        original = index.Index.of_kind

        def of_kind(idx: Any, kind: str, *args: Any, **kwargs: Any) -> Any:
            if kind == "message":
                self.files.append(kwargs.get("files", (None, None)))
            return original(idx, kind, *args, **kwargs)

        monkeypatch.setattr(index.Index, "of_kind", of_kind)


def _same(lb: Logbook) -> None:
    report = people.read_whole(lb)
    assert report is not None
    assert people_drift.real_contacts(lb, report) == people_drift._read(lb, report)


@pytest.mark.parametrize("seed", (1, 2))
def test_a_day_at_a_time_across_a_month_s_end_it_names_the_same_contacts(
    record: Any, seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(seed)
    _same(lb)
    count = Count(monkeypatch)
    for day in rest:
        lb.append_many(day)
        _same(lb)
    kept_reads = [f for f in count.files if f != (None, None)]
    assert kept_reads and all(f[0] for f in kept_reads[-2:]), (
        "the last readings read from a month on, not every file"
    )


def test_a_day_that_arrives_after_the_next_one(record: Any) -> None:
    lb, rest = record(1)
    _same(lb)
    for today, yesterday in zip(rest[1::2], rest[0::2], strict=False):
        late = [d for d in yesterday if d["kind"] in ("message", "call")]
        lb.append_many([d for d in yesterday if d not in late])
        lb.append_many(today)
        lb.append_many(late)
        _same(lb)


def _backfill(lb: Logbook) -> None:
    lb.append(
        at="2026-06-02T10:00:00Z",
        source="ios-calls",
        kind="call",
        tier=1,
        payload={
            "schema": "call/v1",
            "raw_id": "c-backfilled",
            "direction": "incoming",
            "answered": True,
            "duration_s": 60,
            "counterparty": {"kind": "phone", "value": "+447700900001"},
        },
    )


def _correction(lb: Logbook) -> None:
    with lb.index() as idx:
        call = next(iter(idx.of_kind("call")))
    lb.append(
        at=str(call["at"]),
        source=str(call["source"]),
        kind="call",
        tier=int(call["tier"]),
        payload={
            **call["payload"],
            "answered": not call["payload"].get("answered"),
            "supersedes": call["id"],
        },
    )


def _retraction(lb: Logbook) -> None:
    with lb.index() as idx:
        call = next(iter(idx.of_kind("call")))
    lb.retract(int(call["seq"]), "a wrong number")


@pytest.mark.parametrize("change", [_backfill, _correction, _retraction])
def test_what_a_kept_month_cannot_carry_reads_the_whole_record(record: Any, change: Any) -> None:
    lb, rest = record(2)
    _same(lb)
    lb.append_many(rest[0])
    change(lb)
    _same(lb)
