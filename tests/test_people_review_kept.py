"""The observed people of the whole record, kept between readings (`people_review._folds`): each kind's
counterparts in file order, read on from where they stopped, are the reading of every line, row for
row, after every day appended; a line into an earlier month, a correction, a retraction or a resolution
reads every line again. On the demo month (the Oslo persona and the people around her, who do not
exist)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from logbook.contrib import demo, people_review
from logbook.core import index, kept
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


class Whole:
    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.n = 0
        real = index.Index.of_kind

        def of_kind(idx: Any, kind: str, *args: Any, **kwargs: Any) -> Any:
            if kind == "message" and kwargs.get("after_seq") is None and not args:
                self.n += 1
            return real(idx, kind, *args, **kwargs)

        monkeypatch.setattr(index.Index, "of_kind", of_kind)

    def take(self) -> int:
        n, self.n = self.n, 0
        return n


def _rows(lb: Logbook) -> list[dict[str, Any]]:
    with lb.index() as idx:
        return [o._row() for o in people_review.build(lb, idx)]


def _same(lb: Logbook, whole: Whole | None = None) -> int:
    if whole is not None:
        whole.take()
    found = _rows(lb)
    n = whole.take() if whole is not None else 0
    with mock.patch.object(kept, "load", return_value=None):
        assert found == _rows(lb)
    assert found, "the demo has people"
    return n


@pytest.mark.parametrize("seed", (1, 2))
def test_a_day_at_a_time_the_observed_people_are_every_line_s(
    record: Any, seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(seed)
    _same(lb)
    whole = Whole(monkeypatch)
    for day in rest:
        lb.append_many(day)
        assert _same(lb, whole) == 0, "read on from where it stopped"


def _earlier_month(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("message")))
    lb.append(
        at="2026-05-20T10:00:00Z",  # a month file before the last one read
        source=str(line["source"]),
        kind="message",
        tier=int(line["tier"]),
        payload={**line["payload"], "raw_id": "late-one"},
    )


def _correction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("message")))
    lb.append(
        at=str(line["at"]),
        source=str(line["source"]),
        kind="message",
        tier=int(line["tier"]),
        payload={**line["payload"], "text": "corrected", "supersedes": line["id"]},
    )


def _retraction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("message")))
    lb.retract(int(line["seq"]), "not mine")


def _resolution(lb: Logbook) -> None:
    lb.append(
        at="2026-07-20T09:00:00Z",
        source="manual",
        kind="resolution",
        tier=2,
        payload={
            "schema": "resolution/v1",
            "ref": {"kind": "phone", "value": "+447700900042"},
            "entity": {"type": "person", "id": "019ea000-0000-7000-8000-00000000f00d", "registry": "logbook"},
            "label": "Nora Nordmann",
            "method": "owner",
        },
    )


@pytest.mark.parametrize("change", [_earlier_month, _correction, _retraction, _resolution])
def test_what_a_kept_reading_cannot_carry_reads_every_line(
    record: Any, change: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(1)
    _same(lb)
    lb.append_many(rest[0])
    change(lb)
    whole = Whole(monkeypatch)
    assert _same(lb, whole) == 1, change.__name__
