"""A Notion row seen live and then again by `sync notion --relations-backfill` is one row on the Day.

The backfill's `relations` line adds a row's relations to an edit the record holds already, at that
edit: it is no happening of its own, so the Day (`logbook day` and the Day page of `logbook serve`)
folds it into the page's line on the day, which then stands for both lines. `show` lists every line,
as SPEC §3.2.1 has it (one calendar holding an entry twice is two rows), and still lists both. The
record is the synthetic workspace of `tests/notion_api.py`, written by the adapter's own sync and
backfill."""

from __future__ import annotations

import json
from typing import Any

import pytest
from notion_api import ENGINE, FERRY, SERVICE, SHELVES, FakeNotion
from test_notion import _backfill, _before_relations, _key, _keyed, _sync, clock, lb, notes

from logbook import cli
from logbook.contrib import serve
from logbook.core.store import Logbook

__all__ = ["clock", "lb", "notes"]  # the fixtures, imported from the adapter's own tests

DAY = "2026-03-02"
TITLES = {ENGINE: "Engine noise", FERRY: "Book the ferry", SERVICE: "Service the engine"}
SHELVES_TITLE = "Garden shelves"  # created on the day: the backfill's line is at its edit, 20 minutes on


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(list(args))
    return capsys.readouterr().out


def _backfilled(lb: Logbook, notes: FakeNotion, capsys: pytest.CaptureFixture[str]) -> dict[str, Any]:
    """The record with every row synced before relations were kept, then backfilled: per row of the
    day, its live line and the backfill's `relations` line."""
    _before_relations(lb, notes, capsys)
    assert _backfill() == 0
    capsys.readouterr()
    keyed = _keyed(lb)
    for row in (*TITLES, SHELVES):
        assert _key(row, DAY, "relations") in keyed, "the backfill wrote the row's relations"
    return keyed


def _unplaced(capsys: pytest.CaptureFixture[str], title: str) -> list[dict[str, Any]]:
    data = json.loads(_run(capsys, "day", DAY, "--json"))
    return [item for item in data["unplaced"] if item["title"] == title]


def test_day_prints_a_backfilled_row_once(
    lb: Logbook, notes: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    _backfilled(lb, notes, capsys)
    out = _run(capsys, "day", DAY)
    for title in (*TITLES.values(), SHELVES_TITLE):
        assert out.count(f"event  {title}\n") == 1, f"{title}: one row, not two\n{out}"
    assert "  09:00  event  Engine noise\n" in out and "×" not in out, "one source, so no ×N sources"
    assert "  13:00  event  Garden shelves\n" in out, "the row at its own line, the one the sync wrote"
    assert "notion 11 lines" in out, "every line still counted under sources"


def test_the_row_stands_for_both_lines_in_the_json(
    lb: Logbook, notes: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    keyed = _backfilled(lb, notes, capsys)
    for row, title in {**TITLES, SHELVES: SHELVES_TITLE}.items():
        live = next(
            keyed[_key(row, DAY, action)]
            for action in ("edited", "created")
            if _key(row, DAY, action) in keyed
        )
        backfill = keyed[_key(row, DAY, "relations")]
        (item,) = _unplaced(capsys, title)
        assert item["line"] == live["id"], f"{title}: the line the sync wrote is the row"
        assert item["lines"] == [live["id"], backfill["id"]] and item["sources"] == ["notion"]


def test_the_day_page_shows_a_backfilled_row_once(
    lb: Logbook, notes: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    keyed = _backfilled(lb, notes, capsys)
    response = serve.Site(lb).respond(f"/day/{DAY}", "")
    assert response.status == 200, response.body[:300]
    page = response.body.decode("utf-8")
    for title in (*TITLES.values(), SHELVES_TITLE):
        assert page.count(f"</span> {title}<") == 1, f"{title}: one row on the Day page"
    backfill = keyed[_key(ENGINE, DAY, "relations")]["id"]
    assert f'id="l-{backfill}"' not in page, "no row of its own"
    assert f'name="line" value="{keyed[_key(ENGINE, DAY, "edited")]["id"]}"' in page


def test_show_still_lists_both_lines(
    lb: Logbook, notes: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    _backfilled(lb, notes, capsys)
    out = _run(capsys, "show", DAY)
    assert out.count("notion         Engine noise\n") == 2, "SPEC §3.2.1: one source's repeat is two rows"


def test_a_backfill_line_without_its_page_on_the_day_is_a_row_of_its_own(
    lb: Logbook, notes: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    keyed = _backfilled(lb, notes, capsys)
    lb.retract(int(keyed[_key(ENGINE, DAY, "edited")]["seq"]), "synced twice by mistake")
    (item,) = _unplaced(capsys, "Engine noise")
    backfill = keyed[_key(ENGINE, DAY, "relations")]
    assert item["line"] == backfill["id"] and item["lines"] == [backfill["id"]]


def test_a_backfill_written_before_the_sync_saw_the_edit_folds_into_that_edit(
    lb: Logbook, notes: FakeNotion, capsys: pytest.CaptureFixture[str]
) -> None:
    """The backfill may read a row's edit first; the sync's line for it then comes after, at the same
    moment, and is the row."""
    _before_relations(lb, notes, capsys)
    notes.edit(ENGINE, "2026-03-04T09:00Z")
    assert _backfill() == 0 and _sync() == 0
    keyed = _keyed(lb)
    backfill = keyed[_key(ENGINE, "2026-03-04", "relations")]
    edited = keyed[_key(ENGINE, "2026-03-04", "edited")]
    assert backfill["at"] == edited["at"] and int(backfill["seq"]) < int(edited["seq"])
    capsys.readouterr()
    data = json.loads(_run(capsys, "day", "2026-03-04", "--json"))
    (item,) = [item for item in data["unplaced"] if item["title"] == "Engine noise"]
    assert item["line"] == edited["id"] and item["lines"] == [edited["id"], backfill["id"]]
