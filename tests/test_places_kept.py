"""The observed places of the whole record, kept between readings (`places_review._kept`): the owner's
stays, brought forward from a little before the last days read (the whole track's stays after the first
one the track read from there are the same), and the names the lines give, read on from where they
stopped and merged where their lines stand; the clusters and their names are the reading of every line,
row for row, after every day appended, as the days come to a calendar's events written ahead; a
retraction, a correction and a point into a day read already read every line again. On the demo month
(the Oslo persona and the places she goes, which do not exist)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from logbook.contrib import demo, places_review
from logbook.core import kept, reading
from logbook.core.index import local_date
from logbook.core.store import Logbook


@pytest.fixture(autouse=True)
def short_lookback(monkeypatch: pytest.MonkeyPatch) -> None:
    """A track read back four days, then eight, so a month's record splices (the record's is a month)."""
    monkeypatch.setattr(places_review, "LOOKBACK_DAYS", 4)
    monkeypatch.setattr(places_review, "LOOKBACK_MOST", 16)


@pytest.fixture
def record(tmp_path: Path) -> Iterator[Any]:
    def make(seed: int, days: int = 30, held: int = 10) -> tuple[Logbook, list[list[dict[str, Any]]]]:
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
        return lb, [by_day[day] for day in ordered[held:]]

    yield make


class Whole:
    """How many readings of the owner's track read it from the record's first day."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.n = 0
        real = reading.owner_track

        def counted(lb: Logbook, first: str, *args: Any, **kwargs: Any) -> Any:
            span = reading.record_days(lb, "location")
            self.n += span is not None and first == span[0]
            return real(lb, first, *args, **kwargs)

        monkeypatch.setattr(reading, "owner_track", counted)

    def take(self) -> int:
        n, self.n = self.n, 0
        return n


def _same(lb: Logbook, whole: Whole | None = None) -> int:
    if whole is not None:
        whole.take()
    found = [o._row() for o in places_review.build(lb)]
    n = whole.take() if whole is not None else 0
    with mock.patch.object(kept, "load", return_value=None):
        assert found == [o._row() for o in places_review.build(lb)]
    assert found, "the demo has places"
    return n


def _ahead(day: str, n: int) -> dict[str, Any]:
    return {
        "at": f"{day}T10:00:00Z",
        "end": f"{day}T11:30:00Z",
        "source": "google-calendar",
        "kind": "event",
        "tier": 2,
        "payload": {
            "schema": "event/v1",
            "raw_id": f"ahead-{n}",
            "title": "Harbour board",
            "location": "Harbour office, Oslo",
            "all_day": False,
        },
    }


@pytest.mark.parametrize("seed", (1, 2))
def test_a_day_at_a_time_the_places_are_every_line_s(
    record: Any, seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(seed)
    days = sorted({local_date(str(d[0]["at"]), demo.TZ) for d in rest})
    lb.append_many([_ahead(day, n) for n, day in enumerate(days[3::4])])  # the calendar, ahead
    _same(lb)
    whole = Whole(monkeypatch)
    for day in rest:
        lb.append_many(day)
        assert _same(lb, whole) == 0, "the kept stays were brought forward"


def _retraction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("location")))
    lb.retract(int(line["seq"]), "a wrong fix")


def _backfill(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("location")))
    lb.append(
        at="2026-06-02T03:00:00Z",
        source=str(line["source"]),
        kind="location",
        tier=int(line["tier"]),
        payload={**line["payload"], "raw_id": "late-fix", "lat": 59.95, "lon": 10.7},
    )


def _correction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(p for p in idx.of_kind("photo"))
    lb.append(
        at=str(line["at"]),
        source=str(line["source"]),
        kind="photo",
        tier=int(line["tier"]),
        payload={**line["payload"], "supersedes": line["id"]},
    )


@pytest.mark.parametrize("change", [_retraction, _backfill, _correction])
def test_what_kept_places_cannot_carry_reads_every_line(
    record: Any, change: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(1)
    _same(lb)
    lb.append_many(rest[0])
    change(lb)
    whole = Whole(monkeypatch)
    assert _same(lb, whole) == 1, change.__name__
