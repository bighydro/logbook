"""The whole record's people, kept between readings and brought forward by what was appended
(`people.read_whole`, phase 5 of the Library's rebuild): after every day appended, the reading
brought forward is `people.read` of the whole window, field for field (every person's channels,
days together, nights, places, last real contact and tier, the voices counted); and what a delta
cannot carry (a resolution, a retraction, a correction, a day before the last ones read, a changed
setting) reads the whole record again. On the demo month (`logbook demo`: the Oslo persona and the
people around her, who do not exist), appended a day at a time as a nightly sync would."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from logbook.contrib import demo
from logbook.core import people, reading
from logbook.core.index import local_date
from logbook.core.store import Logbook

SEEDS = (1, 2, 3)


@pytest.fixture
def record(tmp_path: Path) -> Iterator[Any]:
    def make(seed: int, days: int = 30, held: int = 8) -> tuple[Logbook, list[list[dict[str, Any]]]]:
        story = demo.story_of(days, seed, "2026-07-01T00:00:00Z")
        drafts = sorted(story.drafts, key=lambda d: str(d["at"]))
        by_day: dict[str, list[dict[str, Any]]] = {}
        for d in drafts:
            by_day.setdefault(local_date(str(d["at"]), demo.TZ), []).append(d)
        ordered = sorted(by_day)
        first = [d for day in ordered[:held] for d in by_day[day]]
        rest = [by_day[day] for day in ordered[held:]]

        def held_only(days_: int, seed_: int, recorded_at: str) -> Any:
            story.drafts[:] = first
            return story

        with mock.patch.object(demo, "story_of", held_only):
            lb = demo.generate(tmp_path / f"Demo-{seed}", days=days, seed=seed)
        return lb, rest

    yield make


def _same(lb: Logbook, found: people.Report | None) -> None:
    """`found` is `people.read` of the whole window, every field the readers read."""
    whole = reading.record_days(lb)
    assert whole is not None and found is not None
    full = people.read(lb, *whole)
    assert json.dumps(found.to_json(), sort_keys=True) == json.dumps(full.to_json(), sort_keys=True)
    assert list(found.known) == list(full.known)
    for entity, person in full.known.items():
        mine = found.known[entity]
        assert mine.real == person.real, entity
        assert mine.tier == person.tier, entity
        assert list(mine.channels) == list(person.channels), entity
        for name, channel in person.channels.items():
            theirs = mine.channels[name]
            assert sorted(theirs.ids) == sorted(channel.ids), (entity, name)
            assert (
                theirs.lines,
                theirs.first,
                theirs.last,
                theirs.tier,
                theirs.last_line,
                theirs.spoke_s,
            ) == (
                channel.lines,
                channel.first,
                channel.last,
                channel.tier,
                channel.last_line,
                channel.spoke_s,
            ), (entity, name)
        assert {k: v.to_json() for k, v in mine.shared.items()} == {
            k: v.to_json() for k, v in person.shared.items()
        }
        assert list(mine.shared) == list(person.shared), (entity, "the order the reading met them")
    assert (found.unnamed, found.not_yet_named) == (full.unnamed, full.not_yet_named)
    assert [p.entity for p in found.people] == [p.entity for p in full.people]


class Count:
    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.whole = 0
        real = people._whole

        def counted(*args: Any, **kwargs: Any) -> Any:
            self.whole += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(people, "_whole", counted)


@pytest.mark.parametrize("seed", SEEDS)
def test_brought_forward_a_day_at_a_time_it_is_the_whole_reading(
    record: Any, seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(seed)
    count = Count(monkeypatch)
    _same(lb, people.read_whole(lb))
    assert count.whole == 1
    for day in rest:
        lb.append_many(day)
        _same(lb, people.read_whole(lb))
    assert count.whole == 1, "every day after the first was brought forward, never read whole"


def test_two_days_at_once_and_none_at_all(record: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    lb, rest = record(1)
    count = Count(monkeypatch)
    people.read_whole(lb)
    lb.append_many([*rest[0], *rest[1]])
    _same(lb, people.read_whole(lb))
    _same(lb, people.read_whole(lb))  # nothing appended: the same reading
    assert count.whole == 1


def _resolution(lb: Logbook) -> None:
    lb.append(
        at="2026-06-20T09:00:00Z",
        source="manual",
        kind="resolution",
        tier=2,
        payload={
            "schema": "resolution/v1",
            "ref": {"kind": "email", "value": "new.friend@example.org"},
            "entity": {"type": "person", "id": "019ea000-0000-7000-8000-00000000f00d", "registry": "logbook"},
            "label": "Nora Nordmann",
            "method": "owner",
        },
    )


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
        event = next(iter(idx.of_kind("event")))
    lb.append(
        at=str(event["at"]),
        end=event.get("end"),
        source=str(event["source"]),
        kind="event",
        tier=int(event["tier"]),
        payload={**event["payload"], "title": "Moved", "supersedes": event["id"]},
    )


def _setting(lb: Logbook) -> None:
    places = lb.root / "places.json"
    data = json.loads(places.read_text(encoding="utf-8")) if places.exists() else {}
    data["The quay"] = {"lat": 59.9, "lon": 10.74, "radius_m": 80}
    places.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("change", [_resolution, _backfill, _correction, _setting])
def test_what_a_delta_cannot_carry_reads_the_whole_record_again(
    record: Any, change: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(2)
    count = Count(monkeypatch)
    people.read_whole(lb)
    lb.append_many(rest[0])
    change(lb)
    _same(lb, people.read_whole(lb))
    assert count.whole == 2, change.__name__


def test_a_kept_reading_that_does_not_read_is_read_whole_again(
    record: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(3)
    people.read_whole(lb)
    (lb.index_path.parent / people.MEMO_FILE).write_bytes(b"{not json")
    count = Count(monkeypatch)
    lb.append_many(rest[0])
    _same(lb, people.read_whole(lb))
    assert count.whole == 1


def test_the_kept_reading_is_beside_the_index_never_in_the_record(record: Any) -> None:
    lb, _rest = record(1)
    people.read_whole(lb)
    path = lb.index_path.parent / people.MEMO_FILE
    assert path.is_file() and lb.root not in path.parents
    if __import__("sys").platform != "win32":
        assert path.stat().st_mode & 0o777 == 0o600


def test_a_stay_longer_than_the_lookback_is_read_back_to_where_it_began(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Forty-five days at home without a move: one stay, begun before the 32 days the track is read
    back, so the track is read back twice as far (`_track_back`); Kari at the dinner every evening, so
    every day is a day together at it. Brought forward a day at a time, it is the whole reading."""
    from datetime import date, timedelta

    from persona import HOME, KARI, KARI_ID, attendee, dwell, event, resolution, utc

    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    start = date(2026, 5, 1)
    days = [(start + timedelta(days=n)).isoformat() for n in range(45)]

    def day_of(day: str) -> list[dict[str, Any]]:
        dinner = event(utc(day, "19:00"), utc(day, "21:00"), "Dinner", [attendee(KARI["email"], "Kari")])
        return [*dwell(day, "00:00", "24:00", HOME, every_min=60), dinner]

    lb.append_many(
        [
            resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
            *[d for day in days[:40] for d in day_of(day)],
        ]
    )
    count = Count(monkeypatch)
    _same(lb, people.read_whole(lb))
    looked: list[str] = []
    real = people.reading.owner_track

    def tracked(lb_: Logbook, first: str, last: str, airports: Any = None) -> Any:
        looked.append(first)
        return real(lb_, first, last, airports)

    monkeypatch.setattr(people.reading, "owner_track", tracked)
    for day in days[40:]:
        lb.append_many(day_of(day))
        found = people.read_whole(lb)
        _same(lb, found)
        assert found is not None and len(found.known[KARI_ID].days) == days.index(day) + 1
    assert count.whole == 1
    assert days[0] in looked, "read back to where the stay began"


def test_a_day_that_arrives_after_the_next_one_is_still_the_whole_reading(
    record: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A phone that syncs late: the messages of a day arrive after the next day's lines, inside the
    days read again (`MARGIN_DAYS`). Brought forward, it is the whole reading."""
    lb, rest = record(1)
    count = Count(monkeypatch)
    people.read_whole(lb)
    for today, yesterday in zip(rest[1::2], rest[0::2], strict=False):
        late = [d for d in yesterday if d["kind"] in ("message", "call")]
        lb.append_many([d for d in yesterday if d not in late])
        lb.append_many(today)
        lb.append_many(late)
        _same(lb, people.read_whole(lb))
    assert count.whole == 1
