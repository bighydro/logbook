"""`logbook show plan [DAY] [--json] [--coverage]`: the plan, read and never run (RFC 0043 §9, slice E).

The plan is what `sync notion` already wrote: one `event/v1` line per Notion page, day and action, tier
1, a database row's status, select, date and checkbox values and its relations, never its body. The
reader takes the latest line per row and answers three parts: today's tasks, the current sprint and
the next trip. It reads tier-1 `sync notion` lines and nothing else: never the day's stays, its
browsing or any other line, and it names none of them (where you are and the queue are a later slice).
Which databases are which is the owner's `plan` entry in `policy/notion.json`; without it the reader
says so in one sentence and answers nothing. Nothing is written, to the record or to Notion.

The lines here are built the way the adapter writes them (`tests/ideas_record.py`'s `notion`), and
one test writes them through the adapter itself against the fake API of `tests/notion_api.py`.
Everything is synthetic: Ines Nordmann of Oslo, who does not exist, her tasks, her trip to Lofoten."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from ideas_record import notion
from notion_api import FERRY as FAKE_FERRY
from notion_api import TASKS as FAKE_TASKS
from persona import HOME, TZ, dwell
from test_notion import _sync, clock, fake

from logbook import cli
from logbook.contrib import plan
from logbook.core.store import Logbook

__all__ = ["clock", "fake"]  # the fixtures, imported from the adapter's own tests

DAY = "2026-10-21"  # a Wednesday in Sprint 24


def uid(n: int) -> str:
    """A synthetic Notion id, dashed as the API spells one."""
    return f"{n:08x}-0000-4000-8000-{n:012x}"


TASKS, SPRINTS, TRIPS = (uid(0x100 + n) for n in range(3))
CITIES, QUEUE, PEOPLE, PLACES = (uid(0x103 + n) for n in range(4))  # databases the plan does not read
SPRINT_23, SPRINT_24 = uid(0x201), uid(0x202)
LOFOTEN, BERGEN_TRIP, COPENHAGEN = uid(0x301), uid(0x302), uid(0x303)
OSLO, BERGEN = uid(0x401), uid(0x402)
PER, FJORD_CAFE = uid(0x501), uid(0x601)
SPLICING, REEFING, UNREAD = uid(0x701), uid(0x702), uid(0x703)
BILGE, FERRY, PHOTOS, TILLER, CHARTS, STORAGE, ROPE, BINNED = (uid(0x800 + n) for n in range(8))
MORE = [uid(0x900 + n) for n in range(5)]  # five more tasks dated today, in the sprint
MORE_TITLES = [
    "Check the life jackets",
    "Clean the cabin",
    "Renew the berth",
    "Service the outboard",
    "Test the VHF",
]
BODY_WORDS = 240  # every task line carries a body digest; its text is never in the record

MAPPING = {
    "tasks": TASKS,
    "sprints": f"https://www.notion.so/ines/Sprints-{SPRINTS.replace('-', '')}?pvs=4",  # a copied link
    "trips": TRIPS,
}
LATER = ("cities", "queue", "people", "places")  # where you are and the queue: a later slice


def _row(at: str, page: str, title: str, database: str, **kw: Any) -> dict[str, Any]:
    path = {TASKS: "Tasks", SPRINTS: "Sprints", TRIPS: "Trips", CITIES: "Cities", QUEUE: "Queue"}.get(
        database, "People" if database == PEOPLE else "Places"
    )
    return notion(at, page, title, parent={"type": "database", "id": database}, path=["Plan", path], **kw)


def _when(start: str | None, end: str | None = None) -> dict[str, Any]:
    return {"start": start, "end": end}


def _task(
    at: str,
    page: str,
    title: str,
    due: str | None,
    status: str = "To do",
    sprint: str | None = SPRINT_24,
    **kw: Any,
) -> dict[str, Any]:
    properties = {"Due": _when(due), "Priority": "High", "Status": status, "Done": status == "Done"}
    relations = {"Sprint": [sprint] if sprint else []}
    return _row(at, page, title, TASKS, properties=properties, relations=relations, words=BODY_WORDS, **kw)


def plan_lines() -> list[dict[str, Any]]:
    """The plan as `sync notion` would have written it over two months."""
    return [
        _row("2026-09-27T08:00:00Z", SPRINT_23, "Sprint 23", SPRINTS, action="created",
             properties={"Dates": _when("2026-09-28", "2026-10-11")}),
        _row("2026-10-11T08:00:00Z", SPRINT_24, "Sprint 24", SPRINTS, action="created",
             properties={"Dates": _when("2026-10-12", "2026-10-25")}),
        _row("2026-08-01T10:00:00Z", COPENHAGEN, "Copenhagen", TRIPS, action="created",
             properties={"When": _when("2026-09-01", "2026-09-04")}),
        _row("2026-09-15T10:00:00Z", LOFOTEN, "Lofoten", TRIPS, action="created",
             properties={"When": _when("2026-11-27", "2026-12-03")}),
        _row("2026-09-16T10:00:00Z", BERGEN_TRIP, "Bergen weekend", TRIPS, action="created",
             properties={"When": _when("2026-12-05", "2026-12-06")}),
        _row("2026-09-01T09:00:00Z", OSLO, "Oslo", CITIES, action="created",
             relations={"People": [PER], "Tasks": [ROPE]}),
        _row("2026-09-01T09:05:00Z", BERGEN, "Bergen", CITIES, action="created"),
        _row("2026-09-02T09:00:00Z", PER, "Per Hansen", PEOPLE, action="created", relations={"City": [OSLO]}),
        # the café names the city from its own side of the relation; Oslo's line does not list it
        _row("2026-09-03T09:00:00Z", FJORD_CAFE, "Fjord café", PLACES, action="created",
             relations={"City": [OSLO]}),
        _row("2026-10-01T18:00:00Z", SPLICING, "https://knots.example.org/splicing", QUEUE, action="created",
             properties={"Read": False}),
        _row("2026-10-02T18:00:00Z", REEFING, "Reefing in a gust", QUEUE, action="created",
             properties={"Read": False}),
        _row("2026-10-03T18:00:00Z", UNREAD, "https://tides.example.org/oslofjord", QUEUE, action="created",
             properties={"Read": False}),
        _task("2026-10-12T07:00:00Z", BILGE, "Fix the bilge pump", "2026-10-19", action="created"),
        _task("2026-10-12T07:05:00Z", FERRY, "Book the ferry", "2026-10-21", "In progress", action="created"),
        _task("2026-10-12T07:10:00Z", PHOTOS, "Send Ola the photos", "2026-10-21", action="created"),
        _task("2026-10-21T06:30:00Z", PHOTOS, "Send Ola the photos", "2026-10-21", "Done"),  # done today
        _task("2026-09-28T07:00:00Z", TILLER, "Varnish the tiller", "2026-10-20", sprint=SPRINT_23,
              action="created"),  # overdue, but in last sprint
        _task("2026-10-12T07:15:00Z", CHARTS, "Order charts", "2026-10-22", action="created"),  # tomorrow
        _task("2026-10-13T07:00:00Z", STORAGE, "Ask about winter storage", DAY, sprint=None,
              action="created"),  # in no sprint, dated today
        _task("2026-10-13T07:05:00Z", ROPE, "Buy rope at the chandlery", None, action="created"),
        _task("2026-10-13T07:10:00Z", BINNED, "Paint the hull", DAY, action="created"),
        _task("2026-10-14T07:10:00Z", BINNED, "Paint the hull", DAY, action="archived"),
        *(
            _task(f"2026-10-12T08:0{n}:00Z", page, title, DAY, action="created")
            for n, (page, title) in enumerate(zip(MORE, MORE_TITLES, strict=True))
        ),
    ]  # fmt: skip


def day_lines() -> list[dict[str, Any]]:
    """The day's other lines, at tier 2: the owner at home in Oslo, a visit and a video, whose page
    and title are a queue row's. The plan reads none of them."""
    return [
        *dwell(DAY, "00:00", "24:00", HOME, every_min=10),
        {
            "at": "2026-10-21T17:00:00Z",
            "source": "safari",
            "kind": "browse",
            "tier": 2,
            "payload": {
                "schema": "browse/v1",
                "raw_id": "safari:1792602000:aa11bb22cc33dd44",
                "url": "https://Knots.example.org/splicing/",
                "title": "Splicing, step by step",
                "action": "visit",
                "browser": "safari",
            },
        },
        {
            "at": "2026-10-21T19:00:00Z",
            "source": "google-takeout",
            "kind": "watch",
            "tier": 2,
            "payload": {
                "schema": "watch/v1",
                "raw_id": "youtube:2026-10-21T19:00:00.000Z:5e2a4f0c9d1b7a3e",
                "action": "watched",
                "title": "Reefing in a gust",
                "url": "https://video.example.org/watch?v=reef01",
                "service": "youtube",
            },
        },
    ]


def make(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, Any] | None = MAPPING,
    lines: list[dict[str, Any]] | None = None,
) -> Logbook:
    lb = Logbook.init(tmp_path / "lb", TZ)
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    lb.append_many(plan_lines() + day_lines() if lines is None else lines)
    (lb.root / "places.json").write_text(  # home is named Oslo: nothing of it may reach the plan
        json.dumps({"Oslo": {"lat": HOME[0], "lon": HOME[1], "radius_m": 150, "kind": "home"}}),
        encoding="utf-8",
    )
    if mapping is not None:
        (lb.root / "policy").mkdir(exist_ok=True)
        (lb.root / "policy" / "notion.json").write_text(json.dumps({"plan": mapping}), encoding="utf-8")
    return lb


def run(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    try:
        cli.main(["show", "plan", *args])
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    out, err = capsys.readouterr()
    return code, out, err


def answer(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    code, out, err = run(capsys, *args, "--json")
    assert code == 0, err
    data: dict[str, Any] = json.loads(out)
    return data


def link(page: str) -> str:
    return f"https://www.notion.so/{page.replace('-', '')}"


# -- today's tasks ----------------------------------------------------------------------------------------


def test_todays_tasks_are_the_open_ones_dated_today_and_the_sprints_overdue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch)
    data = answer(capsys, DAY)
    tasks = data["tasks"]
    titles = [t["title"] for t in tasks["rows"]]
    # Notion's own date, then the title: the overdue one first
    assert titles == [
        "Fix the bilge pump",
        "Ask about winter storage",
        "Book the ferry",
        "Check the life jackets",
        "Clean the cabin",
    ], titles
    assert tasks["more"] == 3 and tasks["sprint"] == "Sprint 24"
    bilge = tasks["rows"][0]
    assert bilge["overdue"] is True and bilge["date"] == {"start": "2026-10-19", "end": None}
    assert bilge["url"] == link(BILGE) and bilge["id"] == BILGE and bilge["status"] == "To do"
    assert tasks["rows"][2]["status"] == "In progress" and tasks["rows"][2]["overdue"] is False
    every = {t["title"] for t in tasks["rows"]}
    assert "Send Ola the photos" not in every, "done by its latest line"
    assert "Varnish the tiller" not in every, "overdue in last sprint, not this one"
    assert "Order charts" not in every and "Paint the hull" not in every, "tomorrow; archived"

    code, out, _ = run(capsys, DAY)
    assert code == 0
    assert "Fix the bilge pump" in out and "overdue" in out and link(BILGE) in out
    assert "and 3 more in Sprint 24" in out


def test_the_rest_beyond_five_is_a_count_and_a_task_line_never_prints_its_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch)
    _, out, _ = run(capsys, DAY)
    shown = [t for t in MORE_TITLES if t in out]
    assert shown == MORE_TITLES[:2], "five at most: the other three are a count"
    data = answer(capsys, DAY)
    text = json.dumps(data)
    for word in ("body", "sha256", "words", "actor", "Ines"):
        assert word not in text and word not in out, word


def test_a_task_dated_over_days_is_todays_until_its_last_day(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    week = _task("2026-10-12T07:00:00Z", uid(0xB01), "Haul out the boat", "2026-10-19", action="created")
    week["payload"]["extra"]["properties"]["Due"] = _when("2026-10-19", "2026-10-23")
    old = _task("2026-10-12T07:00:00Z", uid(0xB02), "Return the trailer", "2026-10-19", sprint=SPRINT_23)
    old["payload"]["extra"]["properties"]["Due"] = _when("2026-10-19", "2026-10-23")
    make(tmp_path, monkeypatch, lines=[plan_lines()[1], week, old])
    rows = answer(capsys, DAY)["tasks"]["rows"]
    assert [(r["title"], r["overdue"]) for r in rows] == [
        ("Haul out the boat", False),
        ("Return the trailer", False),
    ], "Monday to Friday: today's on Wednesday, whichever sprint"
    (row,) = answer(capsys, "2026-10-24")["tasks"]["rows"]
    assert row["title"] == "Haul out the boat" and row["overdue"] is True


def test_a_ticked_checkbox_can_say_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A task database with no status, only a `Done` checkbox: `status` names it, ticked is done."""
    ticked = _task("2026-10-12T07:00:00Z", uid(0xC01), "Coil the halyards", DAY, action="created")
    ticked["payload"]["extra"]["properties"] = {"Due": _when(DAY), "Done": True}
    open_ = _task("2026-10-12T07:01:00Z", uid(0xC02), "Fold the jib", DAY, action="created")
    open_["payload"]["extra"]["properties"] = {"Due": _when(DAY), "Done": False}
    make(tmp_path, monkeypatch, mapping={"tasks": TASKS, "status": "Done"}, lines=[ticked, open_])
    rows = answer(capsys, DAY)["tasks"]["rows"]
    assert [r["title"] for r in rows] == ["Fold the jib"] and rows[0]["status"] is None


def test_the_count_names_the_sprint_only_for_the_tasks_in_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    loose = [
        _task(
            f"2026-10-13T09:0{n}:00Z",
            uid(0xD00 + n),
            f"Zzz loose end {n}",
            DAY,
            sprint=None,
            action="created",
        )
        for n in range(2)
    ]  # after every other title: both beyond the five
    make(tmp_path, monkeypatch, lines=[*plan_lines(), *loose])
    tasks = answer(capsys, DAY)["tasks"]
    assert tasks["more"] == 5 and tasks["more_in_sprint"] == 3
    _, out, _ = run(capsys, DAY)
    assert "and 5 more, 3 of them in Sprint 24" in out


def test_with_sprints_but_none_today_no_old_task_is_overdue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Between sprints, the overdue tasks of a sprint gone by are not today's; with no sprints mapped
    at all, every overdue open task is."""
    make(tmp_path, monkeypatch)
    data = answer(capsys, "2026-10-27")
    assert data["sprint"] is None and data["tasks"]["rows"] == [] and data["tasks"]["more"] == 0
    make(tmp_path / "no-sprints", monkeypatch, mapping={"tasks": TASKS})
    titles = [t["title"] for t in answer(capsys, "2026-10-27")["tasks"]["rows"]]
    assert titles[:2] == ["Fix the bilge pump", "Varnish the tiller"], titles


NO_SPRINT = "No sprint holds this day, so no overdue tasks are shown."


def test_with_sprints_but_none_today_the_plan_says_why_no_task_is_overdue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The owner's rule (between sprints, no overdue task) is said in one line, in the text and in the
    JSON, whether or not the day has tasks of its own; never on a day a sprint holds, and never when
    no sprints database is mapped, where every overdue task shows."""
    make(tmp_path, monkeypatch)
    tasks = answer(capsys, "2026-10-27")["tasks"]
    assert tasks["rows"] == [] and tasks["said"] == NO_SPRINT
    _, out, _ = run(capsys, "2026-10-27")
    assert [line.strip() for line in out.splitlines()].count(NO_SPRINT) == 1, out
    assert answer(capsys, DAY)["tasks"]["said"] is None, "Sprint 24 holds the day"
    assert NO_SPRINT not in run(capsys, DAY)[1]

    make(tmp_path / "due", monkeypatch, mapping={**MAPPING, "date": "Due"})  # sprints have no Due
    tasks = answer(capsys, DAY)["tasks"]
    assert tasks["rows"] and not any(t["overdue"] for t in tasks["rows"]) and tasks["said"] == NO_SPRINT
    lines = run(capsys, DAY)[1].splitlines()
    (said,) = [n for n, line in enumerate(lines) if line.strip() == NO_SPRINT]
    rows = lines[1:said]
    assert rows[-1].strip() == "and 2 more", "said after today's tasks and their count"
    assert all("https://www.notion.so/" in line for line in rows[:-1]) and len(rows) == 6

    make(tmp_path / "no-sprints", monkeypatch, mapping={"tasks": TASKS})
    assert answer(capsys, "2026-10-27")["tasks"]["said"] is None, "no sprints: every overdue task shows"
    assert NO_SPRINT not in run(capsys, "2026-10-27")[1]


def test_an_untitled_row_is_untitled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    nameless = _task("2026-10-12T07:00:00Z", uid(0xE01), "", DAY, action="created")
    del nameless["payload"]["title"]
    make(tmp_path, monkeypatch, mapping={"tasks": TASKS}, lines=[nameless])
    (row,) = answer(capsys, DAY)["tasks"]["rows"]
    assert row["title"] is None
    _, out, _ = run(capsys, DAY)
    assert "Untitled" in out and "None" not in out


def test_a_row_folds_its_backfilled_relations_and_a_sprint_may_name_its_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A `--relations-backfill` line holds a row's relations and nothing else: the row keeps the
    properties of its edit. And a sprint whose own relation lists a task holds it, whatever the task's
    line says."""
    sprint = _row(
        "2026-10-11T08:00:00Z",
        SPRINT_24,
        "Sprint 24",
        SPRINTS,
        action="created",
        properties={"Dates": _when("2026-10-12", "2026-10-25")},
    )
    task = _task(
        "2026-10-12T07:00:00Z",
        uid(0xF01),
        "Splice the mooring line",
        "2026-10-19",
        sprint=None,
        action="created",
    )
    backfill = notion(
        "2026-10-12T07:00:00Z",
        SPRINT_24,
        "Sprint 24",
        action="relations",
        parent={"type": "database", "id": SPRINTS},
        who=None,
        relations={"Tasks": [uid(0xF01)]},
    )
    backfill["payload"]["raw_id"] = f"{SPRINT_24}/2026-10-12/relations"
    make(tmp_path, monkeypatch, lines=[sprint, task, backfill])
    data = answer(capsys, DAY)
    assert data["sprint"]["date"] == {"start": "2026-10-12", "end": "2026-10-25"}, "kept from its edit"
    assert [(t["title"], t["overdue"]) for t in data["tasks"]["rows"]] == [("Splice the mooring line", True)]


def test_the_day_defaults_to_today_and_one_date_property_may_be_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from datetime import UTC, datetime

    from logbook.contrib import gaps

    make(tmp_path, monkeypatch, mapping={**MAPPING, "date": "Due"})
    monkeypatch.setattr(gaps, "now", lambda: datetime(2026, 10, 21, 10, 0, tzinfo=UTC))
    data = answer(capsys)
    assert data["day"] == DAY
    assert data["sprint"] is None and data["trip"] is None, "`date` names Due: sprints and trips have none"
    assert data["tasks"]["rows"][0]["title"] == "Ask about winter storage", "no sprint today: no overdue one"


# -- the sprint and the next trip -------------------------------------------------------------------------


def test_the_current_sprint_and_its_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch)
    sprint = answer(capsys, DAY)["sprint"]
    assert sprint["title"] == "Sprint 24" and sprint["url"] == link(SPRINT_24)
    assert sprint["date"] == {"start": "2026-10-12", "end": "2026-10-25"}
    _, out, _ = run(capsys, DAY)
    assert "Sprint 24" in out and "2026-10-12" in out and "2026-10-25" in out
    assert answer(capsys, "2026-10-05")["sprint"]["title"] == "Sprint 23"


def test_the_next_trip_is_a_countdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch)
    trip = answer(capsys, DAY)["trip"]
    assert trip["title"] == "Lofoten" and trip["days"] == 37 and trip["url"] == link(LOFOTEN)
    _, out, _ = run(capsys, DAY)
    assert "Lofoten" in out and "in 37 days" in out
    assert answer(capsys, "2026-11-30")["trip"]["title"] == "Bergen weekend", "Lofoten has begun"
    assert answer(capsys, "2026-11-27")["trip"]["days"] == 0
    _, out, _ = run(capsys, "2026-11-27")
    assert "Lofoten" in out and "today" in out


# -- tier 1 alone -------------------------------------------------------------------------------------------


def test_the_plan_is_three_parts_of_tier_1_lines_and_names_no_other_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The record holds the day at home in Oslo, a visit and a video at tier 2, and Notion rows of a
    city, a person, a place and a queue: none of it is in the plan, by part, by line id or by word."""
    lb = make(tmp_path, monkeypatch)
    data = answer(capsys, DAY)
    assert set(data) == {"day", "mapped", "tasks", "sprint", "trip"}, sorted(data)
    _, out, _ = run(capsys, DAY)
    with lb.index() as idx:
        every = [line for day in ("2026-10-20", DAY, "2026-10-22") for line in idx.day(day)]
        notion_ids = {
            str(line["id"]) for line in idx.of_source("event", "notion", "0000-01-01", "9999-12-31")
        }
    others = [line for line in every if line["source"] != "notion"]
    assert sum(line["tier"] == 2 for line in others) == 2 and len(others) > 100, "the stays, a visit, a video"
    shown = json.dumps(data) + out
    for line in others:
        assert str(line["id"]) not in shown, line["kind"]
        for key in ("url", "title"):
            if isinstance(line["payload"].get(key), str):
                assert line["payload"][key] not in shown, line["payload"][key]
    lines = {r["line"] for r in data["tasks"]["rows"]} | {data["sprint"]["line"], data["trip"]["line"]}
    assert lines <= notion_ids, "every line named is a `sync notion` line"
    for word in ("Oslo", "Per Hansen", "Fjord café", "Reefing", "knots.example.org", "Splicing"):
        assert word not in shown, word
    labels = {line.split()[0] for line in out.splitlines()[1:] if line.startswith("  ") and line[2] != " "}
    assert labels <= {"today", "next", "nothing"}, labels  # no `here`, no `queue` row


def test_the_plan_reads_no_line_but_sync_notions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reading a day, a window, a kind or the stays would be reading more than the plan: each refuses,
    and the plan, its JSON and its coverage still answer."""
    from logbook.core import reading
    from logbook.core.index import Index

    make(tmp_path, monkeypatch)

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("the plan read more than the `sync notion` lines")

    for name in ("day", "between", "by_kind", "stream", "of_kind", "locations", "evidence", "window"):
        monkeypatch.setattr(Index, name, refuse)
    monkeypatch.setattr(reading, "read", refuse)
    assert run(capsys, DAY)[0] == 0
    assert answer(capsys, DAY)["tasks"]["rows"][0]["title"] == "Fix the bilge pump"
    assert answer(capsys, "--coverage")["mapped"] is True


def test_a_mapping_naming_a_later_slices_database_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Where you are and the queue read tier-2 lines; this slice has neither, so a mapping naming
    their databases is one error naming the key, never a part answered from nothing."""
    for n, key in enumerate(LATER):
        make(tmp_path / str(n), monkeypatch, mapping={**MAPPING, key: CITIES})
        code, out, err = run(capsys, DAY)
        assert code == 2 and out == "" and key in err and "notion.json" in err, key


# -- no mapping, a bad one -----------------------------------------------------------------------------------


def test_without_a_mapping_the_reader_says_so_in_one_sentence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = make(tmp_path, monkeypatch, mapping=None)
    code, out, err = run(capsys, DAY)
    assert code == 0 and err == ""
    assert out.count("\n") == 1 and out.rstrip().endswith(".") and "policy/notion.json" in out
    assert "Fix the bilge pump" not in out
    data = answer(capsys, DAY)
    assert data["mapped"] is False and data["said"] == out.strip()
    assert set(data) == {"day", "mapped", "said", "tasks", "sprint", "trip"}
    assert all(data[part] is None for part in ("tasks", "sprint", "trip"))
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "notion.json").write_text(json.dumps({"other": 1}), encoding="utf-8")
    assert run(capsys, DAY)[1] == out, "a file with no plan entry is no mapping"


def test_a_mapping_that_is_not_the_shape_is_one_error_naming_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch, mapping={"tasks": "not an id"})
    code, out, err = run(capsys, DAY)
    assert code == 2 and out == ""
    assert "notion.json" in err and "tasks" in err and "Traceback" not in err
    make(tmp_path / "two", monkeypatch, mapping={"tusks": TASKS})
    code, _, err = run(capsys, DAY)
    assert code == 2 and "tusks" in err


def test_a_bad_day_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch)
    for bad in ("2026-13-01", "20261021", "2026-W43-3"):  # the last two `date.fromisoformat` would take
        code, out, err = run(capsys, bad)
        assert code == 2 and out == "" and "YYYY-MM-DD" in err and "Traceback" not in err, bad


# -- coverage ----------------------------------------------------------------------------------------------


def test_coverage_counts_the_rows_the_record_knows_and_each_databases_first_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch)
    data = answer(capsys, "--coverage")["coverage"]
    assert data["tasks"]["rows"] == 13 and data["tasks"]["lines"] == 15
    assert data["tasks"]["first"] == "2026-09-28T07:00:00Z" and data["tasks"]["first_day"] == "2026-09-28"
    assert data["sprints"]["rows"] == 2 and data["sprints"]["first_day"] == "2026-09-27"
    assert data["trips"]["rows"] == 3 and set(data) == {"tasks", "sprints", "trips"}
    assert data["tasks"]["id"] == TASKS and data["sprints"]["id"] == SPRINTS, "the link is read as its id"
    code, out, _ = run(capsys, "--coverage")
    assert code == 0
    assert "13 task rows" in out and "2026-09-28" in out
    assert "sync notion --since" in out and "not run here" in out


def test_coverage_says_a_database_the_record_has_no_line_of(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(
        tmp_path,
        monkeypatch,
        lines=[line for line in plan_lines() if "Trips" not in line["payload"]["extra"]["path"]],
    )
    data = answer(capsys, "--coverage")["coverage"]
    assert data["trips"] == {"id": TRIPS, "rows": 0, "lines": 0, "first": None, "first_day": None}
    _, out, _ = run(capsys, "--coverage")
    assert "trips" in out and "no line yet" in out


# -- the rules -----------------------------------------------------------------------------------------------


def test_reading_the_plan_writes_nothing_and_reads_tier_1_notion_lines_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    secret = _task("2026-10-15T07:00:00Z", uid(0xAAA), "A row someone wrote at tier 2", DAY, action="created")
    secret["tier"] = 2
    lb = make(tmp_path, monkeypatch, lines=[*plan_lines(), *day_lines(), secret])
    head = lb.meta.get("head")
    before = sorted(p.read_bytes() for p in (lb.root / "log").rglob("*") if p.is_file())
    _, out, _ = run(capsys, DAY)
    data = answer(capsys, DAY)
    answer(capsys, "--coverage")
    assert "A row someone wrote at tier 2" not in out + json.dumps(data)
    assert sorted(p.read_bytes() for p in (lb.root / "log").rglob("*") if p.is_file()) == before
    assert Logbook.find().meta.get("head") == head


def test_reading_the_plan_opens_no_connection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], no_network: list[str]
) -> None:
    make(tmp_path, monkeypatch)
    assert answer(capsys, DAY)["tasks"]["rows"] and answer(capsys, "--coverage")["mapped"] is True
    assert run(capsys, DAY)[0] == 0
    assert no_network == []


def test_the_reader_is_a_function_of_the_lines(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lb = make(tmp_path, monkeypatch)
    first = plan.read(lb, DAY)
    assert plan.read(lb, DAY) == first and first.to_json()["day"] == DAY


def test_a_retracted_line_is_not_the_rows_latest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lb = make(tmp_path, monkeypatch)
    with lb.index() as idx:
        (done,) = [
            line
            for line in idx.day(DAY)
            if line["source"] == "notion" and line["payload"]["extra"]["page"]["id"] == PHOTOS
        ]
    lb.append(
        "2026-10-21T07:00:00Z",
        "manual",
        "retraction",
        1,
        {
            "schema": "retraction/v1",
            "raw_id": "retract-photos-done",
            "supersedes": done["id"],
            "reason": "a slip",
        },
    )
    assert answer(capsys, DAY)["tasks"]["more"] == 4, "its standing latest line says To do: one more open"


# -- through the adapter itself ---------------------------------------------------------------------------


def test_the_reader_reads_what_sync_notion_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], fake: Any
) -> None:
    """The fake workspace's task database through the real `sync notion`: Book the ferry is due on 5
    March and Doing; the line holds its status and its date by name, never its text, a phone or a
    person, and the plan finds it overdue a day later."""
    lb = Logbook.init(tmp_path / "lb", "Europe/Oslo")
    monkeypatch.setenv("LOGBOOK_HOME", str(lb.root))
    assert _sync() == 0
    capsys.readouterr()
    (lb.root / "policy").mkdir(exist_ok=True)
    (lb.root / "policy" / "notion.json").write_text(
        json.dumps({"plan": {"tasks": FAKE_TASKS}}), encoding="utf-8"
    )
    rows = answer(capsys, "2026-03-06")["tasks"]["rows"]
    assert [(r["title"], r["status"], r["overdue"], r["url"]) for r in rows] == [
        ("Book the ferry", "Doing", True, link(FAKE_FERRY))
    ]
    _, out, _ = run(capsys, "2026-03-06")
    for never in ("Compare the two crossings", "07700 900123", "ask Ola about the car", "Ola Nordmann"):
        assert never not in out, never


# -- a task's day: its Planned date, else its Due date (RFC 0043 §9, as #369 amends it) ---------------------

# `show plan 2026-10-21` on this record, no row with a Planned date: what main prints, byte for byte
SHOWN_WITHOUT_PLANNED = (
    "plan  2026-10-21 · Sprint 24, 2026-10-12 to 2026-10-25  https://www.notion.so/00000202000040008000000000000202\n"
    "  today       1  2026-10-19  Fix the bilge pump · To do · overdue  https://www.notion.so/00000800000040008000000000000800\n"
    "              2  2026-10-21  Ask about winter storage · To do  https://www.notion.so/00000805000040008000000000000805\n"
    "              3  2026-10-21  Book the ferry · In progress  https://www.notion.so/00000801000040008000000000000801\n"
    "              4  2026-10-21  Check the life jackets · To do  https://www.notion.so/00000900000040008000000000000900\n"
    "              5  2026-10-21  Clean the cabin · To do  https://www.notion.so/00000901000040008000000000000901\n"
    "             and 3 more in Sprint 24\n"
    "  next trip  Lofoten · 2026-11-27 to 2026-12-03 · in 37 days  https://www.notion.so/00000301000040008000000000000301\n"
)  # fmt: skip


def _planned(lines: list[dict[str, Any]], planned: dict[str, str]) -> list[dict[str, Any]]:
    """The plan's lines with a `Planned` date on the tasks `planned` names (page id → day)."""
    out = []
    for line in lines:
        extra = line["payload"]["extra"]
        page = extra["page"]["id"]
        if page in planned and isinstance(extra.get("properties"), dict):
            line = json.loads(json.dumps(line))
            line["payload"]["extra"]["properties"]["Planned"] = _when(planned[page])
        out.append(line)
    return out


PLANNED = {
    CHARTS: DAY,  # due tomorrow, planned for today: today's
    FERRY: "2026-10-23",  # due today, planned for Friday: not today's
    BILGE: DAY,  # due on Monday, planned for today: today's, and not overdue
}


def test_a_tasks_day_is_its_planned_date_else_its_due_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default mapping, no `date` named: a task is dated by `Planned`, else by `Due`."""
    make(tmp_path, monkeypatch, MAPPING, _planned(plan_lines(), PLANNED) + day_lines())
    mapping = plan.read_mapping(tmp_path / "lb")
    assert mapping is not None and mapping.date is None and mapping.dates("tasks") == ("Planned", "Due")
    tasks = answer(capsys, DAY)["tasks"]
    titles = [t["title"] for t in tasks["rows"]]
    assert "Order charts" in titles, "planned for today, due tomorrow"
    assert "Book the ferry" not in titles, "due today, planned for Friday"
    bilge = next(t for t in tasks["rows"] if t["title"] == "Fix the bilge pump")
    assert bilge["overdue"] is False and bilge["date"] == {"start": DAY, "end": None}, "its Planned date"
    storage = next(t for t in tasks["rows"] if t["title"] == "Ask about winter storage")
    assert storage["date"] == {"start": DAY, "end": None}, "no Planned date: its Due date is its day"


def test_a_mapping_without_planned_prints_show_plan_byte_for_byte_as_main_does_now(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch, MAPPING)  # no row carries a Planned date
    code, out, _ = run(capsys, DAY)
    assert code == 0 and out == SHOWN_WITHOUT_PLANNED


def test_an_empty_list_of_date_properties_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    make(tmp_path, monkeypatch, {**MAPPING, "date": []})
    code, _, err = run(capsys, DAY)
    assert code != 0 and "plan.date" in err and "notion.json" in err
