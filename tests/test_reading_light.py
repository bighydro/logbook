"""A reading made from the index's own columns (`reading.read(..., kinds=)`): the stays, the folded stays,
the nights and the owner's stays of every subject's track, and its points, are the reading of every
line's, field for field; its lines are only those of the kinds asked for. The world reads its years this
way (`world._Builder`). On the demo month (the Oslo persona and the people around her, who do not
exist) and on the world's long weekend (`tests/world_record.py`), through every gate, with a point
right after a window retracted."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from logbook.contrib import demo
from logbook.core import reading, stays
from logbook.core.store import Logbook

KINDS = ("journey", "trip", "photo")


def _points(rd: reading.Reading) -> list[stays.Point]:
    """The window's points of every subject, as `stays.derive` takes them from the lines."""
    tracks, _evidence = stays._split(rd.lines)
    return sorted((p for track in tracks.values() for p in track), key=lambda p: (p.at, p.seq))


def _same(lb: Logbook, first: str, last: str, tiers: tuple[int, ...] | None = None) -> None:
    full = reading.read(lb, first, last, tiers=tiers)
    light = reading.read(lb, first, last, tiers=tiers, kinds=KINDS)
    assert light.derived.segments == full.derived.segments
    assert light.derived.folded == full.derived.folded
    assert light.derived.noise_points == full.derived.noise_points
    assert light.nights == full.nights and light.nights_after == full.nights_after
    assert light.owner_stays == full.owner_stays
    assert light.points is not None
    assert sorted(light.points, key=lambda p: (p.at, p.seq)) == _points(full)
    assert light.lines == [line for line in full.lines if line["kind"] in KINDS]


@pytest.fixture(scope="module")
def demo_lb(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    return demo.generate(tmp_path_factory.mktemp("light") / "Demo", days=30, seed=2)


@pytest.mark.parametrize("tiers", (None, (1,), (1, 2)))
@pytest.mark.parametrize(
    "window", (("2026-06-01", "2026-06-30"), ("2026-06-05", "2026-06-11"), ("2026-06-13", "2026-06-13"))
)
def test_the_demo_s_stays_from_the_index_are_the_lines(demo_lb: Logbook, window: Any, tiers: Any) -> None:
    _same(demo_lb, *window, tiers)


def test_the_world_s_weekend_from_the_index_is_the_lines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from world_record import DAYS, world_record

    lb = world_record(tmp_path, monkeypatch)
    for tiers in (None, (1, 2)):
        _same(lb, DAYS[0], DAYS[-1], tiers)
        _same(lb, DAYS[1], DAYS[2], tiers)


def test_a_retracted_point_right_after_the_window_is_none(tmp_path: Path) -> None:
    lb = demo.generate(tmp_path / "Demo", days=6, seed=1)
    with lb.index() as idx:
        after = [
            line
            for line in idx.of_kind("location", "2026-06-04", "2026-06-05")
            if not line["payload"].get("subject")
        ]
    end = reading._window(
        reading.day_start.of(lb.meta), "2026-06-01", "2026-06-03", stays.read_settings(lb.root)
    )[1]
    first = min((line for line in after if stays.instant(line["at"]) >= end), key=lambda line: line["at"])
    lb.retract(int(first["seq"]), "a wrong fix")
    _same(lb, "2026-06-01", "2026-06-03")


def _world_same(lb: Logbook) -> None:
    from unittest import mock

    from logbook.contrib import world

    with mock.patch.object(world._Years, "load", return_value=None):
        for tiers in (None, (1,)):
            req = world.request(lb, tiers=tiers)
            assert req is not None
            light = world.build(lb, req)
            with mock.patch.object(world, "READ_KINDS", None):
                full = world.build(lb, req)
            assert light.json == full.json
            assert (light.logged, light.crossed, light.by_kind) == (full.logged, full.crossed, full.by_kind)


def test_the_world_read_from_the_index_is_the_world_read_from_the_lines(
    demo_lb: Logbook, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from world_record import world_record

    _world_same(demo_lb)
    _world_same(world_record(tmp_path, monkeypatch))


def test_the_world_counts_every_line_of_its_window_from_the_index(tmp_path: Path) -> None:
    """`Index.window_tally`, which counts in one statement the lines whose stamp is plainly inside the
    window, and hands back those at its edges and any stamp not in UTC, counts as the lines do."""
    from collections import Counter

    from logbook.contrib import world

    lb = demo.generate(tmp_path / "Demo", days=8, seed=3)
    for at in ("2026-06-03T08:00:00+02:00", "2026-06-08T21:59:59.999Z", "2026-06-02T12:00:00.25Z"):
        lb.append(at=at, source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": at})
    req = world.request(lb, "2026-06-02", "2026-06-08", (1,))
    assert req is not None
    built = world.build(lb, req)
    start, end = (
        world.day_start.of(lb.meta).span("2026-06-02")[0],
        world.day_start.of(lb.meta).span("2026-06-08")[1],
    )
    logged, by_kind, held = 0, Counter[str](), Counter[str]()
    with lb.index() as idx:
        for place in idx.window(stays.instant_text(start), stays.instant_text(end)):
            at = stays.instant(place.at)
            if place.kind == "retraction" or at is None or not start <= at < end:
                continue
            logged += 1
            (by_kind if place.tier == 1 else held)[place.kind] += 1
    assert (built.logged, built.by_kind, built.held_by_kind) == (
        logged,
        dict(sorted(by_kind.items())),
        dict(sorted(held.items())),
    )
