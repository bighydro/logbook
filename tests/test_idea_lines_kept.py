"""The lines that name an idea, kept between readings (`entity_review.idea_lines`): which lines of the
idea kinds give a sighting is the line's alone (and the settings'), so their places in the files are
kept and the next reading reads only those and the lines appended since; what stands, the Notion
tree, the roots and who is who are read each time. The observed ideas and every idea's touches are
the reading of every line, after each line appended, a line into an earlier month, a correction and a
retraction among them. On the synthetic record of `tests/ideas_record.py`: nobody and nothing in it
exists."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from ideas_record import (
    CLOCK_REPO,
    GARDEN,
    IDEA_TYPE,
    KIOSK_REPO,
    KIOSK_ROW,
    PRICING,
    github,
    ideas_drafts,
    notion,
    record,
    row,
    settle,
    task,
    transcript,
)

from logbook.contrib import entity_review, ideas
from logbook.contrib.entities import IDEA
from logbook.core import index, kept
from logbook.core.store import Logbook


@pytest.fixture
def lb(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Logbook:
    found = record(tmp_path, monkeypatch, ideas_drafts())
    settle(found)
    return found


class Whole:
    """How many readings of the idea kinds read every event."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.n = 0
        real = index.Index.of_kind

        def of_kind(idx: Any, kind: str, *args: Any, **kwargs: Any) -> Any:
            if kind == "task" and kwargs.get("after_seq") is None and not args and not kwargs.get("source"):
                self.n += 1
            return real(idx, kind, *args, **kwargs)

        monkeypatch.setattr(index.Index, "of_kind", of_kind)

    def take(self) -> int:
        n, self.n = self.n, 0
        return n


def _read(lb: Logbook) -> tuple[list[dict[str, Any]], list[Any], list[Any]]:
    with lb.index() as idx:
        observed = [o.row() | {"entity": o.entity} for o in entity_review.build(lb, idx, IDEA)]
    return observed, ideas.read(lb).touches, ideas.read(lb, (1,)).touches


def _same(lb: Logbook, whole: Whole | None = None) -> int:
    if whole is not None:
        whole.take()
    found = _read(lb)
    n = whole.take() if whole is not None else 0
    with mock.patch.object(kept, "load", return_value=None):
        assert found == _read(lb)
    assert found[0] and found[1], "the record has ideas and touches"
    return n


def _lines(day: str) -> list[dict[str, Any]]:
    return [
        row(f"{day}T08:00:00Z", KIOSK_ROW, "The fjord kiosk", words=900, delta=40, properties=IDEA_TYPE),
        notion(f"{day}T09:00:00Z", PRICING, "Pricing", parent={"type": "page", "id": KIOSK_ROW}, words=320),
        notion(f"{day}T09:30:00Z", GARDEN, "Garden notes", words=60),
        github(f"{day}T10:00:00Z", KIOSK_REPO, "committed", f"Kiosk menu {day}"),
        github(f"{day}T11:00:00Z", CLOCK_REPO, "revised", "README.md", words=170),
        task(f"{day}T12:00:00Z", "Harbour sauna"),
        task(f"{day}T12:30:00Z", f"Buy rope {day}"),
        transcript(f"{day}T15:00:00Z", "Harbour sauna", f"{day}T15:30:00Z"),
        {
            "at": f"{day}T16:00:00Z",
            "source": "manual",
            "kind": "note",
            "tier": 2,
            "payload": {"schema": "note/v1", "text": "names no idea"},
        },
    ]


def test_a_day_at_a_time_the_ideas_and_their_touches_are_every_line_s(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    _same(lb)
    whole = Whole(monkeypatch)
    for n in range(6):
        lb.append_many(_lines(f"2026-10-{17 + n:02d}"))
        assert _same(lb, whole) == 0, "read the lines that name an idea, and those appended"


def _earlier_month(lb: Logbook) -> None:
    lb.append_many(_lines("2025-03-03"))


def _correction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(line for line in idx.of_kind("task") if line["payload"].get("title") == "Harbour sauna")
    lb.append(
        at=str(line["at"]),
        source=str(line["source"]),
        kind="task",
        tier=int(line["tier"]),
        payload={**line["payload"], "title": "Harbour sauna, the second", "supersedes": line["id"]},
    )


def _retraction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(line for line in idx.of_kind("event") if line["source"] == "github")
    lb.retract(int(line["seq"]), "not mine")


@pytest.mark.parametrize("change", [_earlier_month, _correction, _retraction])
def test_what_comes_before_or_changes_a_line_is_read_where_it_stands(
    lb: Logbook, change: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _same(lb)
    lb.append_many(_lines("2026-10-17"))
    change(lb)
    whole = Whole(monkeypatch)
    assert _same(lb, whole) == 0, change.__name__
