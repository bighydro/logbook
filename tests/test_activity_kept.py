"""The record's activity by source, kept between readings (`gaps.activity_of`): the lines, the first and
last stamps, the days with a line and the longest silence of every source are `Index.activity`'s, after
every day appended, as the days move past lines written ahead of them (a calendar's coming events), and
with a line written into a source's past (read again whole); of equal silences, the first. On the demo
month (the Oslo persona, who does not exist)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from logbook.contrib import demo, gaps
from logbook.core import index, kept
from logbook.core.index import local_date
from logbook.core.store import Logbook


@pytest.fixture
def record(tmp_path: Path) -> Iterator[Any]:
    def make(
        seed: int, days: int = 24, held: int = 10
    ) -> tuple[Logbook, list[str], list[list[dict[str, Any]]]]:
        story = demo.story_of(days, seed, "2026-07-01T00:00:00Z")
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
        return lb, ordered[held:], [by_day[day] for day in ordered[held:]]

    yield make


class Whole:
    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.n = 0
        real = index.Index.activity

        def counted(idx: Any, *args: Any) -> Any:
            self.n += 1
            return real(idx, *args)

        monkeypatch.setattr(index.Index, "activity", counted)

    def take(self) -> int:
        n, self.n = self.n, 0
        return n


def _same(lb: Logbook, today: str, whole: Whole | None = None) -> int:
    if whole is not None:
        whole.take()
    found = gaps.activity_of(lb, "", today)
    n = whole.take() if whole is not None else 0
    with lb.index() as idx:
        assert found == idx.activity("", today)
    with mock.patch.object(kept, "load", return_value=None):
        assert gaps.activity_of(lb, "", today) == found
    return n


def _event_ahead(day: str, n: int) -> dict[str, Any]:
    return {
        "at": f"{day}T09:00:00Z",
        "end": f"{day}T10:00:00Z",
        "source": "google-calendar",
        "kind": "event",
        "tier": 2,
        "payload": {
            "schema": "event/v1",
            "raw_id": f"ahead-{n}",
            "title": "Harbour board",
            "location": "Oslo",
        },
    }


@pytest.mark.parametrize("seed", (1, 2))
def test_a_day_at_a_time_the_activity_is_every_line_s(
    record: Any, seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, days, rest = record(seed)
    lb.append_many([_event_ahead(day, n) for n, day in enumerate(days[2::3])])  # the calendar, ahead
    _same(lb, days[0])
    whole = Whole(monkeypatch)
    for day, lines in zip(days, rest, strict=True):
        lb.append_many(lines)
        assert _same(lb, day, whole) == 0, "brought forward"


def test_a_line_into_a_source_s_past_reads_every_line(record: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    lb, days, rest = record(1)
    _same(lb, days[0])
    lb.append_many(rest[0])
    first = rest[0][0]
    lb.append(
        at="2026-06-02T03:00:00Z",
        source=str(first["source"]),
        kind=str(first["kind"]),
        tier=int(first["tier"]),
        payload={**first["payload"], "raw_id": "late-one"},
    )
    whole = Whole(monkeypatch)
    assert _same(lb, days[1], whole) == 1


def test_of_equal_silences_the_first(tmp_path: Path) -> None:
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    for n, at in enumerate(("2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z", "2026-06-01T14:00:00Z")):
        lb.append(at=at, source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": f"n{n}"})
    with lb.index() as idx:
        [row] = idx.activity("", "2026-06-02")
    assert row["stretch"] == ("2026-06-01T10:00:00Z", "2026-06-01T12:00:00Z")
