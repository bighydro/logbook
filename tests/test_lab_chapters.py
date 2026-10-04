"""`logbook lab chapters`: the record segmented into chapters by home-region changes, gaps in the
track and long trips, as a table of contents. Synthetic Oslo persona over one spring, nobody in it
exists; nothing is appended."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from logbook.store import Logbook
from persona import KARI, KARI_ID, OLA, OLA_ID, TZ, attendee, dwell, event, resolution, travel, utc

from logbook import cli

HOME_A = (59.9139, 10.7522)  # the first flat, central Oslo
OFFICE_A = (59.9100, 10.7600)
HOME_B = (59.9500, 10.6000)  # the second flat, 9 km west
OFFICE_B = (59.9450, 10.6100)
PARENTS = (60.3913, 5.3221)  # the family home in Bergen: a home place too, visited for five nights
HOTEL = (47.3769, 8.5417)  # Zürich, 25 nights
PER = {"id": "019cadd3-6bc0-7dcd-9133-000000000003", "name": "Per Hansen", "email": "per.hansen@example.org"}

FIRST, LAST = date(2026, 3, 1), date(2026, 5, 29)
MOVE = date(2026, 3, 29)  # the move from A to B
GAP = (date(2026, 4, 10), date(2026, 4, 19))  # no line at all for ten days
TRIP = (date(2026, 5, 1), date(2026, 5, 25))  # the 25 nights in Zürich; home on the 26th
VISIT = (date(2026, 3, 14), date(2026, 3, 18))  # five nights at the parents'

PLACES = {
    "Home A": {"lat": HOME_A[0], "lon": HOME_A[1], "radius_m": 120, "kind": "home"},
    "Home B": {"lat": HOME_B[0], "lon": HOME_B[1], "radius_m": 120, "kind": "home"},
    "Parents": {"lat": PARENTS[0], "lon": PARENTS[1], "radius_m": 150, "kind": "home"},
    "Office A": {"lat": OFFICE_A[0], "lon": OFFICE_A[1], "radius_m": 120},
    "Office B": {"lat": OFFICE_B[0], "lon": OFFICE_B[1], "radius_m": 120},
    "Hotel Zürich": {"lat": HOTEL[0], "lon": HOTEL[1], "radius_m": 150},
}


def _days(first: date, last: date) -> list[date]:
    return [first + timedelta(days=i) for i in range((last - first).days + 1)]


def _at(
    day: date, home: tuple[float, float], office: tuple[float, float] | None, start: str = "00:00"
) -> list[dict[str, Any]]:
    d = day.isoformat()
    if office is None or day.weekday() >= 5:
        return dwell(d, start, "24:00", home, every_min=20)
    return (
        dwell(d, start, "08:40", home, every_min=20)
        + travel(d, "08:40", "09:00", home, office, steps=3)
        + dwell(d, "09:00", "17:00", office, every_min=20)
        + travel(d, "17:00", "17:20", office, home, steps=3)
        + dwell(d, "17:20", "24:00", home, every_min=20)
    )


def _track(day: date) -> list[dict[str, Any]]:
    """The owner's points of one day: the move to the parents' and back, the move from A to B, the
    flight out and home, else a day at home with the office on weekdays."""
    d = day.isoformat()
    if GAP[0] <= day <= GAP[1]:
        return []
    if day == VISIT[0]:
        return (
            dwell(d, "00:00", "07:00", HOME_A, every_min=20)
            + travel(d, "07:00", "08:00", HOME_A, PARENTS, steps=6)
            + dwell(d, "08:00", "24:00", PARENTS, every_min=20)
        )
    if VISIT[0] < day <= VISIT[1]:
        return dwell(d, "00:00", "24:00", PARENTS, every_min=20)
    if day == VISIT[1] + timedelta(days=1):
        return (
            dwell(d, "00:00", "07:00", PARENTS, every_min=20)
            + travel(d, "07:00", "08:00", PARENTS, HOME_A, steps=6)
            + _at(day, HOME_A, OFFICE_A, start="08:00")
        )
    if day == MOVE:
        return (
            dwell(d, "00:00", "10:00", HOME_A, every_min=20)
            + travel(d, "10:00", "10:30", HOME_A, HOME_B, steps=4)
            + dwell(d, "10:30", "24:00", HOME_B, every_min=20)
        )
    if day == TRIP[0]:
        return (
            dwell(d, "00:00", "06:00", HOME_B, every_min=20)
            + travel(d, "06:00", "09:00", HOME_B, HOTEL, steps=6)
            + dwell(d, "09:00", "24:00", HOTEL, every_min=20)
        )
    if TRIP[0] < day <= TRIP[1]:
        return dwell(d, "00:00", "24:00", HOTEL, every_min=20)
    if day == TRIP[1] + timedelta(days=1):
        return (
            dwell(d, "00:00", "10:00", HOTEL, every_min=20)
            + travel(d, "10:00", "13:00", HOTEL, HOME_B, steps=6)
            + dwell(d, "13:00", "24:00", HOME_B, every_min=20)
        )
    if day < MOVE:
        return _at(day, HOME_A, OFFICE_A)
    return _at(day, HOME_B, OFFICE_B)


def _lunch(day: date, who: dict[str, Any], where: str) -> dict[str, Any]:
    d = day.isoformat()
    return event(utc(d, "12:00"), utc(d, "13:00"), "Lunch", [attendee(who["email"])], location=where)


def _drafts() -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = [
        resolution(("email", KARI["email"]), KARI_ID, "Kari Nordmann"),
        resolution(("email", OLA["email"]), OLA_ID, "Ola Nordmann"),
        resolution(("email", PER["email"]), PER["id"], PER["name"]),
    ]
    for day in _days(FIRST, LAST):
        drafts += _track(day)
        visiting, in_gap = VISIT[0] <= day <= VISIT[1], GAP[0] <= day <= GAP[1]
        if day < MOVE and day.weekday() == 2 and not visiting:
            drafts.append(_lunch(day, KARI, "Office A"))  # Wednesdays: 4, 11 and 25 March
        if MOVE <= day < TRIP[0] and day.weekday() == 2 and not in_gap:
            drafts.append(_lunch(day, OLA, "Office B"))  # 1, 8, 22 and 29 April
        if TRIP[0] <= day <= TRIP[1] and day.weekday() == 1:
            drafts.append(_lunch(day, PER, "Hotel Zürich"))  # Tuesdays: 5, 12 and 19 May
    # the mail kept coming through the gap
    for day in _days(*GAP):
        drafts.append(
            {
                "at": utc(day.isoformat(), "09:00"),
                "source": "mail",
                "kind": "mail",
                "tier": 2,
                "payload": {
                    "schema": "mail/v1",
                    "message_id": f"<{day.isoformat()}@example.org>",
                    "subject": "hi",
                },
            }
        )
    return drafts


@pytest.fixture(scope="module")
def record(tmp_path_factory: pytest.TempPathFactory) -> Logbook:
    lb = Logbook.init(tmp_path_factory.mktemp("chapters") / "lb", TZ)
    lb.append_many(_drafts())
    (lb.root / "places.json").write_text(json.dumps(PLACES), encoding="utf-8")
    return lb


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> str:
    cli.main(["lab", "chapters", *args])
    return capsys.readouterr().out


def _json(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_run(capsys, *args, "--json"))
    return data


def _summary(data: dict[str, Any]) -> list[tuple[str, str, str, str | None]]:
    return [(c["kind"], c["start"], c["end"], c["home"]) for c in data["chapters"]]


def test_chapters_open_at_a_move_a_gap_and_a_long_trip(
    record: Logbook,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    no_network: list[str],
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    head = record.meta["head"]
    data = _json(capsys)
    assert data["window"]["since"] == "2026-03-01" and data["window"]["until"] == "2026-05-29"
    assert data["home_history"] == "inferred"
    assert data["settings"] == {"min_trip_nights": 21, "min_gap_days": 7, "min_home_nights": 14}
    assert _summary(data) == [
        ("home", "2026-03-01", "2026-03-28", "Home A"),
        ("home", "2026-03-29", "2026-04-09", "Home B"),
        ("gap", "2026-04-10", "2026-04-19", "Home B"),
        ("home", "2026-04-20", "2026-04-30", "Home B"),
        ("trip", "2026-05-01", "2026-05-25", "Home B"),
        ("home", "2026-05-26", "2026-05-29", "Home B"),
    ]
    one, two, gap, _four, trip, six = data["chapters"]
    assert [c["n"] for c in data["chapters"]] == [1, 2, 3, 4, 5, 6]
    assert one["days"] == 28 and one["nights"] == {"total": 28, "home": 28, "away": 0, "in_transit": 0}
    assert one["located_days"] == 28
    assert one["opened_by"]["kind"] == "record start"
    visited = [p["name"] for p in one["places"]]
    assert visited == ["Office A", "Parents"], "the home of the time is no place; another home is"
    assert one["places"][0]["stays"] == 17 and 130 < one["places"][0]["hours"] < 140
    assert one["places"][1]["nights"] == 5
    assert [(p["name"], p["days"]) for p in one["people"]] == [("Kari Nordmann", 3)]
    assert one["people"][0]["person"] == KARI_ID and len(one["people"][0]["lines"]) == 3
    assert two["opened_by"] == {
        "kind": "home change",
        "detail": "Home A → Home B, inferred from the nights",
        "lines": two["opened_by"]["lines"],
    }
    assert len(two["opened_by"]["lines"]) == 1
    assert gap["title"] == "gap: no track for 10 days" and gap["located_days"] == 0 and gap["days"] == 10
    assert gap["still_spoke"] == {"mail": 10}
    assert gap["opened_by"]["kind"] == "track gap"
    assert trip["title"] == "trip: Hotel Zürich" and trip["trip"]["id"] == "trip:2026-05-01:2026-05-25"
    assert trip["nights"] == {"total": 25, "home": 0, "away": 25, "in_transit": 0}
    assert [p["name"] for p in trip["places"]] == ["Hotel Zürich"]
    assert [(p["name"], p["days"]) for p in trip["people"]] == [("Per Hansen", 3)]
    assert trip["opened_by"]["kind"] == "trip"
    assert six["opened_by"]["kind"] == "return" and six["nights"]["home"] == 4
    assert all(len(c["lines"]) == 2 and all(len(id_) == 36 for id_ in c["lines"]) for c in data["chapters"])
    assert record.meta["head"] == head and no_network == []


def test_the_text_is_a_table_of_contents(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    text = _run(capsys)
    lines = text.splitlines()
    assert lines[0].startswith("chapters 2026-03-01") and "6 chapters" in lines[0] and "inferred" in lines[0]
    assert len(lines) == 7
    assert lines[1].lstrip().startswith("1 ") and "2026-03-01" in lines[1] and "28 nights" in lines[1]
    assert "home: Home A" in lines[1] and "Office A" in lines[1] and "Kari Nordmann" in lines[1]
    assert "gap: no track" in lines[3] and "mail" in lines[3]
    assert "trip: Hotel Zürich" in lines[5] and "25 nights" in lines[5] and "Per Hansen" in lines[5]


def test_dates_in_places_json_win_over_the_nights(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    dated = {
        **PLACES,
        "Home A": {**PLACES["Home A"], "until": "2026-03-31"},
        "Home B": {**PLACES["Home B"], "since": "2026-04-01"},
    }
    copy = tmp_path / "lb"
    _copy_record(record, copy, dated)
    monkeypatch.setenv("LOGBOOK_HOME", str(copy))
    data = _json(capsys)
    assert data["home_history"] == "places.json"
    assert _summary(data)[:3] == [
        ("home", "2026-03-01", "2026-03-31", "Home A"),
        ("home", "2026-04-01", "2026-04-09", "Home B"),
        ("gap", "2026-04-10", "2026-04-19", "Home B"),
    ]
    assert data["chapters"][1]["opened_by"]["detail"] == "Home A → Home B, dated in places.json"
    assert "places.json" in _run(capsys).splitlines()[0]


def test_a_bad_date_in_places_json_is_one_clear_error(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    copy = tmp_path / "lb"
    _copy_record(record, copy, {**PLACES, "Home B": {**PLACES["Home B"], "since": "April"}})
    monkeypatch.setenv("LOGBOOK_HOME", str(copy))
    with pytest.raises(SystemExit) as e:
        cli.main(["lab", "chapters"])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "places.json" in err and "Home B" in err and "since" in err


def test_thresholds_are_settings(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    data = _json(capsys, "--min-trip-nights", "30", "--min-gap-days", "11")
    assert data["settings"] == {"min_trip_nights": 30, "min_gap_days": 11, "min_home_nights": 14}
    assert _summary(data) == [
        ("home", "2026-03-01", "2026-03-28", "Home A"),
        ("home", "2026-03-29", "2026-05-29", "Home B"),
    ]
    [_a, b] = data["chapters"]
    assert b["nights"] == {"total": 62, "home": 37, "away": 25, "in_transit": 0}
    assert b["located_days"] == 52
    assert [p["name"] for p in b["places"]][:2] == ["Hotel Zürich", "Office B"]
    assert [p["name"] for p in b["people"]] == ["Ola Nordmann", "Per Hansen"]
    short = _json(capsys, "--min-home-nights", "3")
    assert ("home", "2026-03-14", "2026-03-18", "Parents") in _summary(short), "five nights now make a home"


def test_without_a_home_place_only_the_gap_splits_the_record(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    copy = tmp_path / "lb"
    _copy_record(
        record,
        copy,
        {name: {k: v for k, v in entry.items() if k != "kind"} for name, entry in PLACES.items()},
    )
    monkeypatch.setenv("LOGBOOK_HOME", str(copy))
    data = _json(capsys)
    assert data["home_history"] is None
    assert "no place of kind home" in data["warning"]
    assert _summary(data) == [
        ("home", "2026-03-01", "2026-04-09", None),
        ("gap", "2026-04-10", "2026-04-19", None),
        ("home", "2026-04-20", "2026-05-29", None),
    ]
    assert data["chapters"][0]["title"] == "home unknown"
    assert data["chapters"][0]["nights"]["away"] == 40, "without a home every night is away"
    text = _run(capsys)
    assert "no place of kind home" in text


def test_a_window_clips_the_chapters(
    record: Logbook, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOGBOOK_HOME", str(record.root))
    data = _json(capsys, "--since", "2026-04-25", "--until", "2026-05-10")
    cut = "ten nights of a trip cut by the window are not a long trip; six nights at B still name the home"
    assert _summary(data) == [("home", "2026-04-25", "2026-05-10", "Home B")], cut
    assert data["chapters"][0]["nights"] == {"total": 16, "home": 6, "away": 10, "in_transit": 0}
    assert _json(capsys, "--year", "2025") == {
        "window": None,
        "home_history": None,
        "settings": data["settings"],
        "chapters": [],
    }
    assert "no days" in _run(capsys, "--year", "2025")


def _copy_record(source: Logbook, target: Path, places: dict[str, Any]) -> None:
    """The same lines under another `places.json`, so a module's record is never edited."""
    import shutil

    shutil.copytree(source.root, target, ignore=shutil.ignore_patterns("index.sqlite*"))
    (target / "places.json").write_text(json.dumps(places), encoding="utf-8")


def test_the_lab_commands_defaults_are_the_chapters_modules():
    """`lab chapters --help` names the defaults without importing the labs tier (the split keeps
    `--help` lazy); the copies in the command module are held to the module that owns them."""
    from logbook.commands import lab as lab_command
    from logbook.labs import chapters

    assert lab_command.MIN_TRIP_NIGHTS == chapters.MIN_TRIP_NIGHTS
    assert lab_command.MIN_GAP_DAYS == chapters.MIN_GAP_DAYS
    assert lab_command.MIN_HOME_NIGHTS == chapters.MIN_HOME_NIGHTS
