"""The People pages' years kept (`person_page.ranked`): the year so far is brought forward with the
record (`people.read_to_end`), and a closed year's ranking is kept beside the index and read again only
when a line lands on its days, a line corrects another, or who is who changes. Each is the ranking read
from every line. On the demo month (the Oslo persona and the people around her, who do not exist), with
a note in the next January closing its year."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

from logbook.contrib import demo, person_page
from logbook.core import kept, people
from logbook.core.store import Logbook

NOW = datetime(2027, 1, 20, 9, 0, tzinfo=UTC)
WINDOW = ("2026-05-31", "2026-12-31")  # the closed year: the record's first day (its resolutions) to the 31st


@pytest.fixture
def lb(tmp_path: Path) -> Logbook:
    return demo.generate(tmp_path / "Demo", days=20, seed=1)


def _note(lb: Logbook, at: str, text: str) -> None:
    lb.append(at=at, source="manual", kind="note", tier=2, payload={"schema": "note/v1", "text": text})


class Reads:
    def __init__(self, monkeypatch: pytest.MonkeyPatch):
        self.windows: list[tuple[str, str]] = []
        real = people.read

        def counted(lb: Logbook, first: str, last: str, *args: Any, **kwargs: Any) -> Any:
            self.windows.append((first, last))
            return real(lb, first, last, *args, **kwargs)

        monkeypatch.setattr(people, "read", counted)

    def take(self) -> list[tuple[str, str]]:
        found, self.windows[:] = list(self.windows), []
        return found


def _same(lb: Logbook, year: str, reads: Reads | None = None) -> list[tuple[str, str]]:
    """The year's ranking, kept, is the ranking read from every line; the windows the kept one read."""
    if reads is not None:
        reads.take()
    found = person_page.ranked(lb, year, NOW)
    read = reads.take() if reads is not None else []
    with mock.patch.object(kept, "load", return_value=None), mock.patch.dict(people._HELD, clear=True):
        assert found == person_page.ranked(lb, year, NOW)
    return read


def test_a_closed_year_is_read_once_and_again_only_for_a_line_of_its_own(
    lb: Logbook, monkeypatch: pytest.MonkeyPatch
) -> None:
    _note(lb, "2027-01-05T10:00:00Z", "The new year at the marina.")
    reads = Reads(monkeypatch)
    assert _same(lb, "2026", reads) == [WINDOW]
    assert any(r["days"] for r in person_page.ranked(lb, "2026", NOW)["people"])
    _note(lb, "2027-01-06T10:00:00Z", "Another winter day.")
    assert _same(lb, "2026", reads) == [], "a line of the next year: the closed year as kept"
    _note(lb, "2026-06-10T12:00:00Z", "A note found later, of a June day.")
    assert _same(lb, "2026", reads) == [WINDOW], "a line of its own days"


def _retraction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("message")))
    lb.retract(int(line["seq"]), "not mine")


def _correction(lb: Logbook) -> None:
    with lb.index() as idx:
        line = next(iter(idx.of_kind("message")))
    lb.append(
        at="2027-01-07T10:00:00Z",
        source=str(line["source"]),
        kind="message",
        tier=int(line["tier"]),
        payload={**line["payload"], "text": "corrected", "supersedes": line["id"]},
    )


@pytest.mark.parametrize("change", [_retraction, _correction])
def test_what_changes_a_closed_year_from_outside_it_reads_it_again(
    lb: Logbook, change: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _note(lb, "2027-01-05T10:00:00Z", "The new year at the marina.")
    _same(lb, "2026")
    change(lb)
    reads = Reads(monkeypatch)
    assert _same(lb, "2026", reads) == [WINDOW], change.__name__


def test_the_year_so_far_is_brought_forward(lb: Logbook, monkeypatch: pytest.MonkeyPatch) -> None:
    _same(lb, "2026")
    reads = Reads(monkeypatch)
    _note(lb, "2026-06-21T10:00:00Z", "One more day.")
    _same(lb, "2026", reads)
    assert ("2026-06-01", "2026-06-21") not in reads.take(), "the year so far is never read whole again"
