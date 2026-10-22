"""The whole record's promises, kept between readings (`promises.extract` with every argument its
default, `promises._kept`): after every day appended, a backfilled one among them, the kept reading
is `extract`'s own, proposal for proposal and in the order it counts what it skipped; a task that
closes a promise, and a signed day that disposes of one, close it at once; and a resolution, a
retraction or a corrected line reads the whole record again. On the demo month (`logbook demo`: the
Oslo persona and the people around her, who do not exist), appended a day at a time."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from logbook.contrib import demo, promises
from logbook.core.index import local_date
from logbook.core.store import Logbook


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

        def held_only(days_: int, seed_: int, recorded_at: str) -> Any:
            story.drafts[:] = first
            return story

        with mock.patch.object(demo, "story_of", held_only):
            lb = demo.generate(tmp_path / f"Demo-{seed}", days=days, seed=seed)
        return lb, [by_day[day] for day in ordered[held:]]

    yield make


class Count:
    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.whole = 0
        real = promises._extract

        def counted(*args: Any, **kwargs: Any) -> Any:
            if kwargs.get("after_seq") is None:
                self.whole += 1
            return real(*args, **kwargs)

        monkeypatch.setattr(promises, "_extract", counted)


def _said(text: str, at: str) -> dict[str, Any]:
    return {
        "at": at,
        "source": "manual",
        "kind": "note",
        "tier": 2,
        "payload": {"schema": "note/v1", "text": text},
    }


def _same(lb: Logbook) -> promises.Report:
    kept = promises.extract(lb)
    whole, _skipped = promises._extract(lb)
    assert kept.proposals == whole.proposals
    assert list(kept.skipped.items()) == list(whole.skipped.items())
    assert (kept.owner, kept.sources, kept.since, kept.extractor) == (
        whole.owner,
        whole.sources,
        whole.since,
        whole.extractor,
    )
    return kept


@pytest.mark.parametrize("seed", (1, 2, 3))
def test_brought_forward_a_day_at_a_time_it_is_extract_s_own(
    record: Any, seed: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(seed)
    count = Count(monkeypatch)
    _same(lb)
    assert count.whole == 2, "the kept reading, and the test's own whole one"
    for day in rest:
        lb.append_many([*day, _said("I'll send Ola the harbour map tomorrow.", str(day[0]["at"]))])
        _same(lb)
    assert count.whole == 2 + len(rest), "every kept reading after the first was brought forward"


def test_a_backfilled_day_is_brought_forward_and_a_task_closes_its_promise(
    record: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, _rest = record(1)
    promises.extract(lb)
    count = Count(monkeypatch)
    lb.append_many([_said("I will call the yard on Monday.", "2026-06-02T09:00:00Z")])  # a day long read
    found = _same(lb)
    assert count.whole == 1, "the test's own: the kept one was brought forward"
    [called] = [p for p in found.proposals if "call the yard" in p.match.quote]
    assert called.status == "open"
    task = lb.append(
        at="2026-06-10T09:00:00Z",
        source="manual",
        kind="task",
        tier=2,
        payload={
            "schema": "task/v1",
            "raw_id": "done-the-yard",
            "title": "Call the yard",
            "status": "done",
            "extra": {"promise": called.id},
        },
    )
    closed = _same(lb)
    [after] = [p for p in closed.proposals if p.id == called.id]
    assert (after.closed_by, after.status) == (task["id"], "done"), "closed at once, by the task read again"


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


def _retraction(lb: Logbook) -> None:
    with lb.index() as idx:
        note = next(iter(idx.of_kind("note")))
    lb.retract(int(note["seq"]), "not mine")


def _correction(lb: Logbook) -> None:
    with lb.index() as idx:
        message = next(line for line in idx.of_kind("message") if line["payload"].get("text"))
    lb.append(
        at=str(message["at"]),
        source=str(message["source"]),
        kind="message",
        tier=int(message["tier"]),
        payload={**message["payload"], "text": "I'll be there at nine.", "supersedes": message["id"]},
    )


@pytest.mark.parametrize("change", [_resolution, _retraction, _correction])
def test_what_changes_who_said_what_reads_the_whole_record_again(
    record: Any, change: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    lb, rest = record(2)
    promises.extract(lb)
    lb.append_many(rest[0])
    change(lb)
    count = Count(monkeypatch)
    _same(lb)
    assert count.whole == 2, change.__name__
