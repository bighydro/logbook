"""The world's years, kept between readings (`world._Years`): a part of the window before its last is
taken from beside the index while no line has come for its days since, and the page is the page read
from every line, byte for byte, after every day appended, a day that arrives after the next one, a
backfill into a kept part, a retraction, a changed setting and another gate. The window is cut ten days
at a time here (the page cuts it a calendar year at a time), so the demo's 45 days (the Oslo persona,
who does not exist) hold parts enough to keep.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from logbook.contrib import demo, world
from logbook.core import policy, reading
from logbook.core.index import local_date
from logbook.core.store import Logbook


def _ten_days(req: world.Request) -> list[tuple[str, str]]:
    a, b = date.fromisoformat(req.first), date.fromisoformat(req.last)
    out = []
    while a <= b:
        end = min(b, a + timedelta(days=9))
        out.append((a.isoformat(), end.isoformat()))
        a = end + timedelta(days=1)
    return out


@pytest.fixture(autouse=True)
def ten_day_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(world.Request, "chunks", property(_ten_days))


@pytest.fixture
def record(tmp_path: Path) -> Iterator[Any]:
    def make(seed: int, days: int = 45, held: int = 25) -> tuple[Logbook, list[list[dict[str, Any]]]]:
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
        path = policy.policy_path(lb.root)  # the owner's world entry: tiers 1 and 2 may be shown (S9)
        data = policy.read(lb.root)
        data[policy.WORLD_DESTINATION] = {"max_tier": 2}
        path.write_text(json.dumps(data), encoding="utf-8")
        return lb, [by_day[day] for day in ordered[held:]]

    yield make


class Reads:
    """The parts each page read from the lines."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.parts: list[tuple[str, str]] = []
        real = reading.read

        def counted(lb: Logbook, first: str, last: str, *args: Any, **kwargs: Any) -> Any:
            self.parts.append((first, last))
            return real(lb, first, last, *args, **kwargs)

        monkeypatch.setattr(reading, "read", counted)

    def take(self) -> list[tuple[str, str]]:
        found, self.parts[:] = list(self.parts), []
        return found


def _page(lb: Logbook, tiers: tuple[int, ...] | None = None) -> world.Build:
    req = world.request(lb, tiers=tiers)
    assert req is not None
    return world.build(lb, req)


def _parts(lb: Logbook) -> list[tuple[str, str]]:
    req = world.request(lb)
    assert req is not None
    return _ten_days(req)


def _same(lb: Logbook, tiers: tuple[int, ...] | None = None, reads: Reads | None = None) -> world.Build:
    """The page with the kept parts is the page read from every line; `reads` then holds the parts
    the kept one read."""
    with mock.patch.object(world._Years, "load", return_value=None):
        whole = _page(lb, tiers)
    if reads is not None:
        reads.take()
    kept = _page(lb, tiers)
    assert kept.json == whole.json
    assert (kept.logged, kept.crossed, kept.by_kind, kept.held_by_kind) == (
        whole.logged,
        whole.crossed,
        whole.by_kind,
        whole.held_by_kind,
    )
    return kept


def test_a_day_at_a_time_the_page_is_the_page_of_every_line(
    record: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(1)
    reads = Reads(monkeypatch)
    _same(lb, reads=reads)
    assert reads.take() == _parts(lb), "the first page reads every part"
    _same(lb, reads=reads)
    assert reads.take() == _parts(lb)[-1:], "nothing appended: the last part alone is read"
    for day in rest:
        lb.append_many(day)
        page = _same(lb, reads=reads)
        assert len(reads.take()) <= 2, "a day reads its own part again and the last, at most"
    assert json.loads(page.json)["stays"], "the demo's stays are on the page"


def test_a_day_that_arrives_after_the_next_one(record: Any) -> None:
    lb, rest = record(2)
    _same(lb)
    for today, yesterday in zip(rest[1::2], rest[0::2], strict=False):
        lb.append_many(today)
        _same(lb)
        lb.append_many(yesterday)
        _same(lb)


def test_a_backfill_into_a_kept_part_reads_that_part_again(
    record: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, _rest = record(1)
    _same(lb)
    with lb.index() as idx:
        point = next(line for line in idx.of_kind("location") if not line["payload"].get("subject"))
    reads = Reads(monkeypatch)
    at = datetime.fromisoformat(str(point["at"]).replace("Z", "+00:00")) + timedelta(minutes=1)
    lb.append(
        at=at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        source=str(point["source"]),
        kind="location",
        tier=int(point["tier"]),
        payload={**point["payload"], "lat": 59.95, "lon": 10.7},
    )
    _same(lb, reads=reads)
    assert reads.take() == [_parts(lb)[0], _parts(lb)[-1]], "the backfill's part, and the last"


def _retraction(lb: Logbook) -> None:
    with lb.index() as idx:
        point = next(iter(idx.of_kind("location")))
    lb.retract(int(point["seq"]), "a wrong fix")


def _places_moved(lb: Logbook) -> None:
    path = lb.root / "places.json"
    places = json.loads(path.read_text(encoding="utf-8"))
    for value in places.values():
        value["radius_m"] = float(value.get("radius_m") or 150) * 2
    path.write_bytes(json.dumps(places).encode("utf-8"))


@pytest.mark.parametrize("change", [_retraction, _places_moved])
def test_what_every_part_reads_by_reads_them_all_again(
    record: Any, change: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(2)
    _same(lb)
    lb.append_many(rest[0])
    change(lb)
    reads = Reads(monkeypatch)
    _same(lb, reads=reads)
    assert reads.take() == _parts(lb), change.__name__


def test_another_gate_is_its_own_page(record: Any) -> None:
    lb, rest = record(1)
    _same(lb, (1, 2))
    _same(lb, (1,))
    lb.append_many(rest[0])
    _same(lb, (1,))
    _same(lb, (1, 2))


def test_a_journey_s_page_is_read_from_its_lines(record: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    lb, _rest = record(1)
    _same(lb)
    loaded = mock.MagicMock(side_effect=AssertionError("a journey's page keeps nothing"))
    monkeypatch.setattr(world._Years, "load", loaded)
    req = world.request(lb)
    assert req is not None
    world.build(
        lb, world.Request(req.first, req.last, req.tiers, req.max_tier, world.Journey("trip:x", None, "x"))
    )
